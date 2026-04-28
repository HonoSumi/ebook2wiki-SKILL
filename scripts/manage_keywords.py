#!/usr/bin/env python3
"""
关键词去重管理工具
维护 already_searched.txt，避免重复搜索已提取过的关键词，节省 token。

格式: 一行一个，`序号: 关键词名称`
  1: 扎染
  2: 傩戏
  3: 土楼

用法:
    python manage_keywords.py read <filepath>
        读取已有关键词，以 ", " 拼接输出

    python manage_keywords.py append-from-json <filepath> <json_path>
        从 JSON 文件中提取所有"名词"字段，追加到列表

    python manage_keywords.py filter <filepath> --from-file <keywords_file> [--output <filtered_file>]
        从文件中读取关键词列表（每行一个），过滤出未搜索过的新关键词。
        将新关键词追加到 already_searched.txt，并输出到 stdout（每行一个）。
        可选的 --output 参数：将过滤结果写入文件（用于审计中间产物）。

    python manage_keywords.py filter <filepath> --stdin [--output <filtered_file>]
        从 stdin 读取关键词列表（每行一个或逗号分隔），过滤出新关键词。
        将新关键词追加到 already_searched.txt，并输出到 stdout（每行一个）。
        可选的 --output 参数：将过滤结果写入文件（用于审计中间产物）。
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


def filter_keywords(filepath, input_keywords):
    """
    过滤关键词：从 input_keywords 中找出未搜索过的，追加到文件，并返回新关键词列表。
    """
    existing = read_keywords(filepath)
    existing_set = set(k.lower().strip() for k in existing)

    new_keywords = []
    for kw in input_keywords:
        kw = kw.strip().strip('",\'')
        if not kw:
            continue
        if kw.lower() not in existing_set:
            new_keywords.append(kw)

    if new_keywords:
        append_keywords(filepath, new_keywords)

    return new_keywords


def read_keywords_from_file(keywords_file):
    """从文件读取关键词列表（每行一个，也支持逗号分隔）"""
    result = []
    with open(keywords_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # 支持逗号分隔的单行多关键词
            for part in line.split(","):
                part = part.strip()
                if part:
                    result.append(part)
    return result


def read_keywords_from_stdin():
    """从 stdin 读取关键词（每行一个，或逗号分隔）"""
    result = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        for part in line.split(","):
            part = part.strip()
            if part:
                result.append(part)
    return result


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

    elif command == "filter":
        input_keywords = []
        output_path = None

        # 解析 --output / -o
        for opt in ("--output", "-o"):
            if opt in sys.argv:
                idx = sys.argv.index(opt)
                if idx + 1 < len(sys.argv):
                    output_path = sys.argv[idx + 1]
                break

        if "--from-file" in sys.argv:
            idx = sys.argv.index("--from-file")
            if idx + 1 < len(sys.argv):
                input_keywords = read_keywords_from_file(sys.argv[idx + 1])
        elif "--stdin" in sys.argv:
            input_keywords = read_keywords_from_stdin()
        else:
            print("错误: filter 命令需要 --from-file 或 --stdin 参数", file=sys.stderr)
            sys.exit(1)

        new_keywords = filter_keywords(filepath, input_keywords)

        # stdout（供 AI 捕获为变量）
        for kw in new_keywords:
            print(kw)

        # --output 文件（供人工审计，即使为空也写出，确保每个 chunk 都有对应文件）
        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                for kw in new_keywords:
                    f.write(f"{kw}\n")

    else:
        print(f"未知命令: {command}", file=sys.stderr)
        print("可用命令: read, append-from-json, filter", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
