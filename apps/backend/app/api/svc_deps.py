from __future__ import annotations
from app.services import (
    ChromaService,
    DataSourceService,
    IngestionJobService,
    ProjectService, 
    FileService,
    RecordLockService, 
    ConversationService,
    MessageService,
    ExecutionTokenUsageService,
    ChunkRetrievalService,
    ChunkInsertionService,
    MCPService,
    AgentService,
    DiffService,
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
        async_db=async_db,
        chroma_manager=chroma_mnger,
        db=db, 
    )


def get_data_source_svc(
        db: Session = Depends(get_sync_db_session),
        async_db: AsyncSession = Depends(get_async_db_session),
        chroma_svc: ChromaService = Depends(get_chroma_svc)
):
    """
    Setup DataSourceService dependency

    Args:
        db (Session): current DB session
    """
    
    return DataSourceService(db=db, async_db=async_db, chroma_svc=chroma_svc)


def get_mcp_svc(
        db: Session = Depends(get_sync_db_session),
        async_db: AsyncSession = Depends(get_async_db_session)
):
    """
    Setup MCPService dependency

    Args:
        db (Session): current DB session
    """
    
    return MCPService(db=db, async_db=async_db)

##########################
# Async Service Dependencies 
###########################


def get_async_record_lock_svc():
    """
    Setup async RecordLockService dependency 

    Args:   
        db (AsyncSession): async DB session
    """

    return RecordLockService()
    

def get_async_diff_svc(
    db: AsyncSession = Depends(get_async_db_session),
    data_source_svc: DataSourceService = Depends(get_data_source_svc),
    record_lock_svc: RecordLockService = Depends(get_async_record_lock_svc)
):
    """
    Setup DiffService dependency.
    """
    return DiffService(
        async_db=db, 
        data_source_svc=data_source_svc, 
        record_lock_svc=record_lock_svc
    )


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
        chroma_svc: ChromaService = Depends(get_chroma_svc),
        data_source_svc: DataSourceService = Depends(get_data_source_svc)
):
    """
    Setup async ChunkRetrievalService dependency 
    """
    return ChunkRetrievalService(db=db, chroma_svc=chroma_svc, data_source_svc=data_source_svc)



def get_async_agent_svc(
    db: AsyncSession = Depends(get_async_db_session),
    mcp_svc: MCPService = Depends(get_mcp_svc),
    data_source_svc: DataSourceService = Depends(get_data_source_svc),
    chunk_retrieval_svc: ChunkRetrievalService = Depends(get_async_chunk_retrieval_svc),
    diff_svc: DiffService = Depends(get_async_diff_svc)
):
    """
    Setup async AgentService dependency

    Args:
        db (AsyncSession): async DB session
        mcp_svc (MCPService): async mcp service dependency
        data_source_svc (DataSourceService): async data source service dependency
        chunk_retrieval_svc (ChunkRetrievalService): async chunk retrieval service dependency
    """
    return AgentService(
        db=db, 
        mcp_svc=mcp_svc, 
        data_source_svc=data_source_svc,
        chunk_retrieval_svc=chunk_retrieval_svc,
        diff_svc=diff_svc
    )



def get_async_ingestion_job_svc(
        db: AsyncSession = Depends(get_async_db_session),
        record_lock_svc: RecordLockService = Depends(get_async_record_lock_svc),
        data_source_svc: DataSourceService = Depends(get_data_source_svc)
):
    """
    Setup async IngestionJobService dependency.

    NOTE: Ingestion jobs that run in background require FileSvc, ChunkInsertionSvc, and ChromaSvc, which 
    must all be created using a background-task scoped async session. Thus, those are not injected here.

    Args:
        db (AsyncSession): async db session
        record_lock_svc (RecordLockService): record lock service dependency
        data_source_svc (DataSourceService): async data source service dependency
    """
    return IngestionJobService(
        db=db, 
        record_lock_svc=record_lock_svc,
        data_source_svc=data_source_svc
    )




def get_project_svc(
        db: Session = Depends(get_sync_db_session),
        async_db: AsyncSession = Depends(get_async_db_session),
        diff_svc: DiffService = Depends(get_async_diff_svc),
        ingestion_job_svc: IngestionJobService = Depends(get_async_ingestion_job_svc),
):
    """
    Setup ProjectService dependency

    Args:
        db (Session): current DB session
    """

    return ProjectService(
        db=db, 
        async_db=async_db, 
        diff_svc=diff_svc, 
        ingestion_job_svc=ingestion_job_svc
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

def get_async_execution_token_usage_svc(
    db: AsyncSession = Depends(get_async_db_session)
):
    """
    Setup async ExecutionTokenUsageService dependency 

    Args:   
        db (AsyncSession): async DB session
    """

    return ExecutionTokenUsageService(db=db)


def get_async_message_svc(
        db: AsyncSession = Depends(get_async_db_session),
        conversation_svc: ConversationService = Depends(get_async_conversation_svc),
        agent_svc: AgentService = Depends(get_async_agent_svc),
        execution_token_usage_svc: ExecutionTokenUsageService = Depends(get_async_execution_token_usage_svc),
        project_svc: ProjectService = Depends(get_project_svc),
):
    """
    Setup async MessageService dependency 

    Args:
        db (AsyncSession): async DB session
        conversation_svc (ConversationService): async conversation service dependency
        agent_svc (AgentService): async agent service dependency
        execution_token_usage_svc (ExecutionTokenUsageService): async execution token usage service dependency
        project_svc (ProjectService): project service dependency (owns readiness validation)
    """

    return MessageService(
        db=db, 
        conversation_svc=conversation_svc, 
        agent_svc=agent_svc, 
        execution_token_usage_svc=execution_token_usage_svc, 
        project_svc=project_svc,
    )