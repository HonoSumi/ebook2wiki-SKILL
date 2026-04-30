#!/usr/bin/env python3
"""
Check chunk output after subagent finishes.

Usage:
    python check_chunk_output.py <tmp_dir> <book_name> <seq>

Exit codes:
    0 — OK (JSON valid, plan updated)
    1 — MISSING (no JSON file)
    2 — ERROR (JSON invalid / plan not updated)

Prints one line:
    OK: N 条记录
    MISSING: <reason>
    ERROR: <detail>
"""

import sys
import os
import json

ALLOWED_CATEGORIES = {"人物", "地点", "物件", "事件", "概念", "习俗"}

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main():
    if len(sys.argv) < 4:
        print("Usage: python check_chunk_output.py <tmp_dir> <book_name> <seq>", file=sys.stderr)
        sys.exit(2)

    tmp_dir = sys.argv[1]
    book_name = sys.argv[2]
    seq = int(sys.argv[3])

    json_path = os.path.join(tmp_dir, f"{book_name}_{seq}.json")
    plan_path = os.path.join(tmp_dir, "_plan.json")

    # Check JSON exists
    if not os.path.exists(json_path):
        # Determine where it failed
        yaml_path = os.path.join(tmp_dir, f"{book_name}_{seq}.yaml")
        filtered_path = os.path.join(tmp_dir, f"filtered_{seq}.txt")
        kw_path = os.path.join(tmp_dir, f"keywords_{seq}.txt")

        if os.path.exists(yaml_path):
            print(f"MISSING: JSON 不存在，YAML 存在（yaml_to_json 未执行）")
        elif os.path.exists(filtered_path):
            print(f"MISSING: JSON/YAML 不存在，filtered 存在（步骤 3 未完成）")
        elif os.path.exists(kw_path):
            print(f"MISSING: JSON/YAML 不存在，keywords 存在（步骤 2 未完成）")
        else:
            print(f"MISSING: 无任何中间产物")
        sys.exit(1)

    # Validate JSON content
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: JSON 解析失败 — {e}")
        sys.exit(2)

    if not isinstance(data, list):
        print(f"ERROR: JSON 顶层不是数组")
        sys.exit(2)

    # Validate each record's fields
    for i, item in enumerate(data, 1):
        if not isinstance(item, dict):
            print(f"ERROR: 第 {i} 条不是对象")
            sys.exit(2)
        for field in ["名词", "分类", "解释", "书中原文", "网络来源"]:
            if field not in item:
                print(f"ERROR: 第 {i} 条缺少字段「{field}」")
                sys.exit(2)
            if not isinstance(item[field], str) or not item[field].strip():
                print(f"ERROR: 第 {i} 条字段「{field}」为空")
                sys.exit(2)

    # Validate category is in whitelist — collect all violations first
    violations = []
    for i, item in enumerate(data, 1):
        cat_val = item.get("分类", "").strip()
        if cat_val not in ALLOWED_CATEGORIES:
            noun = item.get("名词", "?").strip()
            violations.append(f"  第 {i} 条: 名词「{noun}」分类为「{cat_val}」")

    if violations:
        print(f"ERROR: 以下 {len(violations)} 条记录的「分类」字段不在允许列表中（{sorted(ALLOWED_CATEGORIES)}）：")
        print("\n".join(violations))
        sys.exit(2)

    # Check plan.json status
    if os.path.exists(plan_path):
        with open(plan_path, "r", encoding="utf-8") as f:
            plan = json.load(f)
        for c in plan.get("chunks", []):
            if c.get("seq") == seq:
                if c.get("status") != "completed":
                    print(f"ERROR: plan 状态为 {c.get('status')}，不是 completed")
                    sys.exit(2)
                break

    count = len(data)
    if count == 0:
        print(f"OK: 0 条记录（空数组）")
    else:
        print(f"OK: {count} 条记录")
    sys.exit(0)


if __name__ == "__main__":
    main()
