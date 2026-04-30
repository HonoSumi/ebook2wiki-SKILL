---
name: ebook2wiki
description: >
  从电子书中提取结构化知识并生成静态 Wiki 站点的完整工作流。
  支持 PDF / EPUB / MOBI / TXT / MD 等多种电子书格式。
  特点：(1) 分块处理避免上下文爆炸，绝不直接读取全书；
  (2) 每次最多 5 个文本块并行通过 subagent 提取名词，结合互联网检索给出解释；
  (3) 5 字段结构：名词（原文用词）、分类、解释、书中原文、网络来源；
  (4) 汇总到 SQLite 数据库后，自动生成分类导航的静态 Wiki 页面。
  当用户需要"提取电子书知识"、"做读书笔记"、"整理书中人物/事件"、
  "归档书中概念"、"结构化电子书内容"时务必使用此 skill。
  也适用于用户想从书中提取具有民族特色或地方特色的文化元素时。
---

# 电子书知识提取 → Wiki 生成工作流

## 核心原则

0. **断点续传** — 每次启动必须先检测断点（扫描 `{book_name}_*.json` 文件），有已完成块则从断点继续，无断点才全新开始。严禁不检查直接从头处理。
1. **禁止直接读取整本电子书** — 对电子书的访问仅限于读取文件名、目录列表和分块后的文本块
2. **分块处理** — 每个文本块约 5000 字符，块间 100 字符重叠，保证上下文连贯但不溢出
3. **有限并行处理** — 文本块以 batch 方式处理，每批最多 5 个 subagent 并行，批内完成后才启动下一批。既利用并发加速，又避免瞬时上下文爆炸和资源争抢
4. **知识型条目优先，严禁单词收集** — 提取的是"知识点"而非"名词"。判断标准：该条目是否有足够的知识密度，值得出现在维基百科上？如果是，才提取。主角名字、普通日常物品、通用概念、**可查英汉词典获得的普通英语词汇**一律不收录
5. **纯词汇输出** — 关键词文件只允许包含纯词汇（每行一个），禁止写入类别名、分组标题、分隔线等任何非词汇内容
6. **互联网辅助** — 对每个条目检索互联网，结合书中内容进行解释，不做纯虚构
7. **名词字段原文约束（铁律）** — `名词` 字段必须使用**书中原文用词**，禁止模型自行翻译、改写、添加括号注释或任何形式的解释性文字。英文书则保留英文，日文书则保留日文，不得擅自转换为其他语言。禁止出现如「White Walkers（异鬼）」「Hogwarts（霍格沃茨魔法学校）」等括号注释形式——括号注释是词典，不是百科条目名。
8. **YAML 五字段约束（铁律）** — 每个知识条目**严格且只有** 5 个字段：`名词`、`分类`、`解释`、`书中原文`、`网络来源`。字段名必须**完全一致**（繁体简体都必须是"名词""分类""解释""书中原文""网络来源"），不得使用别名（如"关键字""出处""来源""类别""标签""references""category"）。字段值必须是**纯字符串**，禁止使用列表、子对象等复杂类型。违反此约束的条目会被 `yaml_to_json.py` 拒绝（退出码 1），subagent 必须重做。
9. **六分类约束（铁律）** — 每个知识条目的「分类」字段必须精确匹配以下 6 个值之一：`人物`、`地点`、`物件`、`事件`、`概念`、`习俗`。`yaml_to_json.py` 中包含分类白名单校验，不在范围内的分类直接拒绝（退出码 1），subagent 必须重做。
10. **subagent 静默模式** — subagent 只产出文件，禁止在最终消息中输出任何总结、表格、分类、类别名或分析。最多一句话确认完成。

## 前置条件

- Python 3.7+
- 八个固化脚本在 `scripts/` 目录下：
  - `chunk_ebook.py` — 电子书分段
  - `detect_checkpoint.py` — 断点检测（判断 FRESH / INCOMPLETE / COMPLETE）
  - `chunk_step2.py` — subagent 步骤 2：去重 + 自动完成
  - `yaml_to_json.py` — 将 subagent 输出的 YAML 转为标准 JSON（严格校验 5 字段）
  - `check_chunk_output.py` — 主 agent 产物检视
  - `merge_to_sqlite.py` — 合并 JSON 到 SQLite
  - `manage_keywords.py` — 管理 `already_searched.txt` 关键词去重列表
  - `generate_wiki.py` — 从 SQLite 数据库生成静态 Wiki 站点

