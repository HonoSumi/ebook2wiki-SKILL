#!/usr/bin/env python3
"""
Checkpoint detection: determine the current state of extraction.

Usage:
    python detect_checkpoint.py <tmp_dir>

Prints one-line result with exit code:

    FRESH                  → no chunks or plan found, need to start fresh
    INCOMPLETE:N/M:next    → N/M chunks done, resume from chunk 'next'
    COMPLETE:M             → all M chunks done, ready to merge

Exit codes:
    0 — FRESH or COMPLETE (no further chunk processing needed)
    1 — INCOMPLETE (resume processing)
"""

import sys
import os
import json
import glob

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        print("Usage: python detect_checkpoint.py <tmp_dir>", file=sys.stderr)
        sys.exit(0)

    tmp_dir = sys.argv[1]

    # Check for chunk files (any .txt that isn't already_searched or filtered/keywords)
    plan_path = os.path.join(tmp_dir, "_plan.json")
    txt_files = glob.glob(os.path.join(tmp_dir, "*_*.txt"))
    txt_files = [f for f in txt_files
                 if not os.path.basename(f).startswith(("already_", "keywords_", "filtered_"))]

    if not txt_files or not os.path.exists(plan_path):
        print("FRESH")
        sys.exit(0)

    # Read plan
    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    total = plan.get("total_chunks", 0)
    chunks = plan.get("chunks", [])

    statuses = {}
    for c in chunks:
        s = c.get("status", "pending")
        statuses[s] = statuses.get(s, 0) + 1

    completed = statuses.get("completed", 0) + statuses.get("failed", 0)

    if completed >= total:
        print(f"COMPLETE:{total}")
        sys.exit(0)

    # Find first pending chunk (sorted by seq for determinism)
    next_seq = None
    for c in sorted(chunks, key=lambda x: x.get("seq", 0)):
        if c.get("status", "pending") == "pending":
            next_seq = c.get("seq")
            break

    if next_seq is None:
        # All chunks accounted for but no pending found — should not happen, be defensive
        next_seq = 1

    print(f"INCOMPLETE:{completed}:{total}:{next_seq}")
    sys.exit(1)


if __name__ == "__main__":
    main()
