# CQA — Conversation Quality Analytics

Прототип оценки качества диалогов операторов (хакатон Freedom Broker).

## Запуск фронта (на моках, без бэка)

```bash
cd frontend
python3 -m http.server 5173
```

- Список диалогов, импорт, массовая оценка: http://localhost:5173/#/dialogs
- Карточка диалога: http://localhost:5173/#/dialogs/p1-ru-001
- Редактор чек-листа: http://localhost:5173/#/checklists
- Очередь апелляций: http://localhost:5173/#/appeals
- Аналитика и экспорт CSV: http://localhost:5173/#/analytics
- Звонок с аудио-таймлайном: http://localhost:5173/#/dialogs/p4-ru-001
- Проверка встраивания как в Dynamics 365: http://localhost:5173/d365-test.html

Через `file://` не откроется: ES-модули и `fetch` требуют http-сервер.
Сбросить мок-данные (оценки, апелляции, версии чек-листа): кнопка «Сбросить мок-данные» на странице «Диалоги».

## Запуск с бэкендом

```bash
# 1. бэкенд (подробно — backend/README.md)
cd backend && pip install -e ".[dev]" && cp .env.example .env
python -m app.cli seed --file data/dev_dataset.json
uvicorn app.main:app --port 8000

# 2. фронт
cd frontend && python3 -m http.server 5173
```

В `frontend/js/config.js`: `USE_MOCKS: false`, `API_BASE: 'http://localhost:8000/api'`
(за Cloudflare — публичный адрес бэка). Контракт и статус реализации — `docs/API_CONTRACT.md`.

## Структура

```
frontend/
  index.html            точка входа, монтирует приложение в #cqa-root
  css/tokens.css        токены, снятые с fbroker.kz (цвета, радиусы, градиент)
  css/app.css           стили; всё под .cqa, наружу не протекает
  js/config.js          USE_MOCKS и API_BASE: единственное место для смены окружения
  js/api.js             все вызовы данных (мок или http)
  js/scoring.js         расчёт итога по правилам чек-листа
  js/mock/              мок API и мок-оценщик на регулярках
  js/ui.js              общие компоненты страниц (фильтры, поля, панель)
  js/views/dialogs.js   список, импорт по group_id, массовая оценка
  js/views/card.js      карточка: транскрипт, оценка, апелляции
  js/views/checklist.js редактор чек-листа с версиями
  js/views/appeals.js   очередь апелляций
  js/views/analytics.js аналитика и экспорт
  mocks/                DEV-набор и чек-лист по умолчанию
docs/API_CONTRACT.md    контракт фронт ↔ бэк
backend/                FastAPI-сервис оценки (см. backend/README.md)
```

## Сценарий защиты (5 минут)

1. **Диалоги:** выбрать диалог, открыть карточку.
2. **Карточка:** раскрыть критерий, по ссылке перейти к реплике, показать N/A и итог.
3. **Апелляция:** роль «Оператор» → «Оспорить оценку»; роль «Проверяющий» → решение → новый итог.
4. **Чек-лист:** заменить критерий → «Сохранить как v2» → «Диалоги» → «Переоценить по v2».