在整个工作流中，`{scripts_dir}` 表示当前 skill 的 `scripts/` 子目录的**绝对路径**（不依赖 CWD）。主 Agent 应自行解析：SKILL.md 所在目录下的 `scripts/` 子目录即为 `{scripts_dir}`。

---

## 详细工作步骤

### 步骤 0：创建/检查工作目录

`{tmp_dir}` = `{book_name}_tmp`（与电子书同目录）。

检查 `{tmp_dir}` 是否存在。若不存在则创建：

```
mkdir -p "{tmp_dir}"
```

### 步骤 1：检测断点（先于分片）

**这是首要步骤。** 运行 `detect_checkpoint.py`：

```bash
python "{scripts_dir}/detect_checkpoint.py" "{tmp_dir}"
```

根据输出决定走向：

| 输出 | 含义 | 处理方式 |
|------|------|---------|
| `FRESH` | 无已有分片和计划 | → 步骤 2（分片），完成后继续步骤 4 |
| `INCOMPLETE:N:M:next` | N/M 块完成，下一块序号为 next | → 步骤 4，从 next 断点继续 |
| `COMPLETE:M` | 全部 M 块已完成 | → 跳到步骤 5（合并） |

### 步骤 2：分段电子书（仅在无分片时执行）

若步骤 1 检测到无已有分片，使用固化脚本 `chunk_ebook.py` 将电子书分割为多个重叠的小文本块。

```bash
python "{scripts_dir}/chunk_ebook.py" <电子书路径> --chunk-size 5000
```

脚本会自动：
1. 检测文件格式并提取全文
2. 自动安装所需 Python 依赖
3. 分割为约 5000 字符的文本块（块间重叠约 100 字符）
4. 将文本块保存到 `{tmp_dir}/{book_name}_1.txt`、`{book_name}_2.txt`… 中（无前导零）
5. 生成 `_plan.json` 处理计划文件

**务必使用此脚本执行分段，不要手动分段。**

如果脚本执行成功，会输出类似：
```
[4/4] 写入处理计划: _plan.json
============================================================
完成! 所有文本块已保存到: 百年孤独_tmp
计划列表: 共 42 个文本块待处理
============================================================
```

### 步骤 3（可选）：初始化关键词去重列表

如果 `{tmp_dir}/already_searched.txt` 不存在，新建空文件：

```bash
touch "{tmp_dir}/already_searched.txt"
```

去重由 `chunk_step2.py` 和 `yaml_to_json.py` 自动维护，无需手动编辑。

### 步骤 4：串行提取每个文本块的知识（subagent 隔离处理）

每个文本块的全部处理委托给独立的 subagent。主流程只负责串行调度、产物检视、汇报进度。

#### subagent prompt 来源

唯一的 subagent prompt 在 `references/subagent_prompt_template.md`。SKILL.md 不含任何 subagent prompt 内容。

启动 subagent 时：
1. Read `references/subagent_prompt_template.md`
2. 填写参数占位符（见下表）
3. 通过 Agent 工具发送

必要占位符：
| 占位符 | 说明 | 示例 |
|--------|------|------|
| `{book_name}` | 书名（不含扩展名，无路径） | `Harry Potter and the Philosophers Stone` |
| `{tmp_dir}` | 工作目录绝对路径 | `E:/ebook-kb/Harry Potter and the Philosophers Stone_tmp` |
| `{seq}` | 当前文本块序号 | `18` |
| `{total}` | 总文本块数 | `90` |
| `{chunk_filepath}` | 文本块文件绝对路径 | `E:/ebook-kb/..._tmp/..._18.txt` |
| `{scripts_dir}` | 脚本目录绝对路径 | `{skill_root}/scripts/`（skill 根目录下的 `scripts/` 子目录） |

#### 处理流程

1. **跳过已完成** — `_plan.json` 中 status 为 `completed` 或 `failed` 的块跳过

