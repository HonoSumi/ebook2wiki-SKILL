#!/usr/bin/env python3
"""
关键词去重管理工具（去重左移）
维护 already_searched.txt，避免 subagent 重复搜索已提取过的关键词，节省 token。

格式: 一行一个，`序号: 关键词名称`
  1: 扎染
  2: 傩戏
  3: 土楼

用法:
    python manage_keywords.py read <filepath>
        读取已有关键词，以 ", " 拼接输出（供 subagent prompt 嵌入）

    python manage_keywords.py append-from-json <filepath> <json_path>
        从 YAML→JSON 转换后的 JSON 文件中提取所有"名词"字段，追加到列表
"""

import sys
import os
import re
import json


def read_keywords(filepath):
    """读取 already_searched.txt，返回关键词列表"""
    if not os.path.exists(filepath):
        return []
    keywords = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = re.match(r"\d+:\s*(.+)", line)
            if m:
                keywords.append(m.group(1).strip())
    return keywords


def append_keywords(filepath, new_keywords):
    """追加新关键词到 already_searched.txt（自动去重、自动编号）"""
    existing = read_keywords(filepath)
    existing_set = set(k.lower().strip() for k in existing)
    next_num = len(existing) + 1
    added = 0
    with open(filepath, "a", encoding="utf-8") as f:
        for kw in new_keywords:
            kw = kw.strip()
            if not kw:
                continue
            if kw.lower() not in existing_set:
                f.write(f"{next_num}: {kw}\n")
                existing_set.add(kw.lower())
                next_num += 1
                added += 1
    return added


def append_from_json(filepath, json_path):
    """从 JSON 文件中提取所有名词并追加"""
    if not os.path.exists(json_path):
        print(f"错误: JSON 文件不存在 — {json_path}", file=sys.stderr)
        return 0

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"错误: JSON 文件不是数组格式 — {json_path}", file=sys.stderr)
        return 0

    nouns = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        noun = entry.get("名词") or entry.get("noun") or ""
        noun = noun.strip()
        if noun:
            nouns.append(noun)

    if not nouns:
        return 0

    added = append_keywords(filepath, nouns)
    return added


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip())
        sys.exit(1)

    command = sys.argv[1]
    filepath = sys.argv[2]

    if command == "read":
        keywords = read_keywords(filepath)
        print(", ".join(keywords) if keywords else "")
    elif command == "append-from-json":
        if len(sys.argv) < 4:
            print("错误: append-from-json 需要 JSON 文件路径作为第三个参数", file=sys.stderr)
            sys.exit(1)
        json_path = sys.argv[3]
        added = append_from_json(filepath, json_path)
        print(f"  关键词: 新增 {added} 个，已写入 {filepath}")
    else:
        print(f"未知命令: {command}", file=sys.stderr)
        print("可用命令: read, append-from-json", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
