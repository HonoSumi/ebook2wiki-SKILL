#!/usr/bin/env python3
"""
YAML → JSON 转换工具（严格模式）
    - 只接受标准 5 字段：名词、分类、解释、书中原文、网络来源
    - 无自动别名映射 — 字段名不匹配直接拒绝
    - 每条记录 5 字段必须齐全且非空
    - 出现任何额外字段直接拒绝
    - 退出码非零 = 转换失败，subagent 需要重做

用法:
    python yaml_to_json.py <input.yaml>
"""

import os
import sys
import re
import json
import subprocess
import argparse


def ensure_dependencies():
    try:
        import yaml
    except ImportError:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyyaml"],
            stdout=subprocess.DEVNULL
        )

ensure_dependencies()

import yaml

REQUIRED_FIELDS = {"名词", "分类", "解释", "书中原文", "网络来源"}
REQUIRED_FIELDS_LIST = ["名词", "分类", "解释", "书中原文", "网络来源"]
ALLOWED_CATEGORIES = {"人物", "地点", "物件", "事件", "概念", "习俗"}


def _update_plan_status(yaml_path, status, keyword_count=None):
    """
    更新 _plan.json 中对应 chunk 的状态和关键词数。
    从 YAML 文件名提取 seq，在父目录找 _plan.json。
    """
    try:
        base = os.path.basename(yaml_path)
        m = re.search(r'_(\d+)\.yaml$', base)
        if not m:
            return
        seq = int(m.group(1))
        plan_path = os.path.join(os.path.dirname(yaml_path), '_plan.json')
        if not os.path.exists(plan_path):
            return
        with open(plan_path, 'r', encoding='utf-8') as f:
            plan = json.load(f)
        for c in plan.get('chunks', []):
            if c.get('seq') == seq:
                c['status'] = status
                if keyword_count is not None:
                    c['keyword_count'] = keyword_count
                break
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # plan.json 更新失败不影响主要功能


def validate_record(record, index):
    """
    校验单条记录。通过返回 True，否则抛出 ValueError。
    """
    if not isinstance(record, dict):
        raise ValueError(
            f"[条目 {index}] 不是字典类型（实际: {type(record).__name__}）\n"
            f"  YAML 格式必须为:\n"
            f"  - 名词: xxx\n"
            f"    分类: 物件\n"
            f"    解释: |\n"
            f"      ...\n"
            f"    书中原文: |\n"
            f"      ...\n"
            f"    网络来源: |\n"
            f"      ..."
        )

    actual_keys = set(record.keys())

    # 检查额外字段
    extra = actual_keys - REQUIRED_FIELDS
    if extra:
        raise ValueError(
            f"[条目 {index}] 包含不认识的字段: {sorted(extra)}\n"
            f"  只允许这 5 个字段: {REQUIRED_FIELDS_LIST}\n"
            f"  实际字段: {sorted(actual_keys)}"
        )

    # 检查缺失字段
    missing = REQUIRED_FIELDS - actual_keys
    if missing:
        raise ValueError(
            f"[条目 {index}] 缺少字段: {sorted(missing)}\n"
            f"  必须包含全部 5 个字段: {REQUIRED_FIELDS_LIST}\n"
            f"  实际字段: {sorted(actual_keys)}"
        )

    # 按固定顺序检查字段值
    for field in REQUIRED_FIELDS_LIST:
        val = record.get(field, "")
        if not isinstance(val, str) or not val.strip():
            raise ValueError(
                f"[条目 {index}] 字段「{field}」为空或不是字符串\n"
                f"  实际值: {repr(val)}"
            )

    return True


def check_categories(records):
    """
    批量检查所有条目的分类，收集所有不合规项一起报告。
    """
    violations = []
    for i, item in enumerate(records, 1):
        cat_val = item.get("分类", "").strip()
        if cat_val not in ALLOWED_CATEGORIES:
            noun = item.get("名词", "?").strip()
            violations.append(f"  第 {i} 条: 名词「{noun}」分类为「{cat_val}」")

    if violations:
        msg = (
            f"以下 {len(violations)} 条记录的「分类」字段不在允许列表中（{sorted(ALLOWED_CATEGORIES)}）：\n"
            + "\n".join(violations)
            + "\n请将所有分类修改为以上值之一，不要自行创造分类名。"
        )
        raise ValueError(msg)