2. **告知用户** — `[003/042] 正在处理 第 3 块……`

3. **启动 subagent** — 读取模板 → 填参数 → 发送

4. **产物检视（subagent 返回后）**：
   ```bash
   python "{scripts_dir}/check_chunk_output.py" "{tmp_dir}" "{book_name}" "{seq}"
   ```
   脚本自动检查 JSON 存在性、字段完整性、分类合规性、plan 状态。根据中间产物残留输出不同级别的诊断信息：`OK: N 条记录`、`MISSING: <阶段>`、`ERROR: <详情>`

5. **汇报进度** — `[003/042] 第 3 块 → 5 个关键词，累计 23 个`
   **不要复述 subagent 输出的任何内容。**

6. **失败处理** — 产物检视失败则重试该块，连续 3 次失败则跳过

#### 并行调度约束

- **分批并行，整体串行** — 工作流步骤 0→1→2→3→4→5→6 严格顺序执行，但在步骤 4 内部以 batch 方式并行：
  - 每批最多 **5 个 subagent 同时运行**，将待处理块按 5 个一组分批
  - 同一批内的 subagent 并行启动（在一条消息中同时发出多个 Agent 工具调用）
  - 等待当前批次**全部完成**（含产物检视）后，才启动下一批
  - 失败的块在批次末尾单独重试，连续 3 次失败则跳过
- **平衡原则** — 5 个并行是上限而非目标。小块（≤20 块）可适当减少并行数（2-3 个），避免不必要的上下文开销。大书（>80 块）用满 5 个并行以加速

### 步骤 5：合并到 SQLite

所有文本块处理完毕后，使用固化脚本 `merge_to_sqlite.py` 合并所有 JSON 到 SQLite 数据库。

```bash
python "{scripts_dir}/merge_to_sqlite.py" <json_dir>
# 例如: python "{scripts_dir}/merge_to_sqlite.py" 百年孤独_tmp
```

其中 `<json_dir>` 就是步骤 0/2 中创建/使用的 `{书名}_tmp/` 目录。

脚本会自动：
1. 扫描目录下的所有 `*.json` 文件（排除 `_` 开头的）
2. 校验每个条目的分类是否在 6 个允许值中（不在则一次性报错退出）
3. 按名词去重（不区分大小写），合并解释、原文和来源
4. 写入 SQLite 数据库，文件名为 `{书名}.db`
5. 输出统计信息

**如果脚本因分类校验失败退出** — 脚本会列出所有 JSON 文件中不合规的条目（文件、序号、名词、错误分类）。此时主 Agent 必须：

1. 读取报错中提到的每个 JSON 文件
2. 对每个不合规的条目，根据其内容（名词、解释、原文）从 `人物/地点/物件/事件/概念/习俗` 中选择最合适的分类
3. 只修改该条目的「分类」字段，保留其他 4 个字段不变
4. 写回 JSON 文件
5. 重新运行 `merge_to_sqlite.py`，直到所有分类合规

脚本执行完成后，向用户汇报最终统计：

```
处理完成统计
────────────────────────────────
总文本块数:    42
总原始条目:    587
去重后条目:    423
数据库文件:    百年孤独.db
────────────────────────────────
```

### 步骤 6：生成静态 Wiki 站点

合并完成后，根据电子书的基调选择主题，然后使用 `generate_wiki.py` 生成静态 Wiki。

#### 6a：确定主题

主 Agent 根据电子书的**内容基调**选择主题枚举值（无需脚本，直接判断）：

| 主题枚举 | 风格 | 适用场景 |
|----------|------|---------|
| `ink` | 水墨黑白 | 古典文学、历史著作、哲学 |
| `parchment` | 羊皮纸暖黄 | 奇幻小说、历史小说、探险 |
| `sky` | 天空浅蓝 | 科幻小说、科技类 |
| `forest` | 森林绿意 | 自然散文、游记、田园 |
| `obsidian` | 暗色深邃 | 悬疑推理、哥特、恐怖 |
| `sakura` | 樱花粉白 | 日本文学、轻小说、俳句 |

选择原则：根据书名、内容风格判断即可，不必纠结边界情况。默认使用 `parchment`。

#### 6b：执行生成

