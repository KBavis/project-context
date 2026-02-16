from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core import (
    settings, 
    init_db, 
    sync_engine, 
    setup_logging, 
    async_engine
)
from contextlib import asynccontextmanager
from .api.routers import app_router
    


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Async context manager for initializing necessary models and then
    disposing of DB engine once app's shutdown
    """
    init_db()
    yield
    sync_engine.dispose()
    await async_engine.dispose()


def create_app() -> FastAPI:
    """
    create FastAPI application instance and configure settings
    """

    setup_logging()

    app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

    # Add Middleware For CORS
    origins = [ #TODO: make these configs 
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # TODO: Add Exception Handlers For

    # TODO: Add JWT Request Filter

    app.include_router(app_router)

    return app

