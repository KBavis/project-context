from app.services import (
    ChromaService,
    ConversationService,
    DataSourceService,
    IngestionJobService,
    ProjectService, 
    FileService
)

from app.core import get_db_session
from app.core import ChromaClientManager

from fastapi import Depends
from sqlalchemy.orm import Session
from functools import lru_cache


@lru_cache()
def get_chroma_manager() -> ChromaClientManager:
    """
    Setup singleton dependency for ChromaClientManager 
    """

    return ChromaClientManager()


def get_project_svc(
        db: Session = Depends(get_db_session),
        chroma_mnger: ChromaClientManager = Depends(get_chroma_manager)
):
    """
    Setup ProjectService dependency

    Args:
        db (Session): current DB session
    """

    return ProjectService(db=db, chroma_manager=chroma_mnger)


def get_chroma_svc(
        db: Session = Depends(get_db_session),
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
        db: Session = Depends(get_db_session)
):
    """
    Setup DataSourceService dependency

    Args:
        db (Session): current DB session
    """
    
    return DataSourceService(db=db)

def get_conversation_svc(
        db: Session = Depends(get_db_session)
):
    """
    Setup ConversationService dependency

    Args:
        db (Session): current DB session
    """

    return ConversationService(db=db)


def get_file_svc(
        db: Session = Depends(get_db_session)
):
    """
    Setup FileService dependency

    Args:
        db (Session): current DB session
    """

    return FileService(db=db)


def get_ingestion_job_svc(
        db: Session = Depends(get_db_session),
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
        db: Session = Depends(get_db_session),
        chroma_mnger: ChromaClientManager = Depends(get_chroma_manager)
):
    """
    Setup ProjectService dependency

    Args:
        db (Session): current DB session
    """

    return ProjectService(db=db, chroma_manager=chroma_mnger)