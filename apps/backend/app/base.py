from fastapi import FastAPI
from .core import settings



def create_app() -> FastAPI:
    """
    create FastAPI application instance and configure settings
    """

    # TODO: Setup logging 

    app = FastAPI(
        title=settings.PROJECT_NAME
    )

    #TODO: Add Middleware For CORS & Exception Handlers 


    return app