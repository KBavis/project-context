from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core import get_db_session
from app.services import DataSourceService
from app.pydantic import DataSourceRequest
from uuid import UUID


router = APIRouter(prefix="/data/sources")


@router.post("/", summary="Connect to external data source")
def create_datasource(
    data_source: DataSourceRequest, db: Session = Depends(get_db_session)
):
    """
    Connect application to an external datasource in order to ingest data from
    """

    try:
        svc = DataSourceService(db)
        return svc.create_data_source(data_source)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.get("/{project_id}", summary="Get connected data sources")
def get_project_data_sources(project_id: UUID, db: Session = Depends(get_db_session)):
    """
    Retrieve data sources corresponding to a Project that the authenticated user is able to view
    """

    try:
        svc = DataSourceService(db)
        return svc.get_project_data_sources(project_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
