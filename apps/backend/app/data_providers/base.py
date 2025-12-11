from uuid import UUID

from app.models.data_source import DataSource
from app.services.file import FileService
from app.core import get_async_session_maker

from sqlalchemy.ext.asyncio import AsyncSession
from abc import abstractmethod, ABC
from typing import Type
import asyncio
import logging
import threading

logger = logging.getLogger(__name__)

class DataProvider(ABC):

    def __init__(self, data_source: DataSource, job_pk: UUID, url: str = "", db_session: AsyncSession = None):
        self.data_source = data_source
        self.job_pk = job_pk
        self.url = url
        self.request_headers = self._get_request_headers()
        self.file_service = FileService(db_session=db_session)
    

    @classmethod
    async def run_ingestion(provider_class: Type, data_source: DataSource, job_pk: UUID):

        # create async DB session for data retrieval 
        session_maker = get_async_session_maker()
        
        async with session_maker() as session:
            try:

                # instantiate concrete provider
                provider_instance = provider_class(
                    data_source=data_source, 
                    url=data_source.url, 
                    job_pk=job_pk,
                    db_session=session
                )

                logger.info(f"Ingesting data from DataProvider={provider_class} for IngestionJob={job_pk}")
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
    def _get_request_headers(self):
        pass
