from fastapi import FastAPI
from .core import (settings, init_db, engine)
from contextlib import asynccontextmanager
from .routers import app_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Async context manager for initializing necessary models and then 
    disposing of DB engine once app's shutdown
    """
    init_db() 
    yield
    engine.dispose()


def create_app() -> FastAPI:
    """
    create FastAPI application instance and configure settings
    """

    # TODO: Setup logging 

    app = FastAPI(
        title=settings.PROJECT_NAME,
        lifespan=lifespan
    )

    #TODO: Add Middleware For CORS 

    #TODO: Add Exception Handlers For 

    #TODO: Add JWT Request Filter 

    app.include_router(app_router)

    return app