#!/usr/bin/env python3
"""
YAML → JSON 转换工具
将 subagent 产出的 YAML 文件转换为标准 JSON，保证引号正确无误。

用法:
    python yaml_to_json.py <input.yaml> [--output output.json] [--keep-yaml]

默认行为：
    - 输入 example.yaml → 输出 example.json（同目录）
    - 保留原始 YAML 文件
"""

import os
import sys
import json
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


def strip_trailing_newlines(obj):
    """递归去除多行字符串末尾的换行"""
    if isinstance(obj, str):
        return obj.rstrip("\n")
    elif isinstance(obj, dict):
        return {k: strip_trailing_newlines(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [strip_trailing_newlines(item) for item in obj]
    return obj


def convert(yaml_path, json_path=None, keep_yaml=True):
    """将 YAML 文件转换为 JSON 文件"""

    if not os.path.exists(yaml_path):
        print(f"错误: 文件不存在 — {yaml_path}", file=sys.stderr)
        sys.exit(1)

    # 读取 YAML
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        print(f"警告: {yaml_path} 内容为空，生成空 JSON 数组")
        data = []

    # 清洗
    data = strip_trailing_newlines(data)

    # 确定输出路径
    if json_path is None:
        json_path = os.path.splitext(yaml_path)[0] + ".json"

    # 写出 JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 验证 JSON 可重新解析
    with open(json_path, "r", encoding="utf-8") as f:
        re_parsed = json.load(f)

    count = len(re_parsed) if isinstance(re_parsed, list) else 1
    print(f"转换完成: {yaml_path} → {json_path}（{count} 条记录）")

    if not keep_yaml:
        os.remove(yaml_path)
        print(f"  已删除原始 YAML: {yaml_path}")


def main():
    parser = argparse.ArgumentParser(description="YAML → JSON 转换工具")
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
