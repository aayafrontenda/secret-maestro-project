# API контракт фронт ↔ бэк

Фронт ходит только через `frontend/js/api.js`. Сейчас там `USE_MOCKS: true` (см. `frontend/js/config.js`).
Чтобы подключить бэк: реализуй эндпоинты ниже, поставь `USE_MOCKS: false` и `API_BASE`.
Эталон поведения — мок в `frontend/js/mock/mockApi.js`: те же сигнатуры, те же формы ответов.

## Чек-лист подключения

1. В `frontend/js/config.js`: `USE_MOCKS: false`, `API_BASE: 'http://<хост>:<порт>/api'`. Больше во фронте ничего не меняется.
2. CORS-заголовки на всех ответах + ответ на `OPTIONS` (фронт шлёт `Content-Type: application/json`).
3. `GET /api/dialogs/:id/evaluation` без оценки → **404** (фронт тогда сам запустит оценку при открытии карточки).
4. В оценке обязательно: `evaluation_id`, `checklist_version`, `checklist` (снимок), `results[]` с `criterion_id` из чек-листа.
   Остальное (`cost_usd`, `latency_ms`, `confidence`, `quote`) можно не отдавать — фронт покажет «—».
5. `answer`: `"yes" | "no" | "na"` или число-ступень шкалы. Строки «15», «Да», «N/A» фронт тоже поймёт, но лучше сразу правильно.
6. `evidence[].msg` вне диапазона транскрипта фронт молча отбросит — проверяй индексы на бэке, иначе ссылки потеряются.
7. Самопроверка: `node tools/fake-backend.mjs` → http://127.0.0.1:8787 — фронт на фейковом бэке по этому контракту.
   Сравни ответы своего бэка с ответами фейка.

Общее:
- JSON, UTF-8. Ошибка: HTTP 4xx/5xx + `{ "error": "текст для человека" }`.
- CORS: разреши `http://localhost:5173` (dev) и `*.dynamics.com` (на будущее).
- Индексы реплик (`msg`, `checked_range`) — **0-based индекс в `transcript`** как пришёл от организаторов. Метки времени не трогаем.

---

## Диалоги

### `POST /api/datasets/import` — подтянуть набор у организаторов
```json
{ "group_id": "DEV" }
```
→ `{ "group_id": "DEV", "imported": 65 }`
Бэк сам делает GET к API организаторов (из браузера будет CORS) и сохраняет записи как есть.
На контроле придёт другой `group_id` — его вводят в UI.

### `POST /api/datasets/upload` — набор из JSON-файла (запасной путь)
```json
{ "name": "CONTROL", "payload": { "data": { "dataset_group_id": "CONTROL", "records": [ ... ] } } }
```
`payload` — ответ API организаторов целиком или просто массив записей. → `{ "group_id": "CONTROL", "imported": 10 }`

### `GET /api/dialogs`
→ массив
```json
[{ "conversation_id": "p1-ru-001", "channel": "agent chat", "language": "RU", "group_id": "DEV", "turns": 12,
   "evaluation": "none | done", "total": 84.62, "gross_error": false,
   "checklist_version": 1, "evaluated_at": "...", "appeals_open": 0, "appeals_total": 0 }]
```
`total` — с учётом решений по апелляциям.

### `GET /api/dialogs/:id`
→ запись в исходном формате организаторов:
```json
{ "conversation_id": "p1-ru-001", "channel": "agent chat", "language": "RU",
  "transcript": [{ "timestamp": "00:02", "speaker": "operator", "text": "..." }],
  "audio_url": null }
```

### `GET /api/dialogs/:id/audio` — только для `voice call`
→ `{ "url": "https://...mp3?sig=...", "player_url": "<audio_url>", "expires_at": "2026-11-07T09:44:28Z" }`

**Важно:** `audio_url` от организаторов отдаёт **HTML-страницу плеера**, не mp3.
Внутри неё `<audio><source src="https://freedomholdingcorporation.crm11.dynamics.com/api/filedownload/...&sig=..." type="audio/mpeg">`.
Ссылка SAS, живёт ~1 час. Бэк: GET `audio_url` → regex `<source src="([^"]+)"` → html-unescape (`&amp;` → `&`) → отдать `url`.
Вызывать при каждом открытии карточки (не кэшировать дольше ~50 минут). Если не вышло — `url: null`, фронт покажет ссылку на внешний плеер.

---

## Чек-лист

