# Control day runbook

The organizers send 10 new dialogs and replace one checklist criterion. Everything runs on one laptop:
Ollama (the model, on the GPU) + two Docker containers (backend with the frontend, ML service) + the
Cloudflare tunnel (a Windows service) that publishes them at https://web.drdieb.com.

Rehearsed end to end on DEV: import, criterion replacement through the UI, batch evaluation, export.
One dialog takes 30–40 s, so 10 dialogs take about 6–7 minutes.

## 30 minutes before

1. Laptop on the charger, Windows power mode "Best performance", sleep off:
   `powercfg /change standby-timeout-ac 0` and `powercfg /change monitor-timeout-ac 0`.
2. Pause Windows Update (Settings → Windows Update → Pause). Close games and heavy apps: they take GPU memory.
3. Docker Desktop and Ollama are running (icons in the tray). From the repository root:
   ```
   docker compose ps                      # maestro-backend-1 Up, maestro-ml-1 Up (healthy)
   curl http://localhost:8000/api/health  # "ml": {... "reachable": true}
   ```
4. Open https://web.drdieb.com from a phone on mobile data: this is what the jury sees.
5. Warm the model: open any dialog and press "Оценить". The first evaluation after a restart is a minute slower.

## During the control check

1. **Import.** Dialogs page → "Импорт" with the group id the organizers give, or upload their JSON file.
   Or: `curl -X POST localhost:8000/api/datasets/import -H "content-type: application/json" -d "{\"group_id\": \"CONTROL\"}"`
2. **Replace the criterion.** Checklist page → edit the criterion (title, rule, type, N/A condition) →
   "Распределить до 100" if the weights changed → save. A changed criterion goes to the generic evaluator
   automatically; the other seven keep their built-in logic.
3. **Evaluate.** Dialogs page → "Оценить новые". Progress is shown on the page and survives a closed tab.
4. **Check.** Open two or three dialogs: answers, explanations, evidence, the replaced criterion.
5. **Export.** Analytics page → "Экспорт" (CSV or JSON).
6. **Submit `results/prod/results.json`** (organizers' format 1.0, must be pushed before the code freeze;
   evaluate the 10 dialogs on the **original eight criteria**, the replaced criterion is a separate check):
   ```
   curl.exe "http://localhost:8000/api/results/check?group_id=<control id>&expected=10"
   curl.exe "http://localhost:8000/api/results?group_id=<control id>&download=true" -o results/prod/results.json
   git add results && git commit -m "chore: control set results" && git push
   ```
   `check` must show `"ok": 10` and `"problems": []`. The same from the UI: Analytics → «Сдача результатов» →
   pick the set → «Проверить» → «Скачать results.json». Use `curl.exe` or the button, not PowerShell `>`
   (it writes UTF-16). `results/dev/results.json` is made the same way with `group_id=DEV&expected=65`.

## If something goes wrong

| Symptom | Do this |
|---|---|
| The site shows a Cloudflare 502 | `docker compose up -d`, then `Get-Service cloudflared` must be Running |
| Evaluations fail with "ML service unavailable" | Start Ollama from the Start menu; `docker compose restart ml` |
| One dialog takes more than 90 s | Something else uses the GPU: close it; `ollama ps` should show `qwen3.5:9b` |
| The UI still shows an old version | Ctrl+F5 |
| The GPU or Ollama cannot be fixed in time | Switch the ML provider to `openai` in the UI (cloud, needs the key in `backend/.env`) |
| The checklist got broken while editing | Checklist page → restore the original checklist, then make the change again |

Do not run `eval/run_dev.py` or other model scripts during the check: there is one GPU, and parallel
requests to Ollama have crashed it before.

The generic evaluator may be configured with a cloud model (`MAESTRO_GENERIC_MODEL` in `ml/.env`). If that
model is unavailable (no network, no credit), the ML service switches to the local model for 10 minutes
and the evaluation still completes.
