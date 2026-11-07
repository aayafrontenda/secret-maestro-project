# CQA Backend

Evaluation service for the Conversation Quality Analytics prototype (Freedom Broker CQA hackathon).

It stores dialogs and checklists, runs evaluations through the ML service, computes weighted
scores with N/A redistribution, and handles the appeal → review → recalculation loop.

- **Stack:** Python 3.11+, FastAPI, SQLAlchemy 2 (async), SQLite (Postgres-ready), Alembic, httpx.
- **API docs:** `http://localhost:8000/docs` (Swagger) · `/redoc`
- **Base path:** `/api/v1`

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

### Connect the ML service

```
ML_PROVIDER=http
ML_SERVICE_URL=http://localhost:8001
```

The contract is in [`docs/ml-contract.md`](docs/ml-contract.md). With `ML_PROVIDER=mock`
(default) a built-in heuristic answers instead, so the UI works before the model is ready.

### Load the control dataset (hour 23)

```bash
# from the organizer API (set ORGANIZER_API_URL in .env to the GET endpoint)
curl -X POST localhost:8000/api/v1/dialogs/import -H 'content-type: application/json' \
     -d '{"group_id": "CONTROL"}'

# or from a downloaded file
curl -X POST localhost:8000/api/v1/dialogs/import-file -F file=@control.json

# then evaluate everything that is not evaluated yet
curl -X POST localhost:8000/api/v1/evaluations/batch -H 'content-type: application/json' \
     -d '{"skip_evaluated": true}'
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
2. **Checklists** are editable through the API. Every evaluation stores an immutable
   `checklist_snapshot`, so editing a checklist never changes past results; new evaluations
   use the new version.
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

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/queue` | Liveness, ML reachability, queue stats |
| GET | `/dialogs` | List (filters: `channel`, `language`, `group_id`, `q`; paginated) with latest score |
| GET | `/dialogs/{id}` | Transcript with message indexes + evaluation history |
| POST | `/dialogs` | Upload one dialog or a list (organizer record format) |
| POST | `/dialogs/import` | Fetch a dataset by `group_id` from the organizer API |
| POST | `/dialogs/import-file` | Upload the organizer JSON file |
| GET | `/dialogs/{id}/audio` | Stream the call recording (CORS-free proxy) |
| GET/POST | `/checklists` | List / create |
| GET | `/checklists/default` | The checklist used when none is specified |
| GET/PUT/DELETE | `/checklists/{id}` | Read / replace (bumps `version`) / delete |
| POST | `/checklists/{id}/duplicate`, `/{id}/default` | Copy; make default |
| POST | `/evaluations` | Queue one evaluation → `202` |
| POST | `/evaluations/sync` | Evaluate one dialog and wait (demo-friendly) |
| POST | `/evaluations/batch` | Queue many / all dialogs → `batch_id` |
| GET | `/evaluations/batch/{batch_id}` | Progress counters |
| GET | `/evaluations`, `/evaluations/{id}` | List (filters) / full result card |
| POST | `/evaluations/{id}/retry` | Re-queue a failed evaluation |
| POST | `/evaluations/{id}/appeals` | Dispute a criterion |
| GET | `/appeals?status=pending` | Reviewer queue |
| GET | `/appeals/{id}` | Dispute + evidence + transcript fragment |
| POST | `/appeals/{id}/decision` | `confirm` or `change` (+ `new_answer`, `reason`) |

### Result card shape (`GET /evaluations/{id}`)

```jsonc
{
  "id": 12, "dialog_id": "p1-ru-001", "status": "completed",
  "checklist_snapshot": {"id": 1, "version": 1, "criteria": [...]},
  "provider": "openai", "model_name": "gpt-4o-mini",
  "usage": {"prompt_tokens": 4200, "completion_tokens": 650, "calls": 1, "cost_usd": 0.0011},
  "original_total": 76.47, "final_total": 88.24,
  "grave_error": false, "final_grave_error": false,
  "original_sections": [{"name": "Начало и понимание запроса", "points": 29.41, "max_points": 29.41, "criteria": ["c1","c2"]}],
  "final_sections": [...],
  "results": [
    {
      "id": 90, "criterion_code": "c3", "criterion_title": "Идентификация",
      "answer_type": "yes_no", "is_flag": false, "weight": 20,
      "answer": "no", "score": 0, "effective_weight": 23.53,
      "explanation": "Данные счёта раскрыты без подтверждения личности.",
      "evidence": [{"message_index": 11, "timestamp": "01:40", "speaker": "operator", "text": "..."}],
      "checked_range": {"from_index": 9, "to_index": 13},
      "na_reason": null, "normalization_note": null,
      "final_answer": "yes", "final_score": 23.53, "final_effective_weight": 23.53,
      "appeals": [{"id": 3, "status": "changed", "comment": "...", "previous_answer": "no",
                   "new_answer": "yes", "decision_reason": "...", "decided_at": "..."}]
    }
  ]
}
```

`effective_weight` is the weight after N/A redistribution; `score` is the points earned against it.
Per-criterion points are rounded to 2 decimals, the total is rounded once from the exact sum,
so the two can differ by ±0.01.

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/cqa.db` | Any async SQLAlchemy URL (`postgresql+asyncpg://…` with `pip install -e ".[postgres]"`) |
| `CORS_ORIGINS` | `*` | Comma-separated origins |
| `ORGANIZER_API_URL` | — | GET endpoint of the organizer API (`group_id` is appended) |
| `ML_PROVIDER` | `mock` | `mock` or `http` |
| `ML_SERVICE_URL` | — | Base URL of the ML service (`/evaluate`, `/health`) |
| `ML_TIMEOUT_S` / `ML_MAX_RETRIES` | `180` / `2` | Per-request timeout; retries on 5xx/network errors |
| `QUEUE_WORKERS` | `3` | Parallel evaluations against the ML service |
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
pytest                 # 52 tests: scoring rules, full API flow, appeals, ML client, failure modes
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
│   ├── api/               # routers (dialogs, checklists, evaluations, appeals, system)
│   ├── core/              # settings, db engine, logging, migrations runner
│   ├── models/            # SQLAlchemy models
│   ├── schemas/           # Pydantic request/response models
│   ├── services/          # scoring, evaluation pipeline, queue, appeals, organizer client
│   └── ml/                # ML contract + clients (mock, http)
├── alembic/               # migrations
├── data/dev_dataset.json  # organizer DEV dataset (65 dialogs)
├── docs/ml-contract.md
└── tests/
```
