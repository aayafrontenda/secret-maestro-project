# ML integration guide for the backend

The ML part is a Python package, `maestro`, in `ml/`. It has no HTTP server: the backend calls it directly from Python, or runs the CLI from another language.

## Requirements on the machine that scores

- Ollama running, with the model pulled: `ollama pull qwen3.5:4b`.
- Python 3.12. Install the package into the backend's environment:

  ```sh
  uv add --editable ../ml        # if the backend uses uv
  pip install -e ../ml           # otherwise
  ```

## Python

```python
from maestro import IngestError, LLMUnavailable, OllamaClient, parse_bytes, score_transcript

llm = OllamaClient.from_env()          # reads MAESTRO_* variables, see ml/.env.example
assert llm.health()["ok"]              # {"ok": bool, "model": str, "error"?: str}

transcripts = parse_bytes(filename, raw_bytes)   # .json .csv .xlsx .txt; raises IngestError
for transcript in transcripts:                   # one file can hold several chats
    result = score_transcript(
        transcript,
        llm,
        output_language="ru",                    # "ru" | "kk" | "en": language of the rationale text
        on_progress=lambda done, total, criterion_id: ...,   # optional, called before each criterion
    )
    payload = result.model_dump(mode="json")     # plain dict, ready for a JSON response
```

Other entry points: `parse_json_object(obj)` for already decoded JSON, `parse_text(text)` for plain text.

### Timing and concurrency

- Measured on an RTX 4070 Laptop (8 GB) with `qwen3.5:4b`: 13–17 model calls and 10–15 seconds per chat once the model is loaded. The first call after Ollama starts loads the model and took about 70 seconds. Ten chats take about 2–3 minutes in total, longer than a typical proxy timeout (Cloudflare closes requests after about 100 seconds), so run scoring as a background job and let the frontend poll, or stream progress.
- `score_transcript` is synchronous and blocking. Run one at a time per GPU; parallel calls only queue inside Ollama.
- `OllamaClient` is safe to reuse across chats.

### Errors

| Error | Meaning | Suggested response |
|---|---|---|
| `IngestError` | The file cannot be read as a chat: unknown format, unknown role, no messages | 422 with the message |
| `LLMUnavailable` | Ollama is down or the model is missing | 503, check `llm.health()` |

If the model gives unusable answers for one criterion, scoring does not fail. That criterion gets `status: "failed"`, the result gets `status: "partial"`, and `final_score` is `null`. No score is made up.

## CLI, for a backend in another language

```sh
uv run --directory ml maestro score /path/chat.json --json --lang ru
```

Prints one JSON result per chat per line on stdout. Exit codes: 0 success, 1 unreadable input, 2 model unavailable.

## Accepted input

JSON can be one chat, a list of chats, `{"chats": [...]}`, or a flat list of message rows with a `chat_id` field. CSV and XLSX are message rows. Field names are matched case-insensitively from these synonyms:

| Meaning | Accepted names |
|---|---|
| role | `role`, `sender`, `author`, `from`, `speaker`, `type` |
| text | `text`, `message`, `content`, `body` |
| time | `timestamp`, `time`, `created_at`, `date`, `datetime` |
| chat ID | `chat_id`, `dialog_id`, `conversation_id`, top-level `id` |
| attachments | `attachments`, `attachment`, `files`, `file` |

Role values: `client`/`customer`/`user`/`клиент`, `operator`/`agent`/`support`/`оператор`, `system`/`система`, `bot`/`бот`, plus a few more. An unknown role is an error, not a guess.

Plain text: one message per line, `[10:01:05] Оператор: text` or `Client: text`. Lines without a known role continue the previous message.

```json
{
  "chat_id": "123",
  "messages": [
    {"role": "client", "time": "2026-11-01T10:00:00", "text": "Добрый день! Какая комиссия?"},
    {"role": "operator", "time": "2026-11-01T10:01:10", "text": "Здравствуйте! Меня зовут Алина..."}
  ]
}
```

## Result

`uv run maestro schema` prints the full JSON schema. The main fields:

```jsonc
{
  "chat_id": "123",
  "status": "scored",                 // "partial" if any criterion failed
  "final_score": 87.33,               // 0-100, null if it cannot be computed
  "gross_violation": {                // criterion 08, null if not scored
    "flag": false, "insult": false, "off_company_offer": false, "confidential_disclosure": false
  },
  "criteria": [
    {
      "criterion_id": "01",
      "name": "Establishing contact",
      "weight": 10,
      "status": "scored",
      "answer": "yes",                // "yes" | "no" | "na" | scale level (04: 0/5/10/15/20, 06: 0/4/7/10)
      "raw_points": 10.0,             // before N/A redistribution
      "points": 13.33,                // share of the final 100
      "rationale": "Поздоровался в первом ответе: да; представился в первом ответе: да; ответил на языке клиента: да.",
      "evidence": [{"message_id": "M2", "role": "operator", "quote": "Здравствуйте! Меня зовут Алина..."}],
      "expected_at": null,            // message where a missed action was expected
      "facts": {"greeted": true, "introduced": true, "client_language_used": true},
      "error": null,
      "attempts": [ /* trace of model calls: probe, prompt hash, raw answer, tokens, time */ ]
    }
  ],
  "output_language": "ru",
  "model": "qwen3.5:4b",
  "llm_calls": 14,
  "duration_ms": 21000
}
```

Display notes:
- Criterion names in `name` are English. Use your own translations in the UI, keyed by `criterion_id`.
- Show `rationale` and `evidence` for each criterion: the checklist requires the answer, a short justification and a supporting fragment.
- `evidence[].message_id` matches `M1…Mn`, the position of the message in the chat after empty messages are dropped.
- `attempts` is for debugging and for showing that the chat was really analysed. It can be large; hide it by default.
