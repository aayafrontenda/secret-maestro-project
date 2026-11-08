# CQA Backend

Evaluation service for the Conversation Quality Analytics prototype (Freedom Broker CQA hackathon).

It stores dialogs and checklists, runs evaluations through the ML service, computes weighted
scores with N/A redistribution, and handles the appeal → review → recalculation loop.

- **Stack:** Python 3.11+, FastAPI, SQLAlchemy 2 (async), SQLite (Postgres-ready), Alembic, httpx.
- **API docs:** `http://localhost:8000/docs` (Swagger) · `/redoc`
- **Base path:** `/api` — one API, in the shapes described in [docs/API_CONTRACT.md](../docs/API_CONTRACT.md).

## Quick start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                                    # defaults: SQLite + mock ML

python -m app.cli seed --file data/dev_dataset.json     # default checklist + 65 DEV dialogs
uvicorn app.main:app --reload --port 8000
```

Or with [uv](https://docs.astral.sh/uv/): `uv sync --extra dev && uv run uvicorn app.main:app --reload`.

Migrations run automatically on startup; the default checklist (the 8 criteria from the
organizer PDF) is created if none exists.

### Run with the frontend

```bash
# terminal 1
cd backend && uvicorn app.main:app --reload --port 8000
# terminal 2
cd frontend && python3 -m http.server 5173
```

In `frontend/js/config.js` set `USE_MOCKS: false` and `API_BASE: 'http://localhost:8000/api'`,
then open http://localhost:5173. Behind a tunnel (Cloudflare) point `API_BASE` at the public
backend host; CORS is open by default (`CORS_ORIGINS=*`).

### Connect the ML service

Start it from the repository root: `cd ml && uv sync && uv run maestro serve` (needs Ollama with
`qwen3.5:9b`, see [`../ml/README.md`](../ml/README.md)). Then in `.env`:

```
ML_PROVIDER=http
ML_SERVICE_URL=http://127.0.0.1:8001
QUEUE_WORKERS=1
```

One GPU scores one dialog at a time, about 24 s each, so one queue worker is enough.
The contract is in [`docs/ml-contract.md`](docs/ml-contract.md). With `ML_PROVIDER=mock`
(default) a built-in heuristic answers instead, so the UI works before the model is ready.

### Evaluate with a cloud LLM (OpenAI or any OpenAI-compatible API)

```
ML_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.6-luna
OPENAI_TEMPERATURE=
OPENAI_PRICE_INPUT_PER_1M=0.20
OPENAI_PRICE_OUTPUT_PER_1M=1.20
# OpenRouter instead: OPENAI_BASE_URL=https://openrouter.ai/api/v1, OPENAI_MODEL=google/gemini-3.7-flash
```

**Several providers at once.** Every configured provider is available side by side: cloud
(`OPENAI_API_KEY`), local (`ML_SERVICE_URL`) and the demo mock. `ML_PROVIDER` picks the default;
the «Модель оценки» block on the dialogs page (or `PUT /api/ml {"provider": "http"}`) switches
new evaluations to another one without a restart. The choice is kept in `data/runtime.json`.
Finished evaluations keep their model, so local and cloud runs can be compared on the same dialogs.

For a local model use `ML_PROVIDER=http` with the ML team's service (above). Plain Ollama behind
`OPENAI_BASE_URL` is not set up for this: it cuts the prompt at 4096 tokens and qwen's thinking
mode takes minutes per dialog. When both the evaluation model and the handoff analysis run on
the local GPU, the backend serialises their requests (two at once used to crash Ollama).

One request per dialog grades every criterion of the checklist version being evaluated; the
JSON schema is built from the checklist, so a new or edited criterion works without code changes
and the model can only answer with values the criterion allows. Before text leaves the machine,
IIN, card numbers, phones, e-mails and IBANs are masked (`PII_MASKING=true`; never for a local
server). Tokens and cost are stored on each evaluation.

With a key set (any `ML_PROVIDER`), the same LLM also analyses bot → operator handoffs
(`POST /api/insights/handoffs/analyze`).

### Load the control dataset (hour 23)

```bash
# from the organizer API (set ORGANIZER_API_URL in .env to the GET endpoint)
curl -X POST localhost:8000/api/datasets/import -H 'content-type: application/json' \
     -d '{"group_id": "CONTROL"}'

