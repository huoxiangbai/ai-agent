# Reactor Python backend

This service is the incremental Python migration target for the Java backend. It runs beside the Java service and does not own public business routes until their contract tests and migration gates pass.

## Local commands

```bash
uv sync
uv run uvicorn reactor_backend.main:app --host 0.0.0.0 --port 8200
uv run pytest -m "not integration"
uv run ruff check .
uv run mypy src
```

Configuration uses environment variables prefixed with `REACTOR_PY_`. The MySQL password and optional full database URL are treated as secrets and are never emitted by application logs.
