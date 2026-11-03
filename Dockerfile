# Один контейнер на Amvera: FastAPI отдаёт и API, и собранный React. База и файлы — на диске /data.

# Базовые образы можно подменить (например, зеркалом при лимитах Docker Hub):
#   docker build --build-arg NODE_IMAGE=... --build-arg PYTHON_IMAGE=... .
ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.12-slim

# --- 1. Сборка фронтенда ---------------------------------------------------------------
FROM ${NODE_IMAGE} AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. mozjpeg: кодировщик JPEG для сжатия картинок при загрузке --------------------
# Статическая сборка одного `cjpeg`: в итоговый образ попадает только он. Сборка не должна ронять
# весь образ: если она не удалась, каталог остаётся пустым, и JPEG сжимается кодировщиком Pillow
# (те же настройки, чуть хуже сжатие); что именно работает — видно в /api/health.
FROM ${PYTHON_IMAGE} AS mozjpeg
ARG MOZJPEG_VERSION=4.1.5
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake nasm curl ca-certificates libpng-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/mozjpeg/bin \
    && ( curl -fsSL "https://github.com/mozilla/mozjpeg/archive/refs/tags/v${MOZJPEG_VERSION}.tar.gz" | tar -xz -C /tmp \
         && cmake -S "/tmp/mozjpeg-${MOZJPEG_VERSION}" -B /tmp/mozjpeg-build \
              -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/mozjpeg \
              -DENABLE_SHARED=FALSE -DPNG_SUPPORTED=FALSE \
         && cmake --build /tmp/mozjpeg-build -j"$(nproc)" \
         && cmake --install /tmp/mozjpeg-build ) \
    || echo "mozjpeg не собрался: JPEG будет сжиматься кодировщиком Pillow"

# --- 3. Итоговый образ: Python + ffmpeg + pngquant -------------------------------------
FROM ${PYTHON_IMAGE}
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    FRONTEND_DIR=/app/static

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core pngquant \
    && rm -rf /var/lib/apt/lists/*

# JPEG для сжатия картинок (путь по умолчанию — CJPEG_BIN в config.py)
COPY --from=mozjpeg /opt/mozjpeg/bin/ /opt/mozjpeg/bin/

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY backend/seed ./seed
COPY --from=web /web/dist ./static

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# Миграции Alembic применяются при старте приложения (lifespan). Ровно один процесс:
# SQLite и сессия Telethon не терпят двух копий.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
