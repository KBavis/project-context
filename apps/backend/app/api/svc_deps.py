from __future__ import annotations
from app.services import (
    ChromaService,
    DataSourceService,
    IngestionJobService,
    ProjectService, 
    FileService,
    RecordLockService, 
    QueryService, 
    ConversationService,
    MessageService,
    CitationService,
    ChunkRetrievalService,
    ChunkInsertionService
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
        async_db: AsyncSession = Depends(get_async_db_session),
        chroma_mnger: ChromaClientManager = Depends(get_chroma_manager)
    ):
    """
    Setup ChromaService dependency 

    Args:
        db (Session): current DB session
    """
    
    return ChromaService(
        db=db, 
        async_db=async_db,
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

def get_async_chunk_insertion_svc(
        db: AsyncSession = Depends(get_async_db_session),
        chroma_svc: ChromaService = Depends(get_chroma_svc),
        file_svc: FileService = Depends(get_async_file_svc)
):
    """
    Setup async ChunkInsertionService dependency 
    """
    return ChunkInsertionService(
        db=db,
        chroma_svc=chroma_svc,
        file_svc=file_svc
    )

def get_async_chunk_retrieval_svc(
        db: AsyncSession = Depends(get_async_db_session),
        chroma_svc: ChromaService = Depends(get_chroma_svc)
):
    """
    Setup async ChunkRetrievalService dependency 
    """
    return ChunkRetrievalService(db=db, chroma_svc=chroma_svc)

def get_async_query_svc(
        db: AsyncSession = Depends(get_async_db_session),
        chunk_retrieval_svc: ChunkRetrievalService = Depends(get_async_chunk_retrieval_svc)
):
    """
    Setup async QueryService dependency 

    Args:
        db (AsyncSession): async DB session
    """

    return QueryService(db=db, chunk_retrieval_svc=chunk_retrieval_svc)



def get_async_record_lock_svc():
    """
    Setup async RecordLockService dependency 

    Args:   
        db (AsyncSession): async DB session
    """

    return RecordLockService()


def get_async_ingestion_job_svc(
        db: AsyncSession = Depends(get_async_db_session),
        record_lock_svc: RecordLockService = Depends(get_async_record_lock_svc),
        file_svc: FileService = Depends(get_async_file_svc),
        chunk_insertion_service: ChunkInsertionService = Depends(get_async_chunk_insertion_svc)
):
    """
    Setup async IngestionJobService dependency 

    Args:
        db (AsyncSession): async db session
        file_svc (FileService): async file service dependency
        chunk_insertion_service (ChunkInsertionService): async chunk insertion service dependency
    """
    return IngestionJobService(
        db=db, 
        record_lock_svc=record_lock_svc,
        file_svc=file_svc,
        chunk_insertion_service=chunk_insertion_service
    )




def get_async_conversation_svc(
        db: AsyncSession = Depends(get_async_db_session)
):
    """
    Setup async ConversationService dependency 

    Args:
        db (AsyncSession): async DB session
    """

    return ConversationService(db=db)


def get_async_citation_svc(
        db: AsyncSession = Depends(get_async_db_session),
        file_svc: FileService = Depends(get_async_file_svc)
):
    """
    Setup async CitationService dependency 

    Args:
        db (AsyncSession): async DB session
        file_svc (FileService): async file service dependency
    """

    return CitationService(db=db, file_svc=file_svc)


def get_async_message_svc(
        db: AsyncSession = Depends(get_async_db_session),
        conversation_svc: ConversationService = Depends(get_async_conversation_svc),
        query_svc: QueryService = Depends(get_async_query_svc),
        citation_svc: CitationService = Depends(get_async_citation_svc)
):
    """
    Setup async MessageService dependency 

    Args:
        db (AsyncSession): async DB session
        conversation_svc (ConversationService): async conversation service dependency
        query_svc (QueryService): async query service dependency
        citation_svc (CitationService): async citation service dependency
    """

    return MessageService(db=db, conversation_svc=conversation_svc, query_svc=query_svc, citation_svc=citation_svc)