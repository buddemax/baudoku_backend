# baudoku_backend

FastAPI backend for the Baudoku field documentation app.

## Local Development

```bash
uv sync --extra dev
uv run python -m uvicorn baudoku_api.main:app --reload --app-dir src --host 0.0.0.0 --port 8000
```

## Checks

```bash
uv run pytest
uv run ruff check src tests
```

Required runtime configuration is documented in `.env.example`.
