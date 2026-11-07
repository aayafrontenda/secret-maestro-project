"""Command line: score chat files or check the model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ingest import IngestError, parse_file
from .llm import LLMUnavailable, OllamaClient
from .schemas import ScoreResult


def _summary(result: ScoreResult, verbose: bool) -> str:
    gross = result.gross_violation.flag if result.gross_violation else None
    lines = [
        f"{result.chat_id}: score={result.final_score} status={result.status} gross={gross} "
        f"calls={result.llm_calls} {result.duration_ms / 1000:.1f}s"
    ]
    if verbose:
        lines += [f"  {c.criterion_id} {c.answer!s:>4} {c.points!s:>6}  {c.rationale}" for c in result.criteria]
    return "\n".join(lines)


def _score(args: argparse.Namespace) -> int:
    from .pipeline import score_transcript

    client = OllamaClient.from_env(model=args.model, think=args.think or None)
    status = client.health()
    if not status["ok"]:
        print(f"error: {status['error']}", file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    for path in args.files:
        try:
            transcripts = parse_file(path)
        except IngestError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            return 1
        for transcript in transcripts:
            try:
                result = score_transcript(transcript, client, args.lang)
            except LLMUnavailable as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            if args.json:
                # One JSON object per line, for callers that are not written in Python.
                print(result.model_dump_json(), flush=True)
            else:
                print(_summary(result, args.verbose), flush=True)
            if out_dir:
                (out_dir / f"{result.chat_id}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return 0


def _health(_: argparse.Namespace) -> int:
    status = OllamaClient.from_env().health()
    print(json.dumps(status, ensure_ascii=False))
    return 0 if status["ok"] else 2


def _schema(_: argparse.Namespace) -> int:
    print(json.dumps(ScoreResult.model_json_schema(), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="maestro", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    score = commands.add_parser("score", help="score chat files (.json, .csv, .xlsx, .txt)")
    score.add_argument("files", nargs="+")
    score.add_argument("--out", help="directory for one JSON result per chat")
    score.add_argument("--json", action="store_true", help="print one JSON result per line instead of a summary")
    score.add_argument("--lang", choices=["ru", "kk", "en"], default="ru", help="language of the rationale")
    score.add_argument("--model", help="Ollama model (default: MAESTRO_MODEL)")
    score.add_argument("--think", action="store_true", help="enable the model's thinking mode")
    score.add_argument("-v", "--verbose", action="store_true", help="print every criterion")
    score.set_defaults(handler=_score)

    commands.add_parser("health", help="check that Ollama and the model are available").set_defaults(handler=_health)
    commands.add_parser("schema", help="print the JSON schema of a result").set_defaults(handler=_schema)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
