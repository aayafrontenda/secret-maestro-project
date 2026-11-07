# ML service for the backend

The ML service implements the contract in `backend/docs/ml-contract.md`: `POST /evaluate` and `GET /health`. It runs locally with Ollama; no cloud APIs are used.

## Run it

On the machine with the GPU:

```sh
ollama pull qwen3.5:9b
cd ml
uv sync
uv run maestro health          # {"ok": true, "model": "qwen3.5:9b"}
uv run maestro serve           # http://127.0.0.1:8001
```

Backend `.env`:

```
ML_PROVIDER=http
ML_SERVICE_URL=http://127.0.0.1:8001
ML_TIMEOUT_S=180
```

For speed, set `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` as user environment variables and restart the Ollama app; on our laptop this cut about 15% per dialog.

`uv run maestro serve --host 0.0.0.0 --port 8001` makes it reachable from another machine. Settings for the model are `MAESTRO_*` variables in `ml/.env.example`.

## Behaviour the backend should know

- **One dialog at a time.** There is one GPU, so the service runs model calls for one dialog at a time and other requests wait. The backend's 3 queue workers are fine, but the wait counts toward `ML_TIMEOUT_S`. `QUEUE_WORKERS=1` avoids that.
- **Speed.** On an RTX 4070 Laptop (8 GB) with `qwen3.5:9b`: 11–18 model calls and 22–38 seconds per dialog, about 5 minutes for 10 dialogs. The first request after Ollama starts also loads the model, about a minute. `MAESTRO_MODEL=qwen3.5:4b` halves the time at lower accuracy (71% vs 79% agreement on our 19 labelled DEV dialogs).
- **Any checklist works.** Each criterion in the request is checked against the eight standard criteria by its rule, answer type and scale. A recognised one uses detailed built-in logic; a new or reworded one is scored from its own `title`, `rule`, `na_rule` and `scale_steps` by a generic evaluator. Codes are never hard-coded. `results[].method` says which path was used (`standard` or `generic`).
- **Language.** `explanation` and `na_reason` are written in the dialog's language from `language` (`RU`, `KZ`, `EN`).
- **Evidence.** `evidence` holds `index` values from the request. For a missed action or a violation that was not found, `checked_range` gives the span that was checked.
- **Cost.** `model` is `{"provider": "ollama", "name": "qwen3.5:9b"}`, and `usage.cost_usd` is 0 because everything runs locally. `usage` also has token counts and the number of model calls.

## Extra response fields

Besides the contract fields, each result has:

| Field | Meaning |
|---|---|
| `method` | `standard` (built-in logic) or `generic` (scored from the criterion's own wording) |
| `standard_id` | Which standard criterion was recognised, `01`…`08` |
| `facts` | Answers to the narrow questions behind the verdict, e.g. `{"greeted": true, "introduced": false}` |

The response also has `duration_ms`. The backend's schema ignores unknown fields, so these are safe to keep or drop.

## Errors

| Status | Meaning | Backend behaviour |
|---|---|---|
| 422 | Empty transcript or criteria, or an unknown `speaker` | Not retried |
| 502 | The model gave no usable answer after retries | Retried (5xx) |
| 503 | Ollama is down or the model is not installed; `/health` also returns 503 | Retried (5xx) |

The service never makes up an answer: if it cannot answer a criterion, the whole request fails with 502.

## Check it without the backend

```sh
uv run python eval/run_dev.py ../backend/data/dev_dataset.json --only p1-ru-001 --out runs/check
```

This sends DEV dialogs through the same code path as `POST /evaluate` with the checklist in `ml/data/default_checklist.json` and prints each answer. `--criteria other.json` uses another checklist in the same format.
