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
.venv/bin/alembic check                                            # модели == миграции (БД должна быть на head)
# Импорт Excel-трекера (идемпотентно, по кодам). Рабочие поля и порядок существующих записей не трогает.
DATA_DIR=.data SESSION_SECRET=dev .venv/bin/python scripts/import_xlsx.py seed/Krivoe_zerkalo_tracker.xlsx --dry-run
#   без --dry-run — записать; --overwrite-work-fields — перезаписать статус/приоритет/срок/комментарий из Excel
# На пустой БД файл backend/seed/Krivoe_zerkalo_tracker.xlsx подгружается сам при старте (SEED_XLSX="" — отключить).

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
  metrics.py                вычисляемое: таймкоды сцен/шотов, суммы, проверки согласованности (с тестами)
  xlsx_reader.py            чтение Excel-трекера по заголовкам колонок → Bundle (без записи в БД)
  services/                 ЕДИНСТВЕННОЕ место записи в БД; каждое изменение пишет `activity`
    core.py                 общие операции: создание/правка/удаление/смена статуса, журнал
    importing.py, seed.py   запись Bundle из Excel; автоимпорт сида на пустой БД
    ordering.py, links.py   порядок сцен/шотов; привязки шот↔ассет и файл↔карточка
    files.py, jobs.py       файлы (дубли по sha256, метаданные) и очередь фоновых задач
  uploads.py                загрузка кусками с докачкой: состояние на диске (/data/cache/uploads)
  media.py, worker.py       ffprobe/ffmpeg/Pillow: превью, прокси H.264 720p, волна; исполнитель очереди
  signing.py                подписанные ссылки на файлы (TTL 1 ч)
  auth/                     вход: токены, бот и юзербот (Telethon), сессия-cookie, Login Widget
  api/                      роутеры FastAPI: entities.py (сущности), files.py (загрузка/раздача), serialize.py
  main.py                   lifespan: миграции → проект → сид → Telegram → воркер; раздача React
backend/seed/               Krivoe_zerkalo_tracker.xlsx — стартовые данные
backend/scripts/            import_xlsx.py, dev_session.py, make_session.py
backend/alembic/            миграции (применяются при старте приложения)
backend/tests/              pytest; test_architecture.py следит, что записей в обход services нет
frontend/src/
  brand.ts                  цвета, шрифты, тексты бренда — единственный источник токенов
  ru.ts                     ВСЕ строки интерфейса
  lib/                      types, queries (TanStack Query + оптимистичные обновления), uploader, format, toast
  hooks/                    usePerms (только прячет кнопки — права проверяет сервер), usePanelParam
  components/               StatusPill, CardPanel, Comments, History, Uploads, … ; media/ — плееры и просмотрщик
  pages/                    Shots, Scenes, SceneDetail, Assets, Setups, Sound, Tasks, Journal (lazy-маршруты)
frontend/e2e/               Playwright (desktop 1440 + phone 390); fixtures.ts, screenshots.mjs
```

## Договорённости

- **Запись в БД только через `app/services`.** Права проверяются в сервисе, не в роутере. Автор
  (`created_by`/`uploaded_by`) ставится из сессии и не принимается от клиента.
- **Вычисляемое не хранится** (таймкоды сцен, суммы, % готовности, доля Seedance, активность) —
  считается в `metrics.py` с тестами. Вырезанные (`cut`) сцены и шоты времени не занимают.
- **Справочники** — константы в `constants.py` + CHECK-ограничения; значения сверены с листом
  «Справочник» Excel (метки Excel — в `*_EXCEL_LABELS`, нужны только импорту). Новое значение =
  константа + миграция CHECK (миграция не импортирует код приложения).
- **Импорт идемпотентен** по кодам (`01.03`, `CH-01`, `T-05`). Повторный запуск не затирает то, что
  команда уже поменяла на сайте: рабочие поля и `order` существующих записей остаются.
- **Файлы**: оригиналы не меняются, превью/прокси лежат отдельно; отдаются только залогиненным,
  по подписанным ссылкам, с `Range`. Автор (`uploaded_by`) — из сессии. Дубль определяется по
  sha256 (сервер отвечает 409, клиент может повторить с `force`). «Команда» не удаляет чужой файл —
  проверка в сервисе, а не в роутере, и на неё есть тест.
- **Загрузка**: свой протокол докачки (`POST /api/uploads` → `PATCH` с `Upload-Offset` → `complete`),
  кусок ≤ 16 МБ (`UPLOAD_CHUNK_MB`), файл ≤ 4 ГБ. После перезапуска незавершённые загрузки продолжаются.
- **Фоновые задачи** — таблица `job` в той же БД, исполнитель `worker.py` (≤ 2 ffmpeg одновременно);
  «зависшие» задачи после перезапуска возвращаются в очередь.
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