```bash
python "{scripts_dir}/generate_wiki.py" <db_path> --theme <theme_name>
# 例如: python "{scripts_dir}/generate_wiki.py" "E:/ebook-kb/百年孤独.db" --theme ink
```

脚本自动：
1. 读取 SQLite 数据库中的 nouns 表
2. 按「分类」字段聚合条目
3. 在电子书同级目录生成 `{书名}_wiki.html`（首页入口），以及 `{书名}_wiki/` 子目录（分类页和详情页）：
   - `{书名}_wiki.html` — 首页，按分类展示所有条目
   - `{书名}_wiki/{分类}/index.html` — 该分类下所有条目的列表
   - `{书名}_wiki/{分类}/{条目}.html` — 单条知识点的详情页（解释、书中原文、参考链接）
4. 自动应用选中主题的配色和排版

Wiki 不需要服务器，直接用浏览器打开 `{书名}_wiki.html` 即可浏览。

主题配置文件位于 skill 的 `themes/` 目录下，每个主题一个 JSON 文件。如需查看或调整配色，可直接编辑对应文件。

---

## 输出说明

### SQLite 数据库结构

库文件 `{书名}.db` 包含两个表：

**nouns 表** — 知识条目：

| 列名 | 说明 |
|------|------|
| noun | 名词（主键，不区分大小写去重） |
| category | 分类 |
| explanation | 综合解释 |
| original_text | 书中原文片段 |
| source_urls | 网络来源 URL |
| created_at | 创建时间 |
| updated_at | 更新时间 |

**metadata 表** — 处理元信息：

| 列名 | 说明 |
|------|------|
| key | 元信息键名 |
| value | 元信息值 |

查询示例：
```sql
SELECT noun, category, length(explanation) as expl_len FROM nouns ORDER BY expl_len DESC LIMIT 10;
SELECT noun, source_urls FROM nouns WHERE source_urls != '' LIMIT 10;
SELECT category, COUNT(*) FROM nouns GROUP BY category ORDER BY COUNT(*) DESC;
```

### 静态 Wiki 结构

```
{书名}_wiki.html           # 首页入口 — 按分类卡片展示，位于电子书同级目录
{书名}_wiki/
├── {分类名}/
│   ├── index.html          # 该分类下的条目列表
│   ├── {条目名1}.html      # 单条知识点详情
│   ├── {条目名2}.html
│   └── ...
```

---

## 错误处理

### subagent 处理失败
如果某个文本块的 subagent 处理失败（超时、格式错误等），**重试该块**而不是跳到下一个。如果连续 3 次失败，跳过该块并在最终报告中注明。重试时 `already_searched.txt` 中的关键词不会被重复搜索，不会浪费 token。

### 分段脚本失败
如果 `chunk_ebook.py` 失败，先检查文件格式是否支持。对于不支持的格式（如 MOBI 且没有 calibre），提示用户转换格式。

### 合并脚本失败
如果 `merge_to_sqlite.py` 失败，检查 JSON 文件是否完整。可以手动修复损坏的 JSON 后重试。

### Wiki 生成失败
如果 `generate_wiki.py` 失败，检查数据库文件路径是否正确。脚本已自动兼容旧版无 category 列的数据库。

---

## 使用范例

用户说："帮我提取《百年孤独》这本书的知识点"

你会回答好的，然后执行：
1. 检查 `百年孤独_tmp/` 目录是否存在，检测断点 → 判断是否为全新处理
2. 若为全新，运行 `python "{scripts_dir}/chunk_ebook.py" 百年孤独.epub` 分片
3. 确保 `百年孤独_tmp/already_searched.txt` 存在
4. 读取 `_plan.json` 列出文本块数，告知用户预计时间
5. 串行启动 subagent（从断点处开始），每个处理一个文本块的完整 pipeline
6. 每块完成后进行产物检视并汇报进度
7. 全部完成后运行 `python "{scripts_dir}/merge_to_sqlite.py" 百年孤独_tmp`
8. 展示最终统计
9. 判断主题（《百年孤独》→ `ink` 水墨风格），运行 `python "{scripts_dir}/generate_wiki.py" 百年孤独.db --theme ink`
10. 告知用户 Wiki 路径，用浏览器打开展示
