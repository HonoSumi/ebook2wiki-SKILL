#!/usr/bin/env python3
"""
电子书分段工具
将各种格式的电子书（PDF/EPUB/MOBI/TXT/MD）分割为互相重叠的小文本块。

用法:
    python chunk_ebook.py <电子书路径> [--chunk-size 10000] [--overlap 100]

输出:
    在 <书名>_tmp/ 目录下生成 <书名>_1.txt, <书名>_2.txt, ...（无前导零）
"""

import os
import sys
import re
import json
import argparse
import subprocess
import tempfile
import shutil


# ============================================================
# 依赖管理
# ============================================================

def ensure_dependencies():
    """自动安装所需 Python 依赖"""
    required = {}
    try:
        import pdfplumber
    except ImportError:
        required["pdfplumber"] = "pdfplumber"

    try:
        import ebooklib
    except ImportError:
        required["EbookLib"] = "EbookLib"

    try:
        import bs4
    except ImportError:
        required["beautifulsoup4"] = "beautifulsoup4"

    if required:
        print(f"正在安装依赖: {', '.join(required.keys())}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install"] + list(required.values()),
            stdout=subprocess.DEVNULL
        )
        print("依赖安装完成")


ensure_dependencies()

import pdfplumber
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup


# ============================================================
# 格式解析器
# ============================================================

def extract_text_from_pdf(path):
    """从 PDF 提取文本"""
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def extract_text_from_epub(path):
    """从 EPUB 提取文本"""
    book = epub.read_epub(path)
    text_parts = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            content = item.get_body_content()
            if content:
                soup = BeautifulSoup(content, "html.parser")
                text_parts.append(soup.get_text())
    return "\n".join(text_parts)


def extract_text_from_mobi(path):
    """从 MOBI 提取文本 — 优先尝试 calibre，回退 mobi 包"""
    # 尝试 calibre 的 ebook-convert
    fd, tmp_path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        result = subprocess.run(
            ["ebook-convert", path, tmp_path],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            text = read_text_file(tmp_path)
            os.unlink(tmp_path)
            return text
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 尝试 mobi Python 包
    try:
        from mobi import extract
        temp_dir, file_path = extract(path)
        text = read_text_file(file_path)
        shutil.rmtree(temp_dir, ignore_errors=True)
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return text
    except ImportError:
        pass

    if os.path.exists(tmp_path):
        os.unlink(tmp_path)

    raise RuntimeError(
        "无法解析 MOBI 文件。请安装 calibre (https://calibre-ebook.com) "
        "后重试，或先将 MOBI 转换为 EPUB/TXT 格式。"
    )


def read_text_file(path):
    """读取文本文件，自动检测编码"""
    encodings = ["utf-8", "gbk", "gb2312", "utf-16", "latin-1"]
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文件: {path}")


def extract_text(path):
    """根据文件扩展名选择解析器提取文本"""
    ext = os.path.splitext(path)[1].lower()
    parsers = {
        ".pdf": extract_text_from_pdf,
        ".epub": extract_text_from_epub,
        ".mobi": extract_text_from_mobi,
        ".txt":  lambda p: read_text_file(p),
        ".md":   lambda p: read_text_file(p),
        ".markdown": lambda p: read_text_file(p),
    }
    parser = parsers.get(ext)
    if not parser:
        raise ValueError(f"不支持的文件格式: {ext}（支持: {', '.join(parsers.keys())}）")
    return parser(path)


# ============================================================
# 文本清洗与分割
# ============================================================

def clean_text(text):
    """清洗文本：去除多余空行和空格，保留段落结构"""
    text = re.sub(r"\n{4,}", "\n\n\n", text)          # 过多空行压缩
    text = re.sub(r"[ \t]{3,}", "  ", text)           # 过多空格压缩
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)  # 行首空白（不含换行）
    text = re.sub(r"(\S)\n(\S)", r"\1\2", text)       # 行中断续（英文换行）
    return text.strip()


def chunk_text(text, chunk_size=5000, overlap=100):
    """
    将文本分割为重叠块。

    策略：
    - 尽量在段落边界（\n\n）处分隔
    - 其次在句子边界（句号/感叹号/问号）处分隔
    - 保证相邻块之间至少有 overlap 字符的重叠
    """
    if not text:
        return []

    chunks = []
    start = 0
    step = chunk_size - overlap
    seq = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        # 非末尾块：尝试在边界处断句
        if end < len(text):
            search_start = start + chunk_size // 2
            # 优先段落边界
            para_break = text.rfind("\n\n", search_start, end)
            if para_break > start:
                end = para_break + 2
            else:
                # 句子边界（中文标点）
                for sep in ["。", "！", "？", "；", "\n"]:
                    pos = text.rfind(sep, search_start, end)
                    if pos > start:
                        end = pos + len(sep)
                        break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start += step
        seq += 1

    return chunks


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="电子书分段工具")
    parser.add_argument("ebook", help="电子书文件路径")
    parser.add_argument("--chunk-size", type=int, default=5000,
                        help="每块目标字符数（默认: 5000）")
    parser.add_argument("--overlap", type=int, default=100,
                        help="块间重叠字符数（默认: 100）")
    args = parser.parse_args()

    ebook_path = os.path.abspath(args.ebook)
    if not os.path.exists(ebook_path):
        print(f"错误: 文件不存在 — {ebook_path}", file=sys.stderr)
        sys.exit(1)

    # 从文件名获取书名
    base_name = os.path.splitext(os.path.basename(ebook_path))[0]
    base_name = re.sub(r'[\\/:*?"<>|]', "_", base_name)  # 去除非法字符

    output_dir = os.path.join(os.path.dirname(ebook_path), f"{base_name}_tmp")
    os.makedirs(output_dir, exist_ok=True)

    print(f"[1/4] 正在提取文本: {ebook_path}")
    text = extract_text(ebook_path)
    text = clean_text(text)
    print(f"      提取完成: {len(text):,} 字符")

    print(f"[2/4] 正在分割文本（每块 ~{args.chunk_size} 字符，重叠 {args.overlap} 字符）")
    chunks = chunk_text(text, args.chunk_size, args.overlap)
    print(f"      共分割为 {len(chunks)} 个文本块")

    print(f"[3/4] 正在写出文本块")
    for i, chunk in enumerate(chunks, 1):
        filename = f"{base_name}_{i}.txt"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(chunk)
        print(f"      [{i:3d}/{len(chunks)}] {filename} ({len(chunk):,} 字符)")

    # 写出处理计划 JSON
    plan = {
        "book_name": base_name,
        "source_file": ebook_path,
        "total_chunks": len(chunks),
        "chunk_size": args.chunk_size,
        "overlap": args.overlap,
        "chunks": [
            {
                "seq": i,
                "filename": f"{base_name}_{i}.txt",
                "char_count": len(chunks[i - 1]),
                "status": "pending"
            }
            for i in range(1, len(chunks) + 1)
        ]
    }
    plan_path = os.path.join(output_dir, "_plan.json")
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    print(f"[4/4] 写入处理计划: _plan.json")
    print(f"\n{'='*60}")
    print(f"完成! 所有文本块已保存到: {output_dir}")
    print(f"计划列表: 共 {len(chunks)} 个文本块待处理")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
