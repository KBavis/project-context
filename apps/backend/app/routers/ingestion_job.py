from fastapi import APIRouter, Depends, HTTPException, status
from app.services import IngestionJobService, FileService
from sqlalchemy.orm import Session
from app.core import get_db_session, ChromaClientManager
from uuid import UUID


router = APIRouter(prefix="/ingestion/jobs")
chroma_manager = ChromaClientManager()


@router.post(
    "/{data_source_id}", summary="Kick off ingestion of data from a datasource"
)
def create_ingestion_job(data_source_id: UUID, db: Session = Depends(get_db_session)):
    """
    Kick off ingestion job for a specific data source
    """

    try:
        file_svc = FileService(db) # TODO: Setup services/dependencies.py for Dependnecy Injection
        svc = IngestionJobService(db=db, file_service=file_svc, chroma_client_manager=chroma_manager)
        return svc.run_ingestion_job(data_source_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.post(
    "/{data_source_id}/{project_id}",
    summary="Kick off ingestion of data from a datasource for a specific Project",
)
def create_ingestion_job(
    data_source_id: UUID, project_id: UUID, db: Session = Depends(get_db_session)
):
    """
    Kick off ingestion job for a datasource for only data corresponding to specified Project
    """

    try:
        file_svc = FileService(db) # TODO: Setup services/dependencies.py for Dependnecy Injection
        svc = IngestionJobService(db=db, file_service=file_svc, chroma_client_manager=chroma_manager)
        return svc.run_ingestion_job(data_source_id, project_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.get("/", summary="Retrieve all ingestion jobs")
def get_ingestion_jobs():
    """
    Retrieve ingestion jobs for authenticated user
    """
