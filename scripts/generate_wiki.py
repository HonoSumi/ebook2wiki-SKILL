#!/usr/bin/env python3
"""
Static Wiki Generator — 从 SQLite 数据库生成分类导航的静态 HTML Wiki 站点。

用法:
    python generate_wiki.py <db_path> --theme <theme_name>

主题:
    ink       — 水墨黑白（古典文学、历史）
    parchment — 羊皮纸暖黄（奇幻、历史小说）
    sky       — 天空浅蓝（科幻、科技）
    forest    — 森林绿意（自然、散文）
    obsidian  — 暗色深邃（悬疑、哥特）
    sakura    — 樱花粉白（日本文学）

输出:
    在 DB 同级目录创建 {书名}_wiki/，包含完整静态站点。
"""

import os
import sys
import json
import sqlite3
import argparse
import html
from datetime import datetime

# ── helpers ──────────────────────────────────────────────────

CATEGORY_ORDER = ["人物", "地点", "物件", "事件", "概念", "习俗"]


def load_theme(theme_name, scripts_dir):
    """从 themes/ 目录加载主题 JSON"""
    theme_path = os.path.join(scripts_dir, "..", "themes", f"{theme_name}.json")
    if not os.path.exists(theme_path):
        print(f"警告: 主题 '{theme_name}' 不存在，使用默认 parchment", file=sys.stderr)
        theme_path = os.path.join(scripts_dir, "..", "themes", "parchment.json")
    with open(theme_path, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_filename(name):
    """将名称转为安全的文件名（保留 Unicode，仅替换文件系统不安全字符）"""
    unsafe = '<>:"/\\|?*'
    for ch in unsafe:
        name = name.replace(ch, "_")
    # 去掉首尾空白和点号（Windows 不允许末尾点号）
    return name.strip(" .")[:120]


def css_vars(theme):
    """从主题配置生成 CSS 变量块"""
    lines = [":root {"]
    for key, val in theme["colors"].items():
        lines.append(f"  {key}: {val};")
    for key, val in theme["fonts"].items():
        lines.append(f"  {key}: {val};")
    lines.append("}")
    return "\n".join(lines)


# ── HTML 模板 ────────────────────────────────────────────────

STYLE_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: var(--font-body);
    background: var(--bg);
    color: var(--text);
    line-height: 1.7;
    min-height: 100vh;
}

a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; color: var(--accent-hover); }

/* ── header ── */
.site-header {
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
    padding: 1.5rem 2rem;
    box-shadow: var(--shadow);
    position: sticky; top: 0; z-index: 10;
}
.site-header .title {
    font-family: var(--font-heading);
    font-size: 1.5rem; font-weight: 700;
    color: var(--heading); letter-spacing: 0.02em;
}
.site-header .subtitle { color: var(--text-muted); font-size: 0.85rem; margin-top: 0.2rem; }

/* ── breadcrumb ── */
.breadcrumb {
    padding: 0.75rem 2rem; font-size: 0.85rem; color: var(--text-muted);
}
.breadcrumb a { color: var(--text-secondary); }
.breadcrumb span { color: var(--text-muted); margin: 0 0.35rem; }

/* ── main layout ── */
.container { max-width: 920px; margin: 0 auto; padding: 1.5rem 2rem 3rem; }

/* ── category cards (index) ── */
.category-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 1.25rem;
    margin-top: 1.5rem;
}
.category-card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; padding: 1.25rem 1.5rem;
    box-shadow: var(--shadow);
    transition: box-shadow 0.2s, transform 0.15s;
}
.category-card:hover {
    box-shadow: var(--shadow-hover);
    transform: translateY(-2px);
}
.category-card h3 {
    font-family: var(--font-heading); font-size: 1.1rem;
    color: var(--heading); margin-bottom: 0.4rem;
}
.category-card .count { color: var(--text-muted); font-size: 0.85rem; }
.category-card .preview { color: var(--text-secondary); font-size: 0.85rem; margin-top: 0.5rem; }

