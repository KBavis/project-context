from uuid import UUID

from app.models.data_source import DataSource
from app.services.file import FileService
from app.core import get_async_session_maker
from app.services.chroma import ChromaService

from sqlalchemy.ext.asyncio import AsyncSession
from abc import abstractmethod, ABC
from typing import Type
import logging

logger = logging.getLogger(__name__)

class DataProvider(ABC):

    def __init__(self, data_source: DataSource, job_pk: UUID, chroma_svc: ChromaService, url: str = "", db_session: AsyncSession = None):
        self.data_source = data_source
        self.job_pk = job_pk
        self.url = url
        self.request_headers = self._get_request_headers()
        self.file_service = FileService(db_session=db_session, chroma_svc=chroma_svc)
    

    @classmethod
    async def run_ingestion(cls: Type, data_source: DataSource, job_pk: UUID, chroma_svc: ChromaService):

        # create async DB session for data retrieval 
        session_maker = get_async_session_maker()
        
        async with session_maker() as session:
            try:

                # instantiate concrete provider
                provider_instance = cls(
                    data_source=data_source, 
                    url=data_source.url, 
                    job_pk=job_pk,
                    db_session=session,
                    chroma_svc=chroma_svc 
                )

                logger.info(f"Ingesting data from DataProvider={cls} for IngestionJob={job_pk}")
                await provider_instance.ingest_data() 

                await session.commit() 
            except Exception as e:
                logger.error(f"Failure occurred while ingesting data from DataSource = {str(e)}")
                await session.rollback() 
                raise 


    @abstractmethod
    async def ingest_data(self):
        pass

    @abstractmethod
    async def _download_file(self, url: str, headers: dict = {}):
        pass

    @abstractmethod
    def _validate_url(self, url: str):
        pass

    @abstractmethod
    def _get_request_headers(self) -> dict[str, str] | None:
        """Get request headers for API calls. Returns None if no auth is needed."""
        pass
