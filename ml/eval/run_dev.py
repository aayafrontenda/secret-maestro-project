"""Run the organizers' dataset through the backend contract, the way the backend will call it.

There is no ground truth for DEV, so this checks speed, stability and answer distributions,
not accuracy. Run from the ml/ directory:

    uv run python eval/run_dev.py ../backend/data/dev_dataset.json --out runs/dev
    uv run python eval/run_dev.py dataset.json --only p1-ru-001,p1-kz-003 --criteria my_checklist.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maestro.contract import Criterion, EvaluateRequest, evaluate  # noqa: E402
from maestro.llm import LLMOutputError, LLMUnavailable, OllamaClient, OpenAIClient  # noqa: E402


def load_records(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "data" in raw:
        raw = raw["data"]
    return raw["records"] if isinstance(raw, dict) else raw


def to_request(record: dict, criteria: list[Criterion], guidelines: list[str] | None = None) -> EvaluateRequest:
    transcript = [
        {"index": i, "timestamp": m.get("timestamp"), "speaker": m["speaker"], "text": m["text"]}
        for i, m in enumerate(record["transcript"])
    ]
    return EvaluateRequest(
        conversation_id=record["conversation_id"],
        channel=record.get("channel", "agent chat"),
        language=record.get("language", "RU"),
        transcript=transcript,
        criteria=criteria,
        guidelines=guidelines or [],
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--criteria", type=Path, default=ROOT / "data" / "default_checklist.json")
    parser.add_argument(
        "--guidelines",
        type=Path,
        default=ROOT / "data" / "default_guidelines.json",
        help="general checklist rules, as the backend sends them; 'none' sends no rules",
    )
    parser.add_argument("--only", help="comma-separated conversation IDs")
    parser.add_argument("--language", help="RU, KZ or EN")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", help="model name (default: MAESTRO_MODEL / MAESTRO_OPENAI_MODEL)")
    parser.add_argument("--backend", choices=["ollama", "openai"], default="ollama")
    parser.add_argument("--reasoning", help="OpenAI reasoning_effort, e.g. low or none")
    parser.add_argument("--think-on", help="thinking only for these criteria/probes, e.g. 04,06,07 (sets MAESTRO_THINK_ON)")
    parser.add_argument("--generic-model", help="separate model for criteria without built-in rules (OpenAI-compatible)")
    parser.add_argument("--generic-url", help="API URL for --generic-model (default: MAESTRO_OPENAI_URL)")
    parser.add_argument("--check-model", help="second model for the cascade check (OpenAI-compatible)")
    parser.add_argument("--check-url", help="API URL for --check-model (default: MAESTRO_OPENAI_URL)")
    parser.add_argument("--check-key-env", default="MAESTRO_CHECK_API_KEY", help="env var with the key for --check-model")
    parser.add_argument("--workers", type=int, default=1, help="dialogs scored in parallel (cloud backends)")
    parser.add_argument("--price-in", type=float, help="USD per 1M prompt tokens, for the cost line")
    parser.add_argument("--price-out", type=float, help="USD per 1M completion tokens, for the cost line")
    parser.add_argument("--out", type=Path, help="directory for responses.jsonl")
    parser.add_argument("--labels", type=Path, help="reference labels; only the labelled dialogs are run")
    args = parser.parse_args()

    criteria = [Criterion(**c) for c in json.loads(args.criteria.read_text(encoding="utf-8"))]
    guidelines: list[str] = []
    if str(args.guidelines).lower() != "none":
        guidelines = json.loads(args.guidelines.read_text(encoding="utf-8"))
    records = load_records(args.dataset)
    labels: dict[str, dict] = {}
    if args.labels:
        raw_labels = json.loads(args.labels.read_text(encoding="utf-8"))
        labels = {item["conversation_id"]: item["expected"] for item in raw_labels["labels"]}
        records = [r for r in records if r["conversation_id"] in labels]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        records = [r for r in records if r["conversation_id"] in wanted]
    if args.language:
        records = [r for r in records if r.get("language", "").upper() == args.language.upper()]
    if args.limit:
        records = records[: args.limit]

    if args.think_on is not None:
        import os

        os.environ["MAESTRO_THINK_ON"] = args.think_on
    if args.backend == "openai":
        llm = OpenAIClient.from_env(model=args.model, reasoning_effort=args.reasoning)
    else:
        llm = OllamaClient.from_env(model=args.model)
    generic_llm = None
    check_llm = None
    if args.check_model:
        import os

        check_llm = OpenAIClient(model=args.check_model, url=args.check_url or os.getenv("MAESTRO_OPENAI_URL", "https://api.openai.com/v1"),
                                 api_key=os.getenv(args.check_key_env) or os.getenv("OPENAI_API_KEY", ""))
    if args.generic_model:
        generic_llm = OpenAIClient.from_env(model=args.generic_model, url=args.generic_url)
    status = llm.health()
    if not status["ok"]:
        print(f"error: {status['error']}", file=sys.stderr)
        return 2

    out = None
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        out = (args.out / "responses.jsonl").open("w", encoding="utf-8")

    answers: dict[str, Counter] = defaultdict(Counter)
    methods: Counter = Counter()
    seconds: list[float] = []
    failures: list[str] = []
    comparison = Comparison()
    started = time.perf_counter()
    codes = [c.code for c in criteria]
    print(f"{len(records)} dialogs, criteria: {', '.join(codes)}\n")
    tokens = {"prompt": 0, "completion": 0, "calls": 0}

    def run_one(record: dict):
        request = to_request(record, criteria, guidelines)
        try:
            return request, evaluate(request, llm, generic_llm, check_llm), None
        except (LLMOutputError, LLMUnavailable) as exc:
            return request, None, exc

    pool = ThreadPoolExecutor(max_workers=max(1, args.workers))
    futures = [pool.submit(run_one, record) for record in records]
    # Print each dialog as soon as it is scored, so a long run shows progress.
    for n, future in enumerate(as_completed(futures), start=1):
        request, response, error = future.result()
        if error is not None:
            failures.append(f"{request.conversation_id}: {error}")
            print(f"[{n}/{len(records)}] {request.conversation_id}: FAILED {error}", flush=True)
            continue
        tokens["prompt"] += response.usage.prompt_tokens
        tokens["completion"] += response.usage.completion_tokens
        tokens["calls"] += response.usage.calls
        seconds.append(response.duration_ms / 1000)
        for result in response.results:
            answers[result.code][str(result.answer)] += 1
            methods[result.method] += 1
        compact = " ".join(f"{r.code}={r.answer}" for r in response.results)
        expected = labels.get(request.conversation_id)
        if expected:
            got = {r.code: r.answer for r in response.results}
            reviews = {r.code: r.review for r in response.results}
            comparison.add(request.conversation_id, request.language, expected, got, reviews)
            misses = [f"{c}: want {expected[c]} got {got.get(c)}" for c in expected if expected[c] != got.get(c)]
            compact = "; ".join(misses) or "all match"
        print(
            f"[{n}/{len(records)}] {request.conversation_id:14} {request.language} {len(request.transcript):>3} msgs "
            f"{response.usage.calls:>2} calls {seconds[-1]:5.1f}s  {compact}",
            flush=True,
        )
        if out:
            out.write(response.model_dump_json() + "\n")
            out.flush()
    pool.shutdown()
    if out:
        out.close()

    total = time.perf_counter() - started
    print(f"\n{len(seconds)} scored, {len(failures)} failed, {total:.0f}s total")
    if seconds:
        print(f"seconds per dialog: mean {statistics.mean(seconds):.1f}, max {max(seconds):.1f}")
    print(f"methods: {dict(methods)}")
    if seconds:
        per = len(seconds)
        print(f"tokens: prompt {tokens['prompt']}, completion {tokens['completion']}, calls {tokens['calls']} "
              f"(per dialog: {tokens['prompt'] / per:.0f} in, {tokens['completion'] / per:.0f} out, {tokens['calls'] / per:.1f} calls)")
        if args.price_in is not None and args.price_out is not None:
            cost = tokens["prompt"] / 1e6 * args.price_in + tokens["completion"] / 1e6 * args.price_out
            print(f"cost: ${cost:.4f} total, ${cost / per:.5f} per dialog")
    for code in codes:
        print(f"  {code}: {dict(sorted(answers[code].items()))}")
    for failure in failures:
        print(f"FAILED {failure}")
    if labels:
        comparison.report(args.model or llm.model)
    return 1 if failures else 0


class Comparison:
    """Agreement with reference labels: per criterion, per language and on the final score."""

    def __init__(self) -> None:
        self.hits: dict[str, list[bool]] = defaultdict(list)
        self.by_language: dict[str, list[bool]] = defaultdict(list)
        self.score_errors: list[float] = []
        self.cascade: list[tuple[bool, bool, bool]] = []  # (models agree, main right, one of the two right)

    def add(self, conversation_id: str, language: str, expected: dict, got: dict, reviews: dict | None = None) -> None:
        for code, want in expected.items():
            ok = got.get(code) == want
            self.hits[code].append(ok)
            self.by_language[language].append(ok)
            review = (reviews or {}).get(code)
            if review is not None:
                self.cascade.append((review.agrees, ok, ok or review.second_answer == want))
        want_score, got_score = final_score(expected), final_score(got)
        if want_score is not None and got_score is not None:
            self.score_errors.append(abs(want_score - got_score))

    def report(self, model: str) -> None:
        total = [ok for values in self.hits.values() for ok in values]
        if not total:
            print(f"\nno labelled dialogs were scored ({model})")
            return
        print(f"\nagreement with reference labels ({model}): {sum(total)}/{len(total)} = {sum(total) / len(total):.1%}")
        for code, values in self.hits.items():
            print(f"  {code}: {sum(values)}/{len(values)}")
        for language, values in self.by_language.items():
            print(f"  {language}: {sum(values) / len(values):.1%}")
        if self.score_errors:
            print(f"  final score mean abs error: {statistics.mean(self.score_errors):.2f}")
        if self.cascade:
            n = len(self.cascade)
            agreed = [c for c in self.cascade if c[0]]
            right_agreed = sum(c[1] for c in agreed)
            print(
                f"cascade: models agree on {len(agreed)}/{n} = {len(agreed) / n:.1%} of answers, accuracy there "
                f"{right_agreed / max(1, len(agreed)):.1%}; to a supervisor {n - len(agreed)} ({(n - len(agreed)) / n:.1%}); "
                f"with the supervisor fixing those: {(right_agreed + n - len(agreed)) / n:.1%}"
            )


def final_score(answers: dict) -> float | None:
    """Final score with the standard weights, for comparing totals. Codes c1..c8 map to 01..08."""
    from maestro.scoring import InvalidAnswer, compute

    mapped = {f"0{code[-1]}": value for code, value in answers.items() if code[-1].isdigit()}
    try:
        return compute(mapped).final_score
    except InvalidAnswer:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