/* ── view toggle ── */
.view-toggle-bar {
    display: flex; gap: 0.5rem; margin-bottom: 1.25rem;
}
.view-toggle-btn {
    padding: 0.4rem 1rem; border: 1px solid var(--border);
    border-radius: 6px; background: var(--bg-card); color: var(--text-secondary);
    cursor: pointer; font-family: var(--font-body); font-size: 0.85rem;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.view-toggle-btn:hover { border-color: var(--accent); color: var(--accent); }
.view-toggle-btn.active {
    background: var(--accent); color: #fff; border-color: var(--accent);
}

/* ── flat list (index all-entries view) ── */
.flat-list { margin-top: 0.5rem; }
.flat-item {
    display: block; padding: 0.75rem 1rem; border-bottom: 1px solid var(--divider);
    transition: background 0.15s;
}
.flat-item:hover { background: var(--bg-card); text-decoration: none; }
.flat-item .noun { font-weight: 600; color: var(--heading); }
.flat-item .cat-tag {
    display: inline-block; background: var(--tag-bg); color: var(--tag-text);
    font-size: 0.75rem; padding: 0.1rem 0.5rem; border-radius: 999px;
    margin-left: 0.5rem; vertical-align: middle;
}
.flat-item .snippet { color: var(--text-secondary); font-size: 0.85rem; margin-top: 0.2rem; }

/* ── hidden utility ── */
.view-hidden { display: none !important; }

/* ── entry list (category page) ── */
.entry-list { margin-top: 1rem; }
.entry-item {
    display: block; padding: 0.85rem 1rem; border-bottom: 1px solid var(--divider);
    transition: background 0.15s;
}
.entry-item:hover { background: var(--bg-card); text-decoration: none; }
.entry-item .noun { font-weight: 600; color: var(--heading); }
.entry-item .snippet { color: var(--text-secondary); font-size: 0.85rem; margin-top: 0.2rem; }

/* ── detail page ── */
.detail-card {
    background: var(--bg-detail); border: 1px solid var(--border);
    border-radius: 8px; padding: 2rem; box-shadow: var(--shadow);
}
.detail-card h1 {
    font-family: var(--font-heading); font-size: 1.6rem;
    color: var(--heading); margin-bottom: 0.5rem;
}
.detail-card .meta-tag {
    display: inline-block; background: var(--tag-bg); color: var(--tag-text);
    font-size: 0.8rem; padding: 0.2rem 0.65rem; border-radius: 999px;
    margin-bottom: 1.25rem;
}
.detail-section { margin-top: 1.5rem; }
.detail-section h2 {
    font-family: var(--font-heading); font-size: 1rem;
    color: var(--accent); margin-bottom: 0.5rem;
    padding-bottom: 0.35rem; border-bottom: 2px solid var(--divider);
}
.detail-section p { color: var(--text); white-space: pre-line; font-size: 0.95rem; }
.detail-section a { word-break: break-all; }

.source-url-item {
    display: block; padding: 0.3rem 0; color: var(--link);
    word-break: break-all;
}

/* ── footer ── */
.site-footer {
    text-align: center; padding: 1.5rem 2rem;
    color: var(--text-muted); font-size: 0.8rem;
    border-top: 1px solid var(--border); margin-top: 2rem;
}
"""


def render_page(title, body, theme, breadcrumb_html="", extra_head="", subtitle=""):
    """渲染完整 HTML 页面"""
    sub_html = f'\n  <div class="subtitle">{html.escape(subtitle)}</div>' if subtitle else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>
{css_vars(theme)}
{STYLE_CSS}
{extra_head}
</style>
</head>
<body>
<header class="site-header">
  <div class="title">{html.escape(title)}</div>{sub_html}
</header>
{breadcrumb_html}
<main class="container">
{body}
</main>
<footer class="site-footer">
  Generated by ebook2wiki &middot; {datetime.now().strftime("%Y-%m-%d %H:%M")}
</footer>
</body>
</html>"""


def build_breadcrumb(items, home_url="../index.html"):
    """生成面包屑导航 HTML。items: [(label, url_or_None), ...]"""
    parts = ['<nav class="breadcrumb">']
    parts.append(f'<a href="{home_url}">Home</a>')
    for label, url in items:
        parts.append('<span>/</span>')
        if url:
            parts.append(f'<a href="{url}">{html.escape(label)}</a>')
        else:
            parts.append(html.escape(label))
    parts.append('</nav>')
    return "\n".join(parts)


# ── 页面生成 ─────────────────────────────────────────────────

def build_index(categories, all_entries, book_name, theme, wiki_dir, wiki_prefix):
    """生成首页：分类卡片视图 + 无分类列表视图，通过按钮切换"""
    total = sum(len(v) for v in categories.values())

    # ── 分类视图：卡片网格 ──
    cards = []
    for cat in CATEGORY_ORDER:
        if cat not in categories or not categories[cat]:
            continue
        entries = categories[cat]
        preview = "、".join(e["noun"] for e in entries[:4])
        cat_enc = safe_filename(cat)
        cards.append(f"""<a class="category-card" href="{wiki_prefix}/{cat_enc}/index.html">
  <h3>{html.escape(cat)}</h3>
  <div class="count">{len(entries)} 个条目</div>
  <div class="preview">{html.escape(preview)}……</div>
</a>""")
    extras = {k: v for k, v in categories.items() if k not in CATEGORY_ORDER}
    for cat, entries in sorted(extras.items(), key=lambda x: len(x[1]), reverse=True):
        preview = "、".join(e["noun"] for e in entries[:4])
        cat_enc = safe_filename(cat)
        cards.append(f"""<a class="category-card" href="{wiki_prefix}/{cat_enc}/index.html">
  <h3>{html.escape(cat)}</h3>
  <div class="count">{len(entries)} 个条目</div>
  <div class="preview">{html.escape(preview)}……</div>
</a>""")

    # ── 列表视图：全部条目平铺 ──
    flat_items = []
    for entry in all_entries:
        noun_fn = safe_filename(entry["noun"])
        cat_enc = safe_filename(entry.get("category", "未分类"))
        snippet = (entry.get("explanation", "") or "")[:120].replace("\n", " ")
        cat_label = html.escape(entry.get("category", "未分类"))
        flat_items.append(f"""<a class="flat-item" href="{wiki_prefix}/{cat_enc}/{noun_fn}.html">
  <span class="noun">{html.escape(entry["noun"])}</span>
  <span class="cat-tag">{cat_label}</span>
  <div class="snippet">{html.escape(snippet)}</div>
</a>""")

    body = f"""<div class="view-toggle-bar">
  <button class="view-toggle-btn active" id="btn-cat-view" onclick="switchView('cat')">📂 分类视图</button>
  <button class="view-toggle-btn" id="btn-flat-view" onclick="switchView('flat')">📋 列表视图</button>
</div>
<p style="margin-bottom:0.5rem;color:var(--text-secondary)">
  知识库包含 <strong>{total}</strong> 个条目，
  分布在 <strong>{len(categories)}</strong> 个分类中。
</p>
<div class="category-grid" id="cat-view">
{chr(10).join(cards)}
</div>
<div class="flat-list view-hidden" id="flat-view">
{chr(10).join(flat_items)}
</div>"""

    extra_head = """.site-header .subtitle{display:block;}
.view-toggle-btn{font-family:inherit;}"""

    toggle_js = """<script>
function switchView(view) {
  var catView = document.getElementById('cat-view');
  var flatView = document.getElementById('flat-view');
  var btnCat = document.getElementById('btn-cat-view');
  var btnFlat = document.getElementById('btn-flat-view');
  if (view === 'cat') {
    catView.classList.remove('view-hidden');
    flatView.classList.add('view-hidden');
    btnCat.classList.add('active');
    btnFlat.classList.remove('active');
  } else {
    flatView.classList.remove('view-hidden');
    catView.classList.add('view-hidden');
    btnCat.classList.remove('active');
    btnFlat.classList.add('active');
  }
}
</script>"""

    html_page = render_page(
        f"{book_name} · 知识百科",
        body, theme,
        extra_head=extra_head,
        subtitle=f"{book_name} Knowledge Wiki"
    )
    # 在 </body> 前插入 JS
    html_page = html_page.replace("</body>", toggle_js + "\n</body>")

    with open(wiki_dir + ".html", "w", encoding="utf-8") as f:
        f.write(html_page)
    print(f"  首页: {os.path.basename(wiki_dir)}.html")


def build_category_page(cat, entries, book_name, theme, wiki_dir):
    """生成分类页：该分类下所有条目列表"""
    cat_enc = safe_filename(cat)
    cat_dir = os.path.join(wiki_dir, cat_enc)
    os.makedirs(cat_dir, exist_ok=True)

    items = []
    for e in entries:
        noun_fn = safe_filename(e["noun"])
        snippet = e.get("explanation", "")[:120].replace("\n", " ")
        items.append(f"""<a class="entry-item" href="{noun_fn}.html">
  <div class="noun">{html.escape(e["noun"])}</div>
  <div class="snippet">{html.escape(snippet)}</div>
</a>""")

    body = f"""<p style="color:var(--text-secondary);margin-bottom:1rem">{len(entries)} 个条目</p>
<div class="entry-list">
{chr(10).join(items)}
</div>"""
    home_url = f"../../{book_name}_wiki.html"
    bc = build_breadcrumb([(cat, None)], home_url=home_url)
    html_page = render_page(
        f"{html.escape(cat)} · {book_name}", body, theme, bc,
        extra_head=""
    )

    with open(os.path.join(cat_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_page)
    print(f"  分类页: {cat_enc}/index.html ({len(entries)} 条目)")


def build_detail_page(cat, entry, book_name, theme, wiki_dir):
    """生成详情页：单个知识点的详细解释"""
    cat_enc = safe_filename(cat)
    cat_dir = os.path.join(wiki_dir, cat_enc)
    os.makedirs(cat_dir, exist_ok=True)

    noun_fn = safe_filename(entry["noun"])

    expl = html.escape(entry.get("explanation", "")).replace("\n", "<br>")
    orig = html.escape(entry.get("original_text", "")).replace("\n", "<br>")
    urls = entry.get("source_urls", "").strip()
    category = html.escape(entry.get("category", cat))

    url_links = ""
    if urls:
        url_items = []
        for u in urls.split("\n"):
            u = u.strip()
            if u:
                url_items.append(f'<a class="source-url-item" href="{html.escape(u)}" target="_blank" rel="noopener">{html.escape(u)}</a>')
        url_links = "\n".join(url_items)

    body = f"""<div class="detail-card">
  <h1>{html.escape(entry["noun"])}</h1>
  <span class="meta-tag">{category}</span>

  <div class="detail-section">
    <h2>解释</h2>
    <p>{expl if expl else '<em style="color:var(--text-muted)">暂无解释</em>'}</p>
  </div>

  <div class="detail-section">
    <h2>书中原文</h2>
    <p>{orig if orig else '<em style="color:var(--text-muted)">暂无原文</em>'}</p>
  </div>

  <div class="detail-section">
    <h2>参考链接</h2>
    {url_links if url_links else '<p style="color:var(--text-muted)"><em>暂无参考链接</em></p>'}
  </div>
</div>"""

    home_url = f"../../{book_name}_wiki.html"
    bc = build_breadcrumb([
        (entry.get("category", cat), "index.html"),
        (entry["noun"], None),
    ], home_url=home_url)
    html_page = render_page(
        f"{html.escape(entry['noun'])} · {book_name}", body, theme, bc
    )

    filepath = os.path.join(cat_dir, f"{noun_fn}.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_page)


# ── 主入口 ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="从 SQLite 生成静态 Wiki 站点")
    parser.add_argument("db_path", help="SQLite 数据库文件路径")
    parser.add_argument("--theme", default="parchment",
                        choices=["ink", "parchment", "sky", "forest", "obsidian", "sakura"],
                        help="主题方案（默认: parchment）")
    parser.add_argument("--output", help="输出目录（默认: DB 同级 {书名}_wiki）")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db_path)
    if not os.path.exists(db_path):
        print(f"错误: 数据库文件不存在 — {db_path}", file=sys.stderr)
        sys.exit(1)

    scripts_dir = os.path.dirname(os.path.abspath(__file__))

    # 加载主题
    theme = load_theme(args.theme, scripts_dir)
    print(f"主题: {theme['name']} — {theme['description']}")

    # 连接数据库
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 确定 book_name
    book_name = os.path.splitext(os.path.basename(db_path))[0]

    # 确定输出目录
    if args.output:
        wiki_dir = os.path.abspath(args.output)
    else:
        wiki_dir = os.path.join(os.path.dirname(db_path), f"{book_name}_wiki")
    os.makedirs(wiki_dir, exist_ok=True)

    print(f"书籍: {book_name}")
    print(f"输出: {wiki_dir}")
    print()

    # 读取所有条目
    # 兼容旧数据库无 category 列
    try:
        cur.execute("SELECT noun, category, explanation, original_text, source_urls FROM nouns ORDER BY noun")
    except sqlite3.OperationalError:
        # 旧表无 category 列 — 全部归入未分类
        cur.execute("SELECT noun, explanation, original_text, source_urls FROM nouns ORDER BY noun")
        rows_raw = cur.fetchall()
        rows = []
        for r in rows_raw:
            rows.append({
                "noun": r["noun"],
                "category": "未分类",
                "explanation": r["explanation"],
                "original_text": r["original_text"],
                "source_urls": r["source_urls"],
            })
    else:
        rows = [dict(r) for r in cur.fetchall()]

    conn.close()

    if not rows:
        print("数据库中没有条目，生成空站点。")
        index_path = wiki_dir + ".html"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(render_page(
                f"{book_name} · 知识百科", "<p>暂无条目</p>", theme
            ))
        print(f"  首页: {os.path.basename(index_path)}")
        return

    # 按分类分组
    categories = {}
    for row in rows:
        cat = row.get("category", "未分类").strip()
        if not cat:
            cat = "未分类"
        categories.setdefault(cat, []).append(row)

    wiki_prefix = os.path.basename(wiki_dir)

    print(f"[1/3] 生成首页...")
    build_index(categories, rows, book_name, theme, wiki_dir, wiki_prefix)

    print(f"[2/3] 生成分类页和详情页...")
    # 先按固定顺序输出 6 个标准分类
    for cat in CATEGORY_ORDER:
        if cat in categories:
            entries = categories[cat]
            build_category_page(cat, entries, book_name, theme, wiki_dir)
            for entry in entries:
                build_detail_page(cat, entry, book_name, theme, wiki_dir)
    # 再输出不在固定顺序中的分类（旧数据兼容），按条目数降序
    extras = {k: v for k, v in categories.items() if k not in CATEGORY_ORDER}
    for cat, entries in sorted(extras.items(), key=lambda x: len(x[1]), reverse=True):
        build_category_page(cat, entries, book_name, theme, wiki_dir)
        for entry in entries:
            build_detail_page(cat, entry, book_name, theme, wiki_dir)

    print(f"[3/3] 完成!")
    print()
    print(f"{'='*60}")
    print(f"Wiki 首页: {wiki_dir}.html")
    print(f"Wiki 资源: {wiki_dir}/")
    print(f"总条目: {len(rows)}")
    print(f"分类数: {len(categories)}")
    print(f"用浏览器打开 {os.path.basename(wiki_dir)}.html 即可浏览")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
