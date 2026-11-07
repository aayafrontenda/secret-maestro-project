"""Compare system scores with expected labels, for one or more models.

Labels live next to the chats: each chat object has an "expected" map such as
{"01": "yes", "04": 15, ...}. Run from the ml/ directory:

    uv run python eval/evaluate.py data/synthetic/chats.json --models qwen3.5:9b,qwen3.5:4b

Synthetic chats only show that the pipeline works. Their labels were written by us, so
the numbers are not an accuracy estimate for real chats.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maestro.checklist import BY_ID, CRITERIA, WEIGHTED  # noqa: E402
from maestro.ingest import parse_json_object  # noqa: E402
from maestro.llm import OllamaClient  # noqa: E402
from maestro.pipeline import score_transcript  # noqa: E402
from maestro.scoring import compute  # noqa: E402


def _normalize(value):
    if isinstance(value, str):
        lowered = value.strip().lower()
        aliases = {"да": "yes", "нет": "no", "n/a": "na", "иә": "yes", "жоқ": "no"}
        lowered = aliases.get(lowered, lowered)
        return int(lowered) if lowered.isdigit() else lowered
    return value


def evaluate(path: Path, model: str, think: bool, out_dir: Path | None) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    chats = raw if isinstance(raw, list) else [raw]
    client = OllamaClient.from_env(model=model, think=think)
    status = client.health()
    if not status["ok"]:
        raise SystemExit(f"{model}: {status['error']}")

    hits: dict[str, list[bool]] = defaultdict(list)
    scale_errors: dict[str, list[int]] = defaultdict(list)
    score_errors: list[float] = []
    by_language: dict[str, list[float]] = defaultdict(list)
    rows = []
    started = time.perf_counter()
    for chat in chats:
        expected = {k: _normalize(v) for k, v in chat["expected"].items()}
        transcript = parse_json_object(chat)[0]
        result = score_transcript(transcript, client)
        got = {c.criterion_id: c.answer for c in result.criteria}
        expected_score = compute({c.id: expected[c.id] for c in WEIGHTED}).final_score
        for criterion in CRITERIA:
            want, have = expected.get(criterion.id), got.get(criterion.id)
            if want is None:
                continue
            hits[criterion.id].append(want == have)
            if criterion.is_scale and isinstance(want, int) and isinstance(have, int):
                scale_errors[criterion.id].append(abs(want - have))
        if result.final_score is not None:
            error = abs(result.final_score - expected_score)
            score_errors.append(error)
            by_language[chat.get("language", "unknown")].append(error)
        misses = [f"{cid}: want {expected[cid]} got {got.get(cid)}" for cid in expected if expected[cid] != got.get(cid)]
        rows.append((transcript.chat_id, expected_score, result.final_score, result.llm_calls, misses))
        print(
            f"[{len(rows)}/{len(chats)}] {transcript.chat_id:42} expected {expected_score!s:>6}  "
            f"got {result.final_score!s:>6}  calls {result.llm_calls:>2}  {result.duration_ms / 1000:5.1f}s  "
            f"{'; '.join(misses) or 'all match'}",
            flush=True,
        )
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{transcript.chat_id}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")

    elapsed = time.perf_counter() - started
    print(f"\n=== {model} (think={think}) on {path.name}: {len(chats)} chats, {elapsed:.0f}s ===")
    print("per criterion: exact match / mean abs error for scales")
    for criterion in CRITERIA:
        values = hits[criterion.id]
        if not values:
            continue
        line = f"  {criterion.id} {BY_ID[criterion.id].name:45} {sum(values)}/{len(values)}"
        if scale_errors[criterion.id]:
            line += f"   MAE {statistics.mean(scale_errors[criterion.id]):.2f}"
        print(line)
    summary = {
        "model": model,
        "think": think,
        "chats": len(chats),
        "seconds": round(elapsed, 1),
        "criterion_accuracy": round(sum(sum(v) for v in hits.values()) / max(sum(len(v) for v in hits.values()), 1), 3),
        "final_score_mae": round(statistics.mean(score_errors), 2) if score_errors else None,
        "final_score_mae_by_language": {k: round(statistics.mean(v), 2) for k, v in by_language.items()},
    }
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--models", default="qwen3.5:9b", help="comma-separated Ollama models")
    parser.add_argument("--think", choices=["off", "on", "both"], default="off")
    parser.add_argument("--out", type=Path, help="directory for per-chat results")
    args = parser.parse_args()

    modes = {"off": [False], "on": [True], "both": [False, True]}[args.think]
    summaries = []
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        for think in modes:
            out = args.out / f"{model.replace(':', '_')}-think{int(think)}" if args.out else None
            summaries.append(evaluate(args.labels, model, think, out))
    if len(summaries) > 1:
        print("\n=== comparison ===")
        for s in summaries:
            print(f"{s['model']:24} think={s['think']!s:5} accuracy={s['criterion_accuracy']} "
                  f"score MAE={s['final_score_mae']} time={s['seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
