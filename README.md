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

## Railway Deployment

Railway should deploy this repository directly with `railway.json`. Keep the service root at
the repository root and use the default Railpack builder.

If Railway fails while installing `uv` through `mise` with a GitHub artifact attestation error,
set this service variable in Railway and redeploy:

```bash
MISE_AQUA_GITHUB_ATTESTATIONS=false
```

The repository also contains `mise.toml`, which tells Railpack to use Python 3.12 instead of
the moving Railway default. If Railway still resolves Python 3.13, add this service variable too:

```bash
RAILPACK_PYTHON_VERSION=3.12
```

Required runtime configuration is documented in `.env.example`.
