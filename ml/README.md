# ML: chat quality scoring

Scores a customer support chat or call against a checklist (by default the 8-criterion Freedom Broker one) and
returns, per criterion, the answer, a short rationale and the messages that support it. Dialogs can be in Russian,
Kazakh or English; rationales come in the dialog's language. The backend turns the answers into points.

The default model is `qwen3.5:9b`, running locally through [Ollama](https://ollama.com): an evaluation costs
nothing. Cloud models can be plugged in through any OpenAI-compatible API (see "Models").

## How it works

The backend calls `POST /evaluate` with one dialog, the checklist and its general rules (`maestro/service.py`,
`maestro/contract.py`). A criterion whose wording is one of the eight standard ones runs the detailed logic below;
any other, new or reworded, is scored from its own wording by the generic evaluator, so checklist edits always
take effect (`maestro/presets.py`).

1. **Facts** (`maestro/facts.py`): code finds the first and last operator messages, each side's language and long
   pauses.
2. **Probes** (`maestro/probes.py`): the model answers narrow yes/no questions, one per call, such as "does the
   operator's first message contain a greeting?". Each question sees only the messages that can answer it. The
   model writes its reasoning first, then the answer, then the ID of the message it relied on.
3. **Rules** (`maestro/rules.py`): code turns probe answers into the verdict. Unambiguous cases are settled
   without the model: greetings and goodbyes, "identity verified" and "operator closed the chat" system events.
   Verdicts that a broad question tends to over-call are confirmed by a narrow question on the cited message:
   06 levels 0 and 7, the client asking again, 02 "asked again for a known detail".
4. **Generic evaluator** (`maestro/generic.py`): for a new criterion, applicability (N/A) is decided in its own
   call, then the answer, with N/A no longer allowed. `MAESTRO_GENERIC_MODE=decompose` instead splits the
   criterion into narrow questions (`maestro/decompose.py`); it scored lower on the held-out set, so it is off.
5. **Suggestions** (`POST /suggest`, `maestro/suggest.py`): on request, the operator message that would have met
   a failed criterion, in the client's language, with facts the chat does not contain left as placeholders.

Evidence text is copied from the transcript by code, so a quote cannot be invented. Every model call is recorded:
prompt hash, raw answer, tokens and time.

## Models

| Setting (`ml/.env`) | What it does |
|---|---|
| `MAESTRO_MODEL=qwen3.5:9b` | Local model (default). About 15 calls and 30–40 s per dialog on an RTX 4070 Laptop, 8 GB. |
| `MAESTRO_BACKEND=openai` | All criteria on a cloud model (`MAESTRO_OPENAI_MODEL`, `OPENAI_API_KEY`). `gpt-4.1-mini`: about $0.006 and 14 s per dialog. |
| `MAESTRO_GENERIC_MODEL` | A separate cloud model for new criteria only. If it is unavailable (no network, no credit), the service uses the local model for 10 minutes. |

`ml/.env` is read at start; a variable set in the shell wins. Recommended for Ollama:
`OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` (about 15% faster). Never send concurrent requests to
one Ollama on one GPU: it has crashed with a CUDA error; the service serialises its own calls.

## Setup and use

```sh
ollama pull qwen3.5:9b
cd ml
uv sync
uv run maestro health
uv run maestro serve            # HTTP service for the backend on port 8001
```

Or `docker compose up -d --build` from the repository root, which runs this service next to the backend.
Contract details: [docs/ML_API.md](docs/ML_API.md).

## Accuracy

There is no ground truth from the organizers, so the team labelled dialogs by the checklist PDF.

| Set | Criteria | Agreement |
|---|---|---|
| `data/test/`: 13 new dialogs labelled by a person, never used for tuning | 8 standard | 85.6% |
| same | 4 new criteria replacing 05, 06, 07, plus a new flag | 86.5% (decomposed mode: 76.9%) |
| `data/reference/dev_reference.json`: 19 DEV dialogs the probes were tuned on | 8 standard | ≈ 87% |

Weakest: 02 needs discovery (7/13 on the test set; its condition reads more than one way), then the N/A decision
of new criteria. Thinking mode was tried on 02 and 06: Qwen 9B overran 4096 tokens of reasoning per narrow
question, so it is not usable on this hardware. `qwen3.5:4b` scored 71.1% on the DEV labels at about half the time.

```sh
uv run pytest
uv run python eval/run_dev.py data/test/test_dataset.json --labels data/test/test_labels.json
uv run python eval/run_dev.py data/test/test_dataset.json --criteria data/test/checklist_new_criteria.json \
  --labels data/test/test_labels_new_criteria.json
uv run python eval/run_dev.py ../backend/data/dev_dataset.json --labels data/reference/dev_reference.json
```

`eval/run_dev.py` sends each dialog through the same path as `POST /evaluate` and prints agreement per criterion
and language, speed, failures and answer distributions. `--backend openai --model ... --workers 6` runs a cloud
model; `--criteria` takes any checklist. `docs/ACCURACY_REVIEW.md` records the earlier rounds of fixes.

## Known gaps

- Criterion 04 cannot check facts about Freedom Broker tariffs or procedures: there is no reference material. It
  catches answers that are missing, partial or self-contradictory.
- Criterion 07 is read as "(summary or offer of further help) and goodbye".
- The wait before the operator's first reply is not a 06 lapse: the checklist does not score first-response time.
- Answers can differ between runs on borderline cases even at temperature 0: GPU inference is not fully
  deterministic.
- Kazakh rationale strings in `maestro/texts.py` need a review by a native speaker.
