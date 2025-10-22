from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core import get_db_session


router = APIRouter(prefix="/data/sources")


@router.post("/{data_source_id}", summary="Connect to external data source")
def create_datasource(db: Session = Depends(get_db_session)):
    """
    Connect application to an external datasource in order to ingest data from
    """

@router.get("/", summary="Get connected data sources")
def get_datsources(db: Session = Depends(get_db_session)):
    """
    Retrieve data sources corresponding to authenticated user
    """

    try:
        #TODO: Use DataSourceService object to retrieve data sources 
        print('Getting datasources!')

    except Exception as e:
        print("An exception occurred while retrieving data sources")
        #TODO:  raise corresponding Exception to be handled by Controlelr advice and change to logging
    
