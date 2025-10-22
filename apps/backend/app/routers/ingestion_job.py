from fastapi import APIRouter


router = APIRouter(prefix="/ingestion/jobs")


@router.post("/{data_source_id}", summary="Kick off ingestion of data from a datasource")
def create_ingestion_job():
    """
    Kick off ingestion job for a specific data source
    """


@router.get("/", summary="Retrieve all ingestion jobs")
def get_ingestion_jobs():
    """
    Retrieve ingestion jobs for authenticated user
    """
