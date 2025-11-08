from fastapi import APIRouter, Depends, HTTPException, status
from app.services import IngestionJobService
from sqlalchemy.orm import Session
from app.core import get_db_session
from uuid import UUID


router = APIRouter(prefix="/ingestion/jobs")


@router.post("/{data_source_id}", summary="Kick off ingestion of data from a datasource")
def create_ingestion_job(data_source_id: UUID, db: Session = Depends(get_db_session)):
    """
    Kick off ingestion job for a specific data source
    """

    try:
        svc = IngestionJobService(db)
        svc.ingest_data(data_source_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )
        



@router.get("/", summary="Retrieve all ingestion jobs")
def get_ingestion_jobs():
    """
    Retrieve ingestion jobs for authenticated user
    """
