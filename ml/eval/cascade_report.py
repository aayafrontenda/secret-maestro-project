"""Cascade report from two saved runs: how often two models agree and how accurate they are then.

Both runs must cover the same dialogs (responses.jsonl written by run_dev.py --out). Every criterion
the models disagree on goes to a supervisor; the report assumes the supervisor fixes it.

    python eval/cascade_report.py runs/gemini runs/gpt --labels data/reference/dev_reference.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load(run: Path) -> dict[str, dict[str, object]]:
    rows = {}
    for line in (run / "responses.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            rows[item["conversation_id"]] = {r["code"]: r["answer"] for r in item["results"]}
    return rows


def summary(rows: list[tuple[object, object, object]]) -> str:
    n = len(rows)
    agreed = [r for r in rows if r[0] == r[1]]
    right = sum(r[0] == r[2] for r in agreed)
    main_acc = sum(r[0] == r[2] for r in rows) / n
    return (
        f"n={n:3}  main alone {main_acc:.1%} | agree on {len(agreed) / n:.1%} -> accuracy {right / max(1, len(agreed)):.1%}"
        f" | to a supervisor {(n - len(agreed)) / n:.1%} | with the supervisor {(right + n - len(agreed)) / n:.1%}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("main", type=Path, help="run directory of the main model")
    parser.add_argument("check", type=Path, help="run directory of the check model")
    parser.add_argument("--labels", type=Path, action="append", required=True, help="reference labels (repeatable)")
    args = parser.parse_args()

    labels: dict[str, dict] = {}
    for path in args.labels:
        for item in json.loads(path.read_text(encoding="utf-8"))["labels"]:
            labels[item["conversation_id"]] = item["expected"]
    a, b = load(args.main), load(args.check)
    rows, by_code, flagged = [], defaultdict(list), defaultdict(int)
    for cid, expected in labels.items():
        if cid not in a or cid not in b:
            continue
        for code, want in expected.items():
            row = (a[cid].get(code), b[cid].get(code), want)
            rows.append(row)
            by_code[code].append(row)
            flagged[cid] += row[0] != row[1]
    if not rows:
        print("no dialogs in common with the labels")
        return 1
    print("all     ", summary(rows))
    for code in sorted(by_code):
        print(f"  {code:6}", summary(by_code[code]))
    automatic = sum(1 for n in flagged.values() if n == 0)
    print(f"dialogs fully automatic: {automatic}/{len(flagged)} ({automatic / len(flagged):.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
