#!/usr/bin/env bash
# Поднимает приложение целиком (API + собранный фронтенд) на чистой БД для e2e-тестов.
set -euo pipefail
cd "$(dirname "$0")/../../backend"
export DATA_DIR="${E2E_DATA_DIR:-$PWD/.e2e-data}"
export SESSION_SECRET="e2e-secret"
export COOKIE_SECURE="false"
export OWNER_TG_ID="900001"
export FRONTEND_DIR="$PWD/../frontend/dist"
rm -rf "$DATA_DIR"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${E2E_PORT:-8765}"
