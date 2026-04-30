#!/usr/bin/env python3
"""
Step 2 of chunk processing: dedup check + auto-finish.

Usage:
    python chunk_step2.py <tmp_dir> <seq>

Behavior:
    - Reads keywords_{seq}.txt, checks against already_searched.txt
    - No new keywords: auto-writes empty JSON, updates _plan.json to completed, prints ALL_DUPES, exits 1
    - Has new keywords: writes filtered_{seq}.txt, prints NEW_KEYWORDS:<count>, exits 0
"""

import sys
import os
import re
import json

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    if len(sys.argv) < 3:
        print("Usage: python chunk_step2.py <tmp_dir> <seq>", file=sys.stderr)
        sys.exit(1)

    tmp_dir = sys.argv[1]
    seq = int(sys.argv[2])

    dedup_file = os.path.join(tmp_dir, "already_searched.txt")
    kw_file = os.path.join(tmp_dir, f"keywords_{seq}.txt")
    filtered_file = os.path.join(tmp_dir, f"filtered_{seq}.txt")
    plan_file = os.path.join(tmp_dir, "_plan.json")

    # Read plan to get book_name
    book_name = ""
    if os.path.exists(plan_file):
        with open(plan_file, "r", encoding="utf-8") as f:
            plan = json.load(f)
        book_name = plan.get("book_name", "")
    else:
        print(f"错误: _plan.json 不存在", file=sys.stderr)
        sys.exit(1)

    # Read existing dedup list
    existing = []
    if os.path.exists(dedup_file):
        with open(dedup_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"\d+:\s*(.+)", line)
                if m:
                    existing.append(m.group(1).strip())

    existing_set = set(k.lower().strip() for k in existing)

    # Read new keywords from keywords_{seq}.txt
    new_keywords = []
    if os.path.exists(kw_file):
        with open(kw_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip().strip('",\'')
                if not line:
                    continue
                if line.lower() not in existing_set:
                    new_keywords.append(line)

    if not new_keywords:
        # Auto-finish: write empty JSON, update plan
        json_path = os.path.join(tmp_dir, f"{book_name}_{seq}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([], f)

        for c in plan.get("chunks", []):
            if c.get("seq") == seq:
                c["status"] = "completed"
                c["keyword_count"] = 0
                break
        with open(plan_file, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)

        print(f"ALL_DUPES: 无新关键词，已写入空 JSON {json_path}")
        sys.exit(1)

    # Has new keywords: write filtered file
    os.makedirs(os.path.dirname(filtered_file) or ".", exist_ok=True)
    with open(filtered_file, "w", encoding="utf-8") as f:
        for kw in new_keywords:
            f.write(f"{kw}\n")

    # Also print to stdout
    for kw in new_keywords:
        print(kw)

    print(f"NEW_KEYWORDS:{len(new_keywords)}")
    sys.exit(0)


if __name__ == "__main__":
    main()