def strip_trailing_newlines(obj):
    if isinstance(obj, str):
        return obj.rstrip("\n")
    elif isinstance(obj, dict):
        return {k: strip_trailing_newlines(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [strip_trailing_newlines(item) for item in obj]
    return obj


def convert(yaml_path, json_path=None, keep_yaml=True):
    if not os.path.exists(yaml_path):
        print(f"错误: 文件不存在 — {yaml_path}", file=sys.stderr)
        _update_plan_status(yaml_path, "failed")
        sys.exit(1)

    # 读取 YAML
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # 空文件
    if data is None:
        print(f"警告: {yaml_path} 内容为空，生成空 JSON 数组")
        data = []

    # 检测非法顶层结构
    if not isinstance(data, list):
        fmt = "object (dict)" if isinstance(data, dict) else type(data).__name__
        print(
            f"错误: {yaml_path} 顶层结构不是数组，而是 {fmt}\n"
            f"  YAML 每一层必须以「- 名词:」开头，形成列表。\n"
            f"  正确格式:\n"
            f"    - 名词: xxx\n"
            f"      解释: |\n"
            f"        ...\n"
            f"    - 名词: yyy\n"
            f"      解释: |\n"
            f"        ...",
            file=sys.stderr
        )
        _update_plan_status(yaml_path, "failed")
        sys.exit(1)

    # 清洗
    data = strip_trailing_newlines(data)

    # 逐条校验（全部通过才输出）
    errors = []
    for i, record in enumerate(data, 1):
        try:
            validate_record(record, i)
        except ValueError as e:
            errors.append(str(e))

    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"\n总计 {len(errors)} 条记录不合格，拒绝生成 JSON。请修正 YAML 后重试。", file=sys.stderr)
        print(f"提示: yaml_to_json.py 只接受以下严格格式:", file=sys.stderr)
        print(f"  - 名词: xxx", file=sys.stderr)
        print(f"    分类: 物件", file=sys.stderr)
        print(f"    解释: |", file=sys.stderr)
        print(f"      中文解释内容", file=sys.stderr)
        print(f"    书中原文: |", file=sys.stderr)
        print(f"      书中出现的原文句子", file=sys.stderr)
        print(f"    网络来源: |", file=sys.stderr)
        print(f"      https://...", file=sys.stderr)
        _update_plan_status(yaml_path, "failed")
        sys.exit(1)

    # 分类批量校验 — 一次性收集所有不合规分类
    try:
        check_categories(data)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        _update_plan_status(yaml_path, "failed")
        sys.exit(1)

    # 确定输出路径
    if json_path is None:
        json_path = os.path.splitext(yaml_path)[0] + ".json"

    # 写出 JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 验证 JSON 可重新解析
    with open(json_path, "r", encoding="utf-8") as f:
        re_parsed = json.load(f)

    count = len(re_parsed)
    print(f"转换完成: {yaml_path} → {json_path}（{count} 条记录，全部校验通过）")
    _update_plan_status(yaml_path, "completed", keyword_count=count)

    # 自动追加到去重列表（检测同目录下的 already_searched.txt）
    tmp_dir = os.path.dirname(os.path.abspath(yaml_path))
    dedup_list = os.path.join(tmp_dir, "already_searched.txt")
    if count > 0 and os.path.exists(dedup_list):
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        manage_py = os.path.join(scripts_dir, "manage_keywords.py")
        result = subprocess.run(
            [sys.executable, manage_py, "append-from-json", dedup_list, json_path],
            capture_output=True, text=True, encoding='utf-8'
        )
        if result.returncode == 0:
            print(f"  去重列表已更新: {dedup_list}")
        else:
            print(f"  警告: 去重列表更新失败 — {result.stderr.strip()}")

    if not keep_yaml:
        os.remove(yaml_path)

    return data


def main():
    parser = argparse.ArgumentParser(description="YAML → JSON 转换工具（严格模式）")
    parser.add_argument("input", help="输入的 YAML 文件路径")
    parser.add_argument("--output", help="输出的 JSON 文件路径（默认: 同目录同文件名.json）")
    parser.add_argument("--keep-yaml", action="store_true", default=True,
                        help="保留原始 YAML 文件（默认保留）")
    parser.add_argument("--no-keep-yaml", action="store_false", dest="keep_yaml",
                        help="转换后删除原始 YAML 文件")
    args = parser.parse_args()

    convert(args.input, args.output, args.keep_yaml)


if __name__ == "__main__":
    main()
