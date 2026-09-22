FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY backend-python/pyproject.toml backend-python/uv.lock backend-python/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend-python/src ./src
RUN uv sync --frozen --no-dev

EXPOSE 8200

CMD ["uvicorn", "reactor_backend.main:app", "--host", "0.0.0.0", "--port", "8200"]
