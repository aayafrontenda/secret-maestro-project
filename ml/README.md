# ML: chat quality scoring

Scores a customer support chat against the 8-criterion Freedom Broker checklist and returns, per criterion, the answer, points, a short rationale and the chat messages that support it, plus the final score out of 100 and a gross violation flag. Chats can be in Russian, Kazakh or English. Rationale text is available in all three.

Everything runs locally through [Ollama](https://ollama.com). No cloud APIs are used.

## How it works

1. **Ingest** (`maestro/ingest.py`): a JSON, CSV, XLSX or plain text chat becomes a list of messages `M1…Mn` with a role (client, operator, system, bot). Tags and attachments are dropped because the checklist does not score them.
2. **Facts** (`maestro/facts.py`): code finds the first and last operator messages, each side's language and long pauses.
3. **Probes** (`maestro/probes.py`): the model answers narrow yes/no questions, one per call, such as "does the operator's first message contain a greeting?". Each question sees only the messages that can answer it. The model states its reasoning first, then the answer, then the ID of the message it relied on.
4. **Rules** (`maestro/rules.py`): code turns probe answers into the checklist verdict. Probes are asked only when needed: if a criterion is N/A, the rest of its probes are skipped. Unambiguous phrases such as "Здравствуйте" or "Сау болыңыз" settle a probe without the model.
5. **Scoring** (`maestro/scoring.py`): the final score follows page 2 of the checklist exactly, including N/A redistribution and rounding to two decimals. No LLM is involved.

Evidence text is always copied from the transcript by code, so a quote cannot be invented. Every model call is recorded in the result (`attempts`): prompt hash, raw answer, tokens and time.

## Setup

Needs Python 3.12, [uv](https://docs.astral.sh/uv/) and Ollama.

```sh
ollama pull qwen3.5:4b
cd ml
uv sync
uv run maestro health
```

Settings are environment variables; see `.env.example`.

## Use

```sh
uv run maestro score data/synthetic/chats.json -v           # summary per chat
uv run maestro score chat.json --lang kk --out results/     # one JSON file per chat
uv run maestro score chat.json --json                       # one JSON result per line on stdout
uv run maestro schema                                       # JSON schema of a result
```

For the backend integration, see [docs/ML_API.md](docs/ML_API.md).

## Tests and evaluation

```sh
uv run pytest
uv run python eval/evaluate.py data/synthetic/chats.json --models qwen3.5:4b --out runs/synthetic
```

`eval/evaluate.py` compares results with the `expected` labels stored with each chat and prints exact match per criterion, scale errors and the final score error by language. It accepts several models and `--think both` to compare thinking mode.

The 12 chats in `data/synthetic/` were written by the team to exercise every N/A case and every gross violation type. Their labels are ours, so results on them show the pipeline works; they are not an accuracy estimate. Real chats go in `data/real/`, which is not committed.

## Known gaps

- Accuracy on real chats is unknown until labelled data arrives.
- Criterion 04 cannot check facts about Freedom Broker tariffs or procedures: there is no reference material. It only catches answers that are missing, partial or self-contradictory.
- Criterion 07 wording allows two readings. The rule used is "(summary or offer of further help) and goodbye". Check it against ground truth.
- Criterion 08 counts disclosing this client's account data before identification as confidential disclosure. Check this too.
- Kazakh rationale strings in `maestro/texts.py` need a review by a native speaker.
