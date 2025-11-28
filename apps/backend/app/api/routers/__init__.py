from fastapi import APIRouter

from .data_source import router as data_source_router
from .ingestion_job import router as ingestion_joh_router
from .project import router as project_router
from .conversation import router as conversation_router
from .chroma import router as chroma_router

app_router = APIRouter(prefix="/api")
app_router.include_router(data_source_router)
app_router.include_router(ingestion_joh_router)
app_router.include_router(project_router)
app_router.include_router(conversation_router)
app_router.include_router(chroma_router)

__all__ = ["app_router"]
