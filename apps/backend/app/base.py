from fastapi import FastAPI
from .core import (settings, init_db, engine)
from typing import Generator
from contextlib import asynccontextmanager

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

    #TODO: Add Middleware For CORS & Exception Handlers 


    return app