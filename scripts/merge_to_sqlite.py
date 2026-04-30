#!/usr/bin/env python3
"""
电子书知识合并工具
读取所有 JSON 提取结果，合并、去重后存储到 SQLite 数据库。

用法:
    python merge_to_sqlite.py <json_dir>

数据库结构:
    nouns 表 — 知识条目
        noun          TEXT  PRIMARY KEY — 名词（不区分大小写去重）
        category      TEXT             — 分类
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

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 唯一允许的字段名
ALLOWED_FIELDS = {"名词", "分类", "解释", "书中原文", "网络来源"}
ALLOWED_FIELDS_LIST = ["名词", "分类", "解释", "书中原文", "网络来源"]
ALLOWED_CATEGORIES = {"人物", "地点", "物件", "事件", "概念", "习俗"}


def read_all_json_files(json_dir):
    """读取目录下所有 JSON 文件，返回 (条目列表, 警告列表, 分类违规列表)"""
    all_entries = []
    warnings = []
    category_violations = []  # [(json_file, index, noun, bad_category)]

    json_files = sorted(
        f for f in os.listdir(json_dir)
        if f.endswith(".json") and not f.startswith("_")
    )
    if not json_files:
        print(f"警告: 在 {json_dir} 中未找到 JSON 文件", file=sys.stderr)
        return [], [], []

    for json_file in json_files:
        filepath = os.path.join(json_dir, json_file)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                if not data:
                    print(f"  读取 {json_file}: 0 条记录")
                    continue

                # 检查每条记录的字段名
                file_ok = True
                file_entries = []
                for i, entry in enumerate(data):
                    if not isinstance(entry, dict):
                        warnings.append(f"  {json_file}[{i}]: 不是字典类型，跳过")
                        file_ok = False
                        continue

                    keys = set(entry.keys())
                    extra = keys - ALLOWED_FIELDS
                    missing = ALLOWED_FIELDS - keys
                    if extra:
                        warnings.append(
                            f"  {json_file}[{i}]: 包含不认识的字段 {sorted(extra)}"
                            f"（允许: {ALLOWED_FIELDS_LIST}）"
                        )
                        file_ok = False
                    if missing:
                        warnings.append(
                            f"  {json_file}[{i}]: 缺少字段 {sorted(missing)}"
                        )
                        file_ok = False

                    if file_ok:
                        file_entries.append(entry)

                if file_ok:
                    # 检查分类是否合规
                    for i, entry in enumerate(data):
                        cat_val = entry.get("分类", "").strip()
                        if cat_val not in ALLOWED_CATEGORIES:
                            noun = entry.get("名词", "?").strip()
                            category_violations.append((json_file, i, noun, cat_val))

                    all_entries.extend(file_entries)
                    print(f"  读取 {json_file}: {len(data)} 条记录")
                else:
                    print(f"  读取 {json_file}: {len(data)} 条记录（字段异常，跳过）")

            elif isinstance(data, dict):
                warnings.append(
                    f"  {json_file}: 顶层是对象 (dict) 而非数组，跳过。"
                    f"请确保 JSON 以 [ 开头。"
                )
                print(f"  读取 {json_file}: 对象格式（跳过）")
            else:
                warnings.append(f"  {json_file}: 不是 JSON 数组格式")
                print(f"  读取 {json_file}: 非数组格式（跳过）")

        except json.JSONDecodeError as e:
            warnings.append(f"  {json_file}: JSON 解析错误 — {e}")
            print(f"  读取 {json_file}: JSON 解析错误（跳过）")
        except Exception as e:
            warnings.append(f"  {json_file}: {e}")
            print(f"  读取 {json_file}: {e}（跳过）")

    return all_entries, warnings, category_violations


def _val_to_str(v):
    """将值安全转为字符串（列表转换行分隔字符串）"""
    if v is None:
        return ""
    if isinstance(v, list):
        return "\n".join(str(item) for item in v if item is not None)
    if isinstance(v, str):
        return v
    return str(v)


def deduplicate_entries(entries):
    """
    按名词去重（不区分大小写）。
    同名词合并：解释拼接、URL 去重合并、原文拼接。
    """
    deduped = {}

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        noun = _val_to_str(entry.get("名词")).strip()
        if not noun:
            continue

        key = noun.lower()

        if key in deduped:
            existing = deduped[key]

            new_expl = _val_to_str(entry.get("解释")).strip()
            old_expl = existing.get("解释", "").strip()
            if new_expl and new_expl != old_expl:
                existing["解释"] = f"{old_expl}\n---\n{new_expl}" if old_expl else new_expl

            new_text = _val_to_str(entry.get("书中原文")).strip()
            old_text = existing.get("书中原文", "").strip()
            if new_text and new_text not in old_text:
                existing["书中原文"] = f"{old_text}\n---\n{new_text}" if old_text else new_text

            new_urls_str = _val_to_str(entry.get("网络来源")).strip()
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
                "分类": _val_to_str(entry.get("分类")),
                "解释": _val_to_str(entry.get("解释")),
                "书中原文": _val_to_str(entry.get("书中原文")),
                "网络来源": _val_to_str(entry.get("网络来源")),
            }

    return list(deduped.values())


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
            category      TEXT NOT NULL DEFAULT '',
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

        CREATE INDEX IF NOT EXISTS idx_nouns_category
            ON nouns(category);

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
            INSERT INTO nouns (noun, category, explanation, original_text, source_urls,
                               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(noun) DO UPDATE SET
                category      = excluded.category,
                explanation   = excluded.explanation,
                original_text = excluded.original_text,
                source_urls   = excluded.source_urls,
                updated_at    = excluded.updated_at
        """, (
            entry["名词"],
            entry.get("分类", ""),
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


def quality_report(conn):
    """生成数据质量报告"""
    cur = conn.cursor()

    total = cur.execute("SELECT COUNT(*) FROM nouns").fetchone()[0]

    empty_expl = cur.execute(
        "SELECT COUNT(*) FROM nouns WHERE explanation IS NULL OR explanation = ''"
    ).fetchone()[0]

    empty_orig = cur.execute(
        "SELECT COUNT(*) FROM nouns WHERE original_text IS NULL OR original_text = ''"
    ).fetchone()[0]

    empty_url = cur.execute(
        "SELECT COUNT(*) FROM nouns WHERE source_urls IS NULL OR source_urls = ''"
    ).fetchone()[0]

    complete = cur.execute(
        "SELECT COUNT(*) FROM nouns WHERE "
        "explanation != '' AND original_text != '' AND source_urls != ''"
    ).fetchone()[0]

    print()
    print(f"{'='*60}")
    print(f"  数据质量报告")
    print(f"{'='*60}")
    print(f"  总条目:          {total:>4d}")
    print(f"  完整条目:         {complete:>4d}  ({complete*100//max(total,1)}%)")
    print(f"  缺解释:           {empty_expl:>4d}")
    print(f"  缺书中原文:       {empty_orig:>4d}")
    print(f"  缺网络来源:       {empty_url:>4d}")

    if empty_expl > 0 or empty_orig > 0 or empty_url > 0:
        print()
        print(f"  ⚠ 不完整条目示例:")
        incomplete = cur.execute(
            "SELECT noun, "
            "CASE WHEN explanation='' THEN 1 ELSE 0 END + "
            "CASE WHEN original_text='' THEN 1 ELSE 0 END + "
            "CASE WHEN source_urls='' THEN 1 ELSE 0 END as missing_count "
            "FROM nouns WHERE explanation='' OR original_text='' OR source_urls='' "
            "ORDER BY missing_count DESC LIMIT 5"
        ).fetchall()
        for row in incomplete:
            noun, mc = row
            print(f"     - {noun}（缺 {mc} 个字段）")

    print(f"{'='*60}")
    return total


def main():
    parser = argparse.ArgumentParser(description="电子书知识合并工具")
    parser.add_argument("json_dir", help="包含 JSON 文件的目录路径（通常是 书名_tmp 目录）")
    parser.add_argument("--db", help="输出数据库路径（默认: 自动生成在 json_dir 同级）")
    args = parser.parse_args()

    json_dir = os.path.abspath(args.json_dir)
    if not os.path.isdir(json_dir):
        print(f"错误: 目录不存在 — {json_dir}", file=sys.stderr)
        sys.exit(1)

    dir_name = os.path.basename(json_dir)
    book_name = dir_name[:-4] if dir_name.endswith("_tmp") else dir_name

    if args.db:
        db_path = os.path.abspath(args.db)
    else:
        db_path = os.path.join(os.path.dirname(json_dir), f"{book_name}.db")

    print(f"书籍: {book_name}")
    print(f"目标数据库: {db_path}")
    print()

    # 1. 读取 JSON
    print("[1/4] 读取 JSON 文件...")
    all_entries, file_warnings, cat_violations = read_all_json_files(json_dir)
    if file_warnings:
        print(f"\n  字段警告（{len(file_warnings)} 条）:")
        for w in file_warnings:
            print(f"  {w}")
        print()

    # 分类校验 — 一次性报告所有不合规条目
    if cat_violations:
        by_file = {}
        for json_file, idx, noun, bad_cat in cat_violations:
            by_file.setdefault(json_file, []).append((idx, noun, bad_cat))

        print(f"\n  分类校验失败 — 以下 {len(cat_violations)} 条记录的分类不在允许列表中（{sorted(ALLOWED_CATEGORIES)}）：")
        for json_file in sorted(by_file):
            print(f"    文件: {json_file}")
            for idx, noun, bad_cat in by_file[json_file]:
                print(f"      [{idx}] 名词「{noun}」分类为「{bad_cat}」")
        print(f"\n  请修正对应 JSON 文件中的分类字段后重试。")
        sys.exit(1)

    print(f"      共 {len(all_entries)} 条有效记录")
    print()

    # 2. 去重
    print("[2/4] 去重合并...")
    deduped = deduplicate_entries(all_entries)
    duplicates = len(all_entries) - len(deduped)
    print(f"      去重后 {len(deduped)} 条记录（合并了 {duplicates} 条重复）")
    print()

    # 3. 写入数据库
    print("[3/4] 写入 SQLite...")
    conn = get_db_connection(db_path)
    init_schema(conn)
    inserted, updated = store_entries(conn, deduped, book_name)

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

    # 4. 质量报告
    print("[4/4] 数据质量报告...")
    quality_report(conn)
    conn.close()
    print()
    print(f"完成! 数据库已保存到: {db_path}")


if __name__ == "__main__":
    main()
