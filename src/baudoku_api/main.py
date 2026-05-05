from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from baudoku_api.config import get_settings
from baudoku_api.routers import ai, health, projects, workflows


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    origins = [origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(projects.router, prefix="/v1")
    app.include_router(projects.profiles_router, prefix="/v1")
    app.include_router(projects.trades_router, prefix="/v1")
    app.include_router(workflows.router, prefix="/v1")
    app.include_router(ai.router, prefix="/v1")
    return app


app = create_app()
