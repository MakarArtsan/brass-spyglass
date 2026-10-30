# The Brass Spyglass — сайт-трекер фильма

Единое место производства фильма «Битва при кривом зеркале» / *The Brass Spyglass*
(1 Billion AI Film Award 2027): статусы, файлы, референсы, звук и музыка. Заменяет Excel-трекер.
Вход только через Telegram и только для участников закрытого чата команды.

ТЗ — в `The Brass Spyglass` (PDF), решения и умолчания — [DECISIONS.md](DECISIONS.md),
рабочие договорённости и команды — [CLAUDE.md](CLAUDE.md).

## Статус этапов

| Этап | Срок | Состояние |
|---|---|---|
| **0. Каркас** | 31.10.2026 | ✅ код готов и проверен локально; ⏳ деплой на Amvera — по шагам ниже |
| 1. Трекер и загрузка | 02.11.2026 | ⛔ ждёт `Krivoe_zerkalo_tracker.xlsx` (см. DECISIONS.md) |
| 2. Telegram и дашборд | 04.11.2026 | — |
| 3. Экспорт | 06.11.2026 | — |
| 4. Полировка | по времени | — |

### Этап 0 — чек-лист

- [x] Репозиторий: FastAPI + React/Vite, многоступенчатый `Dockerfile`, `amvera.yml`, диск `/data`
- [x] SQLite (WAL) + Alembic, вся схема (18 таблиц), справочники, сервисный слой с журналом `activity`
- [x] Вход через Telegram-бота с проверкой членства в закрытом чате (+ Login Widget как запасной)
- [x] Бренд: токены, шрифты, тёмная/светлая тема, раскладки ПК (сайдбар) и телефона (нижняя панель)
- [ ] Деплой на Amvera и проверка входа с настоящим ботом — нужны ваши ключи Telegram

Скриншоты: [`docs/screenshots/stage-0/`](docs/screenshots/stage-0) (ПК 1440 px и телефон 390 px).

## Запуск на Amvera

1. Создайте проект Amvera типа **Docker**, подключите этот репозиторий. `amvera.yml` уже в корне
   (`persistenceMount: /data`, `containerPort: 8000`). Диск `/data` должен быть подключён в тарифе.
2. Создайте бота у [@BotFather](https://t.me/BotFather), для запасного входа выполните `/setdomain`
   с адресом сайта.
3. На [my.telegram.org](https://my.telegram.org) → *API development tools* получите `api_id` и `api_hash`.
4. Заведите **отдельный аккаунт команды** (юзербот), добавьте его в закрытый чат и выпустите сессию:
   ```bash
   cd backend && TG_API_ID=… TG_API_HASH=… .venv/bin/python scripts/make_session.py
   ```
   Скрипт печатает `TG_SESSION=…` и список групп с их id (это `TG_CHAT_ID`).
5. В Amvera → *Переменные* задайте всё из [`.env.example`](.env.example): `TG_API_ID`, `TG_API_HASH`,
   `TG_SESSION`, `TG_BOT_TOKEN`, `TG_CHAT_ID`, `OWNER_TG_ID` (ваш Telegram id), `SESSION_SECRET`
   (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
6. Деплой. Проверка: `GET /api/health` — `status: ok`, `telegram.bot: true`, `telegram.userbot: true`.
   Затем откройте сайт → «Войти через Telegram» → Start в боте.

> Пока юзербот не подключён, войти может только владелец (`OWNER_TG_ID`).
> Приложение работает строго в одном экземпляре: SQLite и сессия Telethon не терпят двух копий.

## Локальная разработка

```bash
cd backend && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
cd ../frontend && npm ci && npm run build
cd ../backend
DATA_DIR=.data SESSION_SECRET=dev COOKIE_SECURE=false OWNER_TG_ID=<ваш tg id> .venv/bin/uvicorn app.main:app
# войти без Telegram:
DATA_DIR=.data SESSION_SECRET=dev .venv/bin/python scripts/dev_session.py --role owner   # → cookie bs_session
```

Проверки: `ruff check && pytest` в `backend/`, `npm run lint && npm run typecheck && npm run test:e2e` в `frontend/`.
Подробнее — в [CLAUDE.md](CLAUDE.md).
