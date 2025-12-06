from app.services import (
    ChromaService,
    ConversationService,
    DataSourceService,
    IngestionJobService,
    ProjectService, 
    FileService
)

from app.core import (
    get_sync_db_session,
    get_async_db_session
)
from app.core import ChromaClientManager

from fastapi import Depends
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import (
    AsyncSession
)
from functools import lru_cache


# singleton dependencies for services 
@lru_cache()
def get_chroma_manager() -> ChromaClientManager:
    """
    Setup singleton dependency for ChromaClientManager 
    """

    return ChromaClientManager()

##########################
# Sync Service Dependencies 
###########################


def get_project_svc(
        db: Session = Depends(get_sync_db_session),
        chroma_mnger: ChromaClientManager = Depends(get_chroma_manager)
):
    """
    Setup ProjectService dependency

    Args:
        db (Session): current DB session
    """

    return ProjectService(db=db, chroma_manager=chroma_mnger)


def get_chroma_svc(
        db: Session = Depends(get_sync_db_session),
        chroma_mnger: ChromaClientManager = Depends(get_chroma_manager),
        svc: ProjectService = Depends(get_project_svc)
    ):
    """
    Setup ChromaService dependency 

    Args:
        db (Session): current DB session
    """
    
    return ChromaService(db=db, chroma_manager=chroma_mnger, project_svc=svc)


def get_data_source_svc(
        db: Session = Depends(get_sync_db_session)
):
    """
    Setup DataSourceService dependency

    Args:
        db (Session): current DB session
    """
    
    return DataSourceService(db=db)

def get_conversation_svc(
        db: Session = Depends(get_sync_db_session)
):
    """
    Setup ConversationService dependency

    Args:
        db (Session): current DB session
    """

    return ConversationService(db=db)


def get_file_svc(
        db: Session = Depends(get_sync_db_session)
):
    """
    Setup FileService dependency

    Args:
        db (Session): current DB session
    """

    return FileService(db=db)


def get_ingestion_job_svc(
        db: Session = Depends(get_sync_db_session),
        file_svc: FileService = Depends(get_file_svc),
        chroma_mnger: ChromaClientManager = Depends(get_chroma_manager)
):
    """
    Setup IngestionJobService dependency

    Args:
        db (Session): current DB session
    """

    return IngestionJobService(db=db, file_service=file_svc, chroma_client_manager=chroma_mnger)


def get_project_svc(
        db: Session = Depends(get_sync_db_session),
        chroma_mnger: ChromaClientManager = Depends(get_chroma_manager)
):
    """
    Setup ProjectService dependency

    Args:
        db (Session): current DB session
    """

    return ProjectService(db=db, chroma_manager=chroma_mnger)



##########################
# Async Service Dependencies 
###########################

def get_async_file_svc(
        db: AsyncSession = Depends(get_async_db_session)
):
    """
    Setup async FileService dependency

    Args:
        db (AsyncSession): async DB session
    """

    return FileService(db=db)


def get_async_ingestion_job_svc(
        db: AsyncSession = Depends(get_async_db_session),
        file_svc: FileService = Depends(get_async_file_svc),
        chroma_mnger: ChromaClientManager = Depends(get_chroma_manager)
):
    """
    Setup async IngestionJobService dependency 

    Args:
        db (AsyncSession): async db session
        file_svc (FileService): async file service dependency
        chroma_mnger (ChromaClientManager): async chroma manager dependency
    """
    return IngestionJobService(
        db=db, 
        file_service=file_svc, 
        chroma_client_manager=chroma_mnger
    )