# or from a downloaded file
curl -X POST localhost:8000/api/datasets/upload-file -F file=@control.json

# then evaluate everything not yet scored with the current checklist, and watch progress
curl -X POST localhost:8000/api/evaluations/batch -H 'content-type: application/json' \
     -d '{"only_new": true}'
curl localhost:8000/api/evaluations/batch/<batch_id>
```

## How it works

```
┌──────────┐   JSON    ┌──────────────────────────────┐  POST /evaluate  ┌────────────┐
│ Frontend │ ◄───────► │ FastAPI                      │ ◄──────────────► │ ML service │
└──────────┘           │  routes → services → models  │                  └────────────┘
                       │  in-process evaluation queue │  GET ?group_id   ┌────────────┐
                       │  scoring engine              │ ◄──────────────  │ Organizers │
                       └──────────────┬───────────────┘                  └────────────┘
                                      │ SQLAlchemy (async)
                               ┌──────┴──────┐
                               │   SQLite    │  data/cqa.db
                               └─────────────┘
```

1. **Dialogs** come from the organizer API, a file upload, or a manual POST. Each message gets a
   stable `index`, which is what evidence links point to.
2. **Checklists** are editable through the API. The UI edits a JSON *document*
   (`data/checklist.default.json` is v1); every save becomes a new version and the backend derives
   its normalised criteria from it. Every evaluation stores an immutable `checklist_snapshot`
   (criteria + document), so editing a checklist never changes past results; new evaluations use
   the new version.
3. **Evaluations** are queued (`202 Accepted`) and processed by `QUEUE_WORKERS` async workers.
   The worker sends transcript + criteria to the ML service, normalises the answers, scores them
   and stores per-criterion results with explanation, evidence and the inspected range.
   Unfinished evaluations are re-queued on restart.
4. **Scoring** (`app/services/scoring.py`) follows the checklist PDF exactly: Yes = full weight,
   No = 0, scale answers are proportional to weight, N/A criteria are dropped and their weight is
   redistributed so the maximum stays 100, the total is rounded to two decimals, flag criteria
   (grave errors) never count towards the total.
5. **Appeals**: a user disputes one criterion → the reviewer sees the verdict, the evidence and the
   transcript fragment → confirms or changes the answer → the backend recalculates the final total.
   Original and final values are both kept (`original_total` / `final_total`, `answer` /
   `final_answer`).

## API overview

Everything lives under `/api`; the request/response shapes are in
[docs/API_CONTRACT.md](../docs/API_CONTRACT.md). Errors are `{ "error": "<text for a human>" }`
(FastAPI's `detail` is included too). Interactive docs: `/docs`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/queue` | Liveness, ML reachability, queue stats |
| POST | `/datasets/import` `{group_id}` | Fetch a dataset from the organizer API (needs `ORGANIZER_API_URL`) |
| POST | `/datasets/upload` `{name, payload}` | Dataset from a JSON document (organizer envelope or bare record list) |
| POST | `/datasets/upload-file` (multipart) | Same, as a file upload — handy for curl |
| GET | `/dialogs` | Rows for the list (`?channel=`, `?language=`, `?group_id=`): latest score, checklist version, appeal counters, `review_status` (none · to_review · appeal · reviewed) |
| GET | `/dialogs/{id}` | Organizer record (transcript as received) |
| DELETE | `/dialogs/{id}` | Remove a dialog with its evaluations and appeals |
| GET | `/dialogs/{id}/evaluation` | Latest **completed** evaluation or `404` |
| GET | `/dialogs/{id}/evaluations` | Evaluation history (incl. in-progress / failed) |
| GET | `/dialogs/{id}/audio` | `{url, player_url, stream_url, expires_at}` — mp3 link extracted from the player page |
| GET | `/dialogs/{id}/audio/stream` | Recording bytes proxied through the backend (fallback) |
| GET | `/checklists/active` | Active checklist document |
| GET | `/checklists/active/versions` · `/versions/{n}` | Version history; a specific version's document |
| PUT | `/checklists/active` | Save the edited document as a new version |
| POST | `/checklists/active/reset` | New version from the original PDF checklist |
| POST | `/evaluations` `{conversation_id}` | Evaluate with the active checklist (waits up to `EVALUATION_WAIT_S`) |
| POST | `/evaluations/batch` `{conversation_ids?, only_new?}` | Queue many / all dialogs → `batch_id` (`202`) |
| GET | `/evaluations/batch/{batch_id}` | Progress counters (`finished: true` when done) |
| POST | `/evaluations/batch/{batch_id}/cancel` | Cancel the batch's not-yet-started evaluations |
| GET | `/evaluations` | List (`?conversation_id=`, `?batch_id=`, `?status=`) |
| GET | `/evaluations/{id}` | Full evaluation; poll while `status` is `queued` / `running` |
| POST | `/evaluations/{id}/retry` | Re-queue a failed or cancelled evaluation |
| GET/POST | `/appeals` | List (`?evaluation_id=`, `?status=open|confirmed|changed`) / dispute a criterion |
| GET | `/appeals/{id}` | One appeal |
| POST | `/appeals/{id}/decision` `{action, answer, reason, by?}` | Reviewer decision; final total recalculated; deciding the last open appeal marks the evaluation reviewed |
| POST / DELETE | `/evaluations/{id}/review` `{by?, note?}` | Mark the verdict as checked by a supervisor / return it to the worklist (`409` while appeals are open) |
| GET / PUT | `/ml` `{provider}` | Configured evaluation providers (cloud / local / demo, reachability) and the active one; `PUT` switches new evaluations without a restart |
| GET | `/results` `?group_id=&team=&mode=&model=&download=` | `results.json` in the organizers' format 1.0 (latest evaluation per dialog, final answers; not evaluated → `status: "error"`) |
| GET | `/results/check` `?group_id=&expected=` | Validates that export: record count, the eight criteria, allowed values, `critical_flag`, no mock |
| GET | `/results/groups` | Imported dataset groups with dialog counts |
| GET | `/attention` | Review queue: grave violations, failed runs, open appeals, totals below `?threshold=` (default `ATTENTION_SCORE_THRESHOLD`), corrected model answers |
| GET | `/insights/handoffs` | Bot → operator handoffs: topics, reasons, wait for the operator, per-dialog details, LLM job status |
| POST | `/insights/handoffs/analyze` `{force?}` | Refine handoffs with the LLM in the background (`409` without a key) |
| GET | `/insights/handoffs/knowledge` `?format=json|jsonl&min_total=80` | Question → answer pairs for the bot's knowledge base, personal data masked |
| GET | `/dialogs/{id}/handoff` | Handoff analysis of one dialog (`null` without the bot) |

**Long evaluations.** A real model takes 10–15 s per chat and a single GPU serialises calls, so
`POST /evaluations` queues the job and waits up to `EVALUATION_WAIT_S` (default 85 s, under
Cloudflare's ~100 s limit). If the verdict is not ready by then, the response is the in-progress
evaluation (`status: "queued"|"running"`, empty `results`) and the client should poll
`GET /evaluations/{id}` until `status` is `completed`. Concurrent requests for the same dialog
share one evaluation. Set `QUEUE_WORKERS=1` when the model runs on one local GPU.

### Evaluation shape (`GET /evaluations/{id}`, `GET /dialogs/{id}/evaluation`)

```jsonc
{
  "evaluation_id": 12, "conversation_id": "p1-ru-001", "status": "completed",
  "checklist_id": "chat-quality", "checklist_version": 1,
  "checklist": { "id": "chat-quality", "version": 1, "sections": [...], "criteria": [...] },   // snapshot
  "model": "qwen3.5:4b", "is_mock": false, "created_at": "...", "latency_ms": 12400,
  "cost_usd": 0, "tokens": { "input": 4200, "output": 650 },
  "results": [
    {
      "criterion_id": "c03", "answer": "no",                 // the model's verdict
      "explanation": "Данные счёта раскрыты без подтверждения личности.",
      "na_reason": null,
      "evidence": [{ "msg": 11, "quote": "..." }],           // 0-based transcript indexes
      "checked_range": [9, 13],                              // where a missed action was expected
      "final_answer": "yes",                                 // after reviewer decisions
      "points": 0, "final_points": 23.53, "effective_weight": 23.53
    }
  ],
  "total": 76.47, "final_total": 88.24,                      // backend-computed; the UI recomputes the same
  "gross_error": false, "final_gross_error": false,
  "sections": [{ "name": "...", "points": 29.41, "max_points": 29.41, "criteria": ["c01", "c02"] }]
}
```

`effective_weight` is the weight after N/A redistribution; `points` are earned against it.
Per-criterion points are rounded to 2 decimals and the total once from the exact sum, so they can
differ by ±0.01.

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/cqa.db` | Any async SQLAlchemy URL (`postgresql+asyncpg://…` with `pip install -e ".[postgres]"`) |
| `CORS_ORIGINS` | `*` | Comma-separated origins |
| `ORGANIZER_API_URL` | — | The signed «Открыть GET для DEV» link from the task PDF, as is; its `group_id` is replaced per request |
| `ML_PROVIDER` | `mock` | `mock`, `http` or `openai` |
| `ML_SERVICE_URL` | — | Base URL of the ML service (`/evaluate`, `/health`) |
| `ML_TIMEOUT_S` / `ML_MAX_RETRIES` | `180` / `2` | Per-request timeout; retries on 5xx/network errors |
| `ML_MOCK_DELAY_S` | `0` | Mock only: seconds per evaluation, to rehearse a slow model |
| `OPENAI_API_KEY` | — | Enables `ML_PROVIDER=openai` and LLM handoff analysis |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible cloud API (OpenRouter…); local models go through `ML_PROVIDER=http` |
| `OPENAI_MODEL` / `OPENAI_TEMPERATURE` | `gpt-4.1` / `0` | Model; leave the temperature empty for models that reject it (gpt-5.x) |
| `OPENAI_REASONING_EFFORT` | — | `none` / `low` / `medium` / `high` for reasoning models |
| `OPENAI_PRICE_INPUT_PER_1M` / `…_OUTPUT_…` | `2.0` / `8.0` | USD per 1M tokens for the cost shown per evaluation |
| `PII_MASKING` | `true` | Mask personal data before it reaches a non-local LLM |
| `OUTPUT_LANGUAGE` | `ru` | Language of model explanations |
| `RUNTIME_STATE_FILE` | `data/runtime.json` | Where the provider chosen in the UI is kept; empty to disable |
| `TEAM_NAME` | `Maestro` | `team_name` in `results.json` |
| `ATTENTION_SCORE_THRESHOLD` | `60` | Totals below this land in the attention queue |
| `QUEUE_WORKERS` | `3` | Parallel evaluations against the ML service (`1` for one local GPU) |
| `EVALUATION_WAIT_S` | `85` | How long `POST /api/evaluations` waits before returning the in-progress state |
| `SEED_DEFAULT_CHECKLIST` | `true` | Create the PDF checklist on first start |

## CLI

```bash
python -m app.cli migrate                               # apply migrations
python -m app.cli seed --file data/dev_dataset.json     # default checklist + dialogs from file
python -m app.cli seed --group-id DEV                   # ... or from ORGANIZER_API_URL
python -m app.cli evaluate-all [--force]                # evaluate every dialog without the server
python -m app.cli export-checklist [--out checklist.json]
```

## Development

```bash
pytest                 # 62 tests: scoring rules, API contract, batches/retries, appeals, ML client, failure modes
ruff check . && ruff format .
alembic revision --autogenerate -m "describe change"    # after editing app/models
```

## Docker

```bash
docker build -t cqa-backend .
docker run -p 8000:8000 -v "$PWD/data:/app/data" --env-file .env cqa-backend
```

## Project layout

```
backend/
├── app/
│   ├── main.py            # app factory, lifespan (migrations, seed, queue)
│   ├── cli.py             # operational commands
│   ├── api/               # routers (datasets, dialogs, checklists, evaluations, appeals, system) + serializers
│   ├── core/              # settings, db engine, logging, migrations runner
│   ├── models/            # SQLAlchemy models
│   ├── schemas/           # Pydantic request/response models
│   ├── services/          # scoring, evaluation pipeline, queue, appeals, checklist document, audio, organizer client
│   └── ml/                # ML contract + clients (mock, http)
├── alembic/               # migrations
├── data/dev_dataset.json  # organizer DEV dataset (65 dialogs)
├── data/checklist.default.json  # the PDF checklist in the UI document format (seeded as v1)
├── docs/ml-contract.md
└── tests/
```
