# syntax=docker/dockerfile:1
# Backend image. Production target: linux/arm64 (Orange Pi 5+ / RK3588).
# It also builds for amd64 so the mock engine runs on a dev PC.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

# libgomp1: OpenMP runtime required by librkllmrt.so
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    RKLLM_LIB_PATH=/usr/lib/librkllmrt.so \
    MODELS_DIR=/models \
    BACKEND_PORT=8000

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# RKLLM runtime 1.2.0 (vendored from rkllm_api_bundle/lib)
COPY lib/librkllmrt.so /usr/lib/librkllmrt.so

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh && mkdir -p /models

# listens on $BACKEND_PORT (default 8000)
EXPOSE 8000
ENTRYPOINT ["/docker-entrypoint.sh"]
