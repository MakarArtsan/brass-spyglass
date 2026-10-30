# CLAUDE.md — The Brass Spyglass

Сайт-трекер производства фильма «Битва при кривом зеркале» / The Brass Spyglass
(1 Billion AI Film Award 2027). Источник правды — ТЗ; принятые решения и умолчания — в
[DECISIONS.md](DECISIONS.md). Язык интерфейса — русский, контент фильма (реплики, субтитры) — английский.

## Как работаем

- Короткими этапами (0 → 4), каждый заканчивается деплоем на Amvera. Следующий этап не начинаем,
  пока не закрыты галочки предыдущего.
- **Не добавлять функции сверх ТЗ.** Не успеваем — переносим на следующий этап и пишем об этом.
- На открытый вопрос без ответа берём умолчание из ТЗ и записываем в `DECISIONS.md`.
- Коммит после каждой законченной фичи.
- После этапа: `ruff`, `pytest`, `eslint`, `tsc`, Playwright и скриншоты ключевых экранов
  на 1440 px и 390 px (`docs/screenshots/stage-N/`).

## Команды

```bash
# Бэкенд (Python 3.12)
cd backend
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q
DATA_DIR=.data SESSION_SECRET=dev COOKIE_SECURE=false OWNER_TG_ID=<tg_id> \
  .venv/bin/uvicorn app.main:app --reload          # http://localhost:8000
.venv/bin/alembic revision --autogenerate -m "..." --rev-id 000N   # новая миграция
.venv/bin/alembic check                                            # модели == миграции

# Фронтенд (Node 22)
cd frontend
npm ci
npm run dev            # Vite на :5173, /api проксируется на :8000
npm run build          # tsc --noEmit + vite build → frontend/dist (его отдаёт бэкенд)
npm run lint && npm run typecheck
npm run test:e2e       # Playwright: сам поднимает бэкенд на :8765 с чистой БД (нужен npm run build)
npm run shots -- ../docs/screenshots/stage-0   # скриншоты (нужен запущенный сервер на :8765)

# Вход без Telegram для разработки и тестов
cd backend && DATA_DIR=.data SESSION_SECRET=dev .venv/bin/python scripts/dev_session.py --role owner
# печатает значение cookie bs_session
```

## Структура

```
Dockerfile, amvera.yml      один контейнер на Amvera, диск /data
backend/app/
  constants.py              справочники (статусы, этапы, крупности…) — от них строятся CHECK в БД
  models.py                 вся схема данных (SQLAlchemy 2)
  db.py                     SQLite в режиме WAL, UTCDateTime (наивное время запрещено)
  permissions.py            матрица ролей из ТЗ — единственное место
  services/                 ЕДИНСТВЕННОЕ место записи в БД; каждое изменение пишет `activity`
  auth/                     вход: токены, бот и юзербот (Telethon), сессия-cookie, Login Widget
  api/                      роутеры FastAPI
  main.py                   lifespan: миграции → проект → Telegram; раздача React
backend/alembic/            миграции (применяются при старте приложения)
backend/tests/              pytest; test_architecture.py следит, что записей в обход services нет
frontend/src/
  brand.ts                  цвета, шрифты, тексты бренда — единственный источник токенов
  ru.ts                     ВСЕ строки интерфейса
  components/, pages/, hooks/, nav.ts
frontend/e2e/               Playwright (desktop 1440 + phone 390)
```

## Договорённости

- **Запись в БД только через `app/services`.** Права проверяются в сервисе, не в роутере. Автор
  (`created_by`/`uploaded_by`) ставится из сессии и не принимается от клиента.
- **Вычисляемое не хранится** (таймкоды сцен, суммы, % готовности, доля Seedance, активность) —
  считается в `metrics.py` (появится на этапе 1–2) с тестами.
- **Справочники** — константы в `constants.py` + CHECK-ограничения. Значения помеченные `TBD`
  сверить с Excel-трекером на этапе 1.
- **Удаление мягкое** (`deleted_at`), корзина 30 дней, восстанавливает владелец.
- **Один экземпляр приложения**: SQLite и сессия Telethon не терпят двух копий. `--workers 1`.
- **Время**: в БД UTC, в API ISO с поясом, отображение — по Дубаю для дедлайнов.
- **Фронтенд**: никаких захардкоженных цветов/строк в компонентах — только токены Tailwind
  (из `brand.ts`) и `ru.ts`. Область касания ≥ 44×44 px, «только по наведению» не бывает.
  Анимации Framer Motion 150–250 мс, без «прыгающих».
- **Миграции не импортируют код приложения** (см. `0001`): типы только из `sqlalchemy`.
- Эндпоинты записи защищены `same_origin` (проверка Origin поверх SameSite=Lax).

## Переменные окружения

См. `.env.example`. Секреты (`TG_*`, `SESSION_SECRET`) — только в переменных Amvera.