### `GET /api/checklists/active` → объект чек-листа (последняя версия)
### `GET /api/checklists/active/versions` → `[{ version, name, updated_at, criteria }]` (criteria — число критериев)
### `PUT /api/checklists/active` — сохранить: тело = чек-лист целиком, бэк создаёт **новую версию** (`version + 1`, `updated_at`) и возвращает её
### `POST /api/checklists/active/reset` — новая версия из исходного чек-листа (PDF), возвращает её

Валидация (фронт проверяет, бэку стоит повторить): сумма `weight` у не-`flag` критериев = 100, у scale ≥ 2 уникальных ступеней,
при `na_allowed` заполнено `na_condition`, у каждого критерия есть `name` и `description`.

Формат — `frontend/mocks/checklist.default.json`. Ключевое:
```json
{
  "id": "chat-quality", "name": "...", "version": 1,
  "rules": { "rounding": 2, "first_response_threshold_sec": 180, "notes": ["..."] },
  "sections": [{ "id": "s1", "name": "Начало и понимание запроса" }],
  "criteria": [{
    "id": "c04", "code": "04", "section": "s2", "name": "Корректная и полная консультация",
    "type": "binary | scale | flag", "weight": 20, "na_allowed": true,
    "description": "критерий для LLM", "na_condition": "когда ставить N/A",
    "scale": [{ "value": 20, "label": "..." }]
  }]
}
```
`flag` = грубые ошибки, вес 0, в итог не входит.
**Промпт LLM должен собираться из этого JSON**, а не быть захардкожен — на контроле заменят критерий через UI.

---

## Оценка

### `POST /api/evaluations`
```json
{ "conversation_id": "p1-ru-001", "checklist_id": "chat-quality" }
```
→ объект оценки (и сохранить как последнюю для диалога):
```json
{
  "evaluation_id": "ev_123",
  "conversation_id": "p1-ru-001",
  "checklist_id": "chat-quality", "checklist_version": 1,
  "checklist": { "...": "снимок чек-листа, по которому оценивали" },
  "model": "claude-sonnet-5-5", "is_mock": false,
  "created_at": "2026-11-07T13:55:00Z",
  "latency_ms": 4200, "cost_usd": 0.0123, "tokens": { "input": 5400, "output": 800 },
  "results": [{
    "criterion_id": "c01",
    "answer": "yes | no | na | <число для scale>",
    "explanation": "Короткое обоснование",
    "na_reason": "только если answer = na",
    "evidence": [{ "msg": 9, "quote": "точная цитата из реплики" }],
    "checked_range": [9, 11],
    "confidence": 0.86
  }]
}
```
- `evidence` — реплики-доказательства. `checked_range` — для пропущенного действия: где оно ожидалось.
- Для scale `answer` — одна из ступеней `scale[].value`.
- Если `na` не разрешён критерием — не возвращать `na`.
- `cost_usd` и `model` организаторы прямо просят показать.
- `checklist` — **снимок** чек-листа на момент оценки. Карточка рисует результат по нему, а не по активному:
  после замены критерия старые оценки не ломаются, а помечаются «оценено по v1, активна v2».

### `GET /api/dialogs/:id/evaluation` → последняя оценка или 404

### Итоговый балл
Фронт считает сам из `results` (`frontend/js/scoring.js`), бэк может считать так же и отдавать `total` в списке.
Правила: да = полный вес, нет = 0, шкала = ступень / максимум × вес, вес N/A перераспределяется пропорционально,
итог округляется до 2 знаков, если применимых нет — итога нет. Грубые ошибки отдельно.

---

## Апелляции

### `POST /api/appeals`
```json
{ "evaluation_id": "ev_123", "conversation_id": "p1-ru-001", "criterion_id": "c01", "comment": "..." }
```
→
```json
{ "appeal_id": "ap_1", "evaluation_id": "ev_123", "conversation_id": "p1-ru-001", "criterion_id": "c01",
  "criterion_name": "Установление контакта", "original_answer": "yes",
  "comment": "...", "status": "open", "created_at": "...", "decision": null }
```

### `GET /api/appeals` → все; фильтры `?evaluation_id=ev_123`, `?status=open` → массив

### `POST /api/appeals/:id/decision`
```json
{ "action": "confirm | change", "answer": "no", "reason": "..." }
```
→ апелляция с `status: "confirmed" | "changed"` и `decision: { action, answer, reason, decided_at }`.
Исходная оценка **не перезаписывается** — финальный результат = исходные ответы + решения по апелляциям.
