#!/usr/bin/env python3
"""
电子书知识合并工具
读取所有 JSON 提取结果，合并、去重后存储到 SQLite 数据库。

用法:
    python merge_to_sqlite.py <json_dir>

    其中 <json_dir> 是包含 JSON 文件的目录（通常是 书名_tmp 目录）。
    数据库文件将生成在 json_dir 的同级目录，文件名为 <书名>.db。

数据库结构:
    nouns 表 — 名词条目
        noun          TEXT  PRIMARY KEY — 名词（不区分大小写去重）
        explanation   TEXT             — 解释/总结
        original_text TEXT             — 书中对应原文
        source_urls   TEXT             — 网络来源 URL（多行）
        created_at    TEXT             — 创建时间
        updated_at    TEXT             — 更新时间

    metadata 表 — 处理元信息
        key   TEXT  PRIMARY KEY
        value TEXT
"""

import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime


# ============================================================
# JSON 读取与合并
# ============================================================

def read_all_json_files(json_dir):
    """读取目录下所有 JSON 文件，返回条目列表"""
    all_entries = []
    json_files = sorted(
        f for f in os.listdir(json_dir)
        if f.endswith(".json") and not f.startswith("_")
    )
    if not json_files:
        print(f"警告: 在 {json_dir} 中未找到 JSON 文件", file=sys.stderr)
        return []

    for json_file in json_files:
        filepath = os.path.join(json_dir, json_file)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                all_entries.extend(data)
                print(f"  读取 {json_file}: {len(data)} 条记录")
            else:
                print(f"  跳过 {json_file}: 不是 JSON 数组格式")
        except json.JSONDecodeError as e:
            print(f"  跳过 {json_file}: JSON 解析错误 — {e}")
        except Exception as e:
            print(f"  跳过 {json_file}: {e}")

    return all_entries


def normalize_keys(entry):
    """
    兼容中英文键名，统一为中文键。
    输入键名可以是: 名词/noun, 解释/explanation, 书中原文/original_text, 网络来源/source_urls
    """
    key_map = {
        "noun": "名词", "explanation": "解释",
        "original_text": "书中原文", "source_urls": "网络来源",
    }
    normalized = {}
    for k, v in entry.items():
        k2 = key_map.get(k, k)
        normalized[k2] = v
    return normalized


def deduplicate_entries(entries):
    """
    按名词去重（不区分大小写）。
    同名词合并：解释拼接、URL 去重合并、原文拼接。
    """
    deduped = {}

    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        entry = normalize_keys(raw_entry)

        noun = entry.get("名词", "").strip()
        if not noun:
            continue

        key = noun.lower()

        if key in deduped:
            existing = deduped[key]

            # 合并解释
            new_expl = entry.get("解释", "").strip()
            old_expl = existing.get("解释", "").strip()
            if new_expl and new_expl != old_expl:
                existing["解释"] = f"{old_expl}\n---\n{new_expl}" if old_expl else new_expl

            # 合并原文
            new_text = entry.get("书中原文", "").strip()
            old_text = existing.get("书中原文", "").strip()
            if new_text and new_text not in old_text:
                existing["书中原文"] = f"{old_text}\n---\n{new_text}" if old_text else new_text

            # 合并 URL（去重）
            new_urls_str = entry.get("网络来源", "").strip()
            old_urls_str = existing.get("网络来源", "").strip()
            if new_urls_str:
                all_urls = set()
                for u in (old_urls_str + "\n" + new_urls_str).split("\n"):
                    u = u.strip()
                    if u:
                        all_urls.add(u)
                existing["网络来源"] = "\n".join(sorted(all_urls))
        else:
            deduped[key] = {
                "名词": noun,
                "解释": entry.get("解释", ""),
                "书中原文": entry.get("书中原文", ""),
                "网络来源": entry.get("网络来源", ""),
            }

    return list(deduped.values())


# ============================================================
# SQLite 存储
# ============================================================

def get_db_connection(db_path):
    """获取数据库连接并启用 WAL 模式"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA encoding='UTF-8'")
    return conn


def init_schema(conn):
    """初始化数据库表结构"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nouns (
            noun          TEXT PRIMARY KEY COLLATE NOCASE,
            explanation   TEXT NOT NULL DEFAULT '',
            original_text TEXT NOT NULL DEFAULT '',
            source_urls   TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS metadata (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_nouns_explanation
            ON nouns(explanation);
    """)


def store_entries(conn, entries, book_name):
    """将去重后的条目写入数据库（UPSERT）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()

    inserted = 0
    updated = 0

    for entry in entries:
        cursor.execute("""
            INSERT INTO nouns (noun, explanation, original_text, source_urls,
                               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(noun) DO UPDATE SET
                explanation   = excluded.explanation,
                original_text = excluded.original_text,
                source_urls   = excluded.source_urls,
                updated_at    = excluded.updated_at
        """, (
            entry["名词"],
            entry.get("解释", ""),
            entry.get("书中原文", ""),
            entry.get("网络来源", ""),
            now, now
        ))
        if cursor.rowcount == 1:
            inserted += 1
        else:
            updated += 1

    conn.commit()
    return inserted, updated


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="电子书知识合并工具")
    parser.add_argument("json_dir", help="包含 JSON 文件的目录路径（通常是 书名_tmp 目录）")
    parser.add_argument("--db", help="输出数据库路径（默认: 自动生成在 json_dir 同级）")
    args = parser.parse_args()

    json_dir = os.path.abspath(args.json_dir)
    if not os.path.isdir(json_dir):
        print(f"错误: 目录不存在 — {json_dir}", file=sys.stderr)
        sys.exit(1)

    # 从目录名推断书名
    dir_name = os.path.basename(json_dir)
    book_name = dir_name[:-4] if dir_name.endswith("_tmp") else dir_name

    # 确定数据库路径
    if args.db:
        db_path = os.path.abspath(args.db)
    else:
        db_path = os.path.join(os.path.dirname(json_dir), f"{book_name}.db")

    print(f"书籍: {book_name}")
    print(f"目标数据库: {db_path}")
    print()

    # 1. 读取 JSON
    print("[1/4] 读取 JSON 文件...")
    all_entries = read_all_json_files(json_dir)
    print(f"      共 {len(all_entries)} 条原始记录")
    print()

    # 2. 去重
    print("[2/4] 去重合并...")
    deduped = deduplicate_entries(all_entries)
    print(f"      去重后 {len(deduped)} 条记录（合并了 {len(all_entries) - len(deduped)} 条重复）")
    print()

    # 3. 写入数据库
    print("[3/4] 写入 SQLite...")
    conn = get_db_connection(db_path)
    init_schema(conn)
    inserted, updated = store_entries(conn, deduped, book_name)

    # 写入元信息
    conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ("book_name", book_name)
    )
    conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ("total_entries", str(len(deduped)))
    )
    conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM nouns").fetchone()[0]
    print(f"      新增 {inserted}，更新 {updated}，数据库总计 {total} 条")
    print()

    # 4. 验证
    print("[4/4] 验证数据库...")
    sample = conn.execute(
        "SELECT noun, length(explanation), length(source_urls) FROM nouns LIMIT 5"
    ).fetchall()
    for row in sample:
        print(f"      ✓ {row[0]} (解释 {row[1]} 字符, 来源 {row[2]} 字符)")
    conn.close()
    print()

    print(f"{'='*60}")
    print(f"完成! 数据库已保存到: {db_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
