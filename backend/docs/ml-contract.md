# Backend ↔ ML contract

The backend owns scoring. The ML service only answers each criterion and points at the evidence.

Set in the backend's `.env`:

```
ML_PROVIDER=http
ML_SERVICE_URL=http://localhost:8001
```

The backend then calls `POST {ML_SERVICE_URL}/evaluate` once per (dialog, checklist) and
`GET {ML_SERVICE_URL}/health` for the health check (any 2xx/4xx counts as reachable).

Until the ML service is ready, `ML_PROVIDER=mock` answers with built-in heuristics so the
frontend and the appeal flow can be developed and demoed.

## Request — `POST /evaluate`

```json
{
  "conversation_id": "p1-ru-001",
  "channel": "agent chat",
  "language": "RU",
  "transcript": [
    {"index": 0, "timestamp": "00:00", "speaker": "client",   "text": "Где посмотреть мой тариф?"},
    {"index": 1, "timestamp": "00:02", "speaker": "bot",      "text": "Здравствуйте! Я AIM..."},
    {"index": 9, "timestamp": "01:15", "speaker": "operator", "text": "Здравствуйте! Меня зовут Алина..."}
  ],
  "criteria": [
    {
      "code": "c1",
      "title": "Установление контакта",
      "rule": "Да — оператор поздоровался на языке клиента и представился в первом ответе.",
      "section": "Начало и понимание запроса",
      "answer_type": "yes_no",
      "scale_max": null,
      "scale_steps": null,
      "weight": 10,
      "allow_na": false,
      "na_rule": null,
      "is_flag": false
    },
    {
      "code": "c4",
      "title": "Корректная и полная консультация",
      "rule": "Оцените ответ или следующий шаг по шкале 0–20.",
      "section": "Безопасность и решение",
      "answer_type": "scale",
      "scale_max": 20,
      "scale_steps": [
        {"value": 20, "label": "Все существенные вопросы закрыты..."},
        {"value": 15, "label": "Основной вопрос решён, пропущена второстепенная деталь."},
        {"value": 10, "label": "..."},
        {"value": 5,  "label": "..."},
        {"value": 0,  "label": "..."}
      ],
      "weight": 20,
      "allow_na": true,
      "na_rule": "N/A — чат закончился до того, как клиент сформулировал запрос.",
      "is_flag": false
    },
    {
      "code": "c8",
      "title": "Грубые ошибки",
      "rule": "Да — оскорбление, услуга в обход компании или раскрытие конфиденциальной информации.",
      "answer_type": "yes_no",
      "weight": 0,
      "allow_na": false,
      "is_flag": true
    }
  ]
}
```

Notes:

- `index` is the 0-based position of the message in the transcript. Use it in `evidence`.
- `speaker` ∈ `client | operator | bot | system`. Only the operator is being evaluated; bot and
  system lines are context (e.g. `"Личность клиента подтверждена."` is a system event).
- `timestamp` is `MM:SS` for chats and ISO 8601 for calls. Keep it as a string.
- The checklist is user-editable, so **do not hard-code criterion codes** — follow `rule`,
  `na_rule`, `answer_type` and `scale_steps` from the request. A new criterion may appear at any time.
- `language` ∈ `RU | KZ | EN`.

## Response

```json
{
  "conversation_id": "p1-ru-001",
  "results": [
    {
      "code": "c1",
      "answer": "yes",
      "explanation": "Оператор поздоровался и представился в первом ответе.",
      "evidence": [9]
    },
    {
      "code": "c3",
      "answer": "na",
      "na_reason": "Запрос не требовал идентификации: общий вопрос о тарифе.",
      "explanation": "Клиент спрашивал, где найти тариф; защищённых действий не было.",
      "evidence": [0, 9]
    },
    {
      "code": "c4",
      "answer": 15,
      "explanation": "Основной вопрос решён, не уточнён период действия тарифа.",
      "evidence": [9, 11]
    },
    {
      "code": "c7",
      "answer": "no",
      "explanation": "После ответа оператор закрыл чат без прощания.",
      "evidence": [12],
      "checked_range": {"from_index": 9, "to_index": 13}
    },
    {
      "code": "c8",
      "answer": "no",
      "explanation": "Оскорблений, обходных предложений и утечек нет.",
      "checked_range": {"from_index": 9, "to_index": 13}
    }
  ],
  "model": {"provider": "openai", "name": "gpt-4o-mini"},
  "usage": {"prompt_tokens": 4200, "completion_tokens": 650, "calls": 1, "cost_usd": 0.0011}
}
```

Rules:

- Return **one result for every criterion code** in the request. Missing codes fail the evaluation.
- `answer`:
  - `yes_no` criteria: `"yes"`, `"no"`, or `"na"` (only if `allow_na` is true).
  - `scale` criteria: an integer from `scale_steps` (or `0..scale_max`), or `"na"` if allowed.
  - flag criteria (`is_flag`): `"yes"` / `"no"`.
- `explanation`: one or two sentences, in the dialog's language, stating what the evidence shows.
- `evidence`: transcript indexes that support the verdict. For a **missed** action, give
  `checked_range` (where the action was expected) instead of, or in addition to, evidence.
- `na_reason`: required when `answer` is `"na"` — which N/A condition from `na_rule` applies.
- `model` and `usage` are optional but wanted: the organizers ask for the model name and the
  approximate cost of one evaluation.

The backend tolerates minor sloppiness and records a `normalization_note` when it does:
`"Да"/"Нет"` are mapped to yes/no, off-step scale values snap to the nearest step, values are
clamped to `[0, scale_max]`, N/A on a criterion that forbids it becomes `"no"` / `0`,
out-of-range evidence indexes are dropped.

## Errors

- Any non-2xx with a JSON/text body. 5xx responses are retried (`ML_MAX_RETRIES`, exponential
  backoff); 4xx are not.
- Timeouts: `ML_TIMEOUT_S` (default 180 s) per request.

## Plugging in a Python module instead of HTTP

If the model ends up as a Python package, implement `app.ml.base.MLClient`
(`evaluate(request) -> MLEvaluateResponse`, `health()`, `aclose()`) and register it in
`app/ml/__init__.py::build_ml_client`. Nothing else changes.
