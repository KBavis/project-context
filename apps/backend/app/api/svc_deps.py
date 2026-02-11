from app.pydantic import CreateConversationRequest
from app.services import (
    ChromaService,
    DataSourceService,
    IngestionJobService,
    ProjectService, 
    FileService,
    RecordLockService, 
    QueryService, 
    RankingService,
    QuestionAndAnswerService,
    ConversationService,
    MessageService
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

def get_chroma_svc(
        db: Session = Depends(get_sync_db_session),
        chroma_mnger: ChromaClientManager = Depends(get_chroma_manager)
    ):
    """
    Setup ChromaService dependency 

    Args:
        db (Session): current DB session
    """
    
    return ChromaService(
        db=db, 
        chroma_manager=chroma_mnger
    )

def get_project_svc(
        db: Session = Depends(get_sync_db_session),
        chroma_svc: ChromaService= Depends(get_chroma_svc)
):
    """
    Setup ProjectService dependency

    Args:
        db (Session): current DB session
    """

    return ProjectService(db=db, chroma_svc=chroma_svc)



def get_data_source_svc(
        db: Session = Depends(get_sync_db_session)
):
    """
    Setup DataSourceService dependency

    Args:
        db (Session): current DB session
    """
    
    return DataSourceService(db=db)




##########################
# Async Service Dependencies 
###########################


def get_async_q_and_a_svc(
        db: AsyncSession = Depends(get_async_db_session)
):
    """
    Setup QAndAService dependency

    Args:
        db (AsyncSession): current DB session
    """

    return QuestionAndAnswerService(db=db)


def get_async_ranking_svc(
        db: AsyncSession = Depends(get_async_db_session)
):
    """
    Setup async RankingService dependency 

    Args:
        db (AsyncSession): async DB session
    """

    return RankingService(db=db)


def get_async_query_svc(
        db: AsyncSession = Depends(get_async_db_session),
        chroma_svc: ChromaService = Depends(get_chroma_svc),
        ranking_svc: RankingService = Depends(get_async_ranking_svc),
        q_and_a_svc: QuestionAndAnswerService = Depends(get_async_q_and_a_svc)
):
    """
    Setup async QueryService dependency 

    Args:
        db (AsyncSession): async DB session
        chroma_svc (ChromaService): async chroma service dependency
    """

    return QueryService(db=db, chroma_svc=chroma_svc, ranking_svc=ranking_svc, q_and_a_svc=q_and_a_svc)

def get_async_file_svc(
        db: AsyncSession = Depends(get_async_db_session),
        chroma_svc: ChromaService = Depends(get_chroma_svc)
):
    """
    Setup async FileService dependency

    Args:
        db (AsyncSession): async DB session
        chroma_svc (ChromaService): async chroma service dependency
    """

    return FileService(db_session=db, chroma_svc=chroma_svc)

def get_async_record_lock_svc():
    """
    Setup async RecordLockService dependency 

    Args:   
        db (AsyncSession): async DB session
    """

    return RecordLockService()


def get_async_ingestion_job_svc(
        db: AsyncSession = Depends(get_async_db_session),
        chroma_svc: ChromaService = Depends(get_chroma_svc),
        record_lock_svc: RecordLockService = Depends(get_async_record_lock_svc)
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
        chroma_svc=chroma_svc,
        record_lock_svc=record_lock_svc
    )