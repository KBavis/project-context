from __future__ import annotations
import logging
from pathlib import Path
from datetime import datetime
from uuid import UUID, uuid4
import shutil
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source import DataSourceType

from app.models import DataSource, EmbedTask, ProcessingStatus, ProjectData
from app.core import settings, ChromaClientManager
from app.services.file import FileService
from app.services.chroma import ChromaService
from app.services.chunk_insertion import ChunkInsertionService
from app.data_providers.ingestible.base import IngestibleDataProvider
from app.services.diff_task import DiffTaskService
from app.core import get_current_session
from app.exceptions import TaskSkipped

if TYPE_CHECKING:
    from app.services.data_source import DataSourceService

logger = logging.getLogger(__name__)

class EmbedTaskService:

    def __init__(
            self, 
            db: AsyncSession, 
            data_source_svc: DataSourceService,
            diff_task_svc: DiffTaskService
    ):
        """
        Initialize EmbedTaskService with necessary dependencies

        Args:
            db (AsyncSession): Database session for ORM operations
            data_source_svc (DataSourceService): Service for managing data sources
        """
        self.db: AsyncSession = db
        self.data_source_svc: DataSourceService = data_source_svc
        self.diff_task_svc: DiffTaskService = diff_task_svc

    @staticmethod
    def _build_ingestion_services(
        async_session: AsyncSession,
    ) -> tuple["FileService", "ChunkInsertionService"]:
        """
        Build the ingestion service graph scoped to a background task's async session.

        ChromaService, FileService, and ChunkInsertionService are NOT FastAPI
        dependencies — they are created here with a session that outlives the
        original HTTP request.

        Args:
            async_session (AsyncSession): background-task-scoped async DB session
        """
        chroma_svc = ChromaService(
            async_db=async_session,
            chroma_manager=ChromaClientManager(),
        )
        file_svc = FileService(db_session=async_session, chroma_svc=chroma_svc)
        chunk_insertion_svc = ChunkInsertionService(
            db=async_session,
            chroma_svc=chroma_svc,
            file_svc=file_svc,
        )
        return file_svc, chunk_insertion_svc


    

    async def init_embed_task(self, data_source_id: UUID, job_start_time: datetime, job_id: UUID | None = None, async_session: AsyncSession | None = None): 
        """
        Validate Datasource & create inital ingestion job with IN_PROGRESS status 

        Args:
            data_source_id (UUID): the data source this ingestion job corresponds to 
            async_session (AsyncSession?): optional background session
        """
        db = async_session or self.db
        
        # retrieve data source (EAGERLY load project_data and project for future processing)
        stmt = (
            select(DataSource)
                .options( 
                    selectinload(DataSource.project_data) 
                    .selectinload(ProjectData.project) 
                ) 
                .where(DataSource.id == data_source_id)
        )
        res = await db.execute(stmt)
        data_source = res.scalar_one_or_none()

        if not data_source:
            logger.error(f"Failed to find DataSource corresponding to ID={data_source_id}")
            raise Exception("Invalid specified Data Source ID to ingest data from")
        

        # generate current EmbedTask id & persist inital record
        task_pk = uuid4() 
        await self.create_embed_task(embed_task_id=task_pk, data_source_id=data_source_id, start_time=job_start_time, job_id=job_id, async_session=async_session)

        logger.info(f"Successfully created inital EmbedTask with ID={task_pk}")
        return data_source, task_pk





    async def run_embed_task(
            self, 
            embed_task_id: UUID, 
            job_start_time: datetime, 
            data_source: DataSource, 
            project_id: UUID | None = None
        ):
        """
        Run the ingestion job for the specified data source: download files, chunk them,
        and persist nodes to both Chroma (vector store) and the PostgreSQL DocStore.

        Since Chroma and DocStore are each 1-1 with a DataSource, all ingested nodes
        belong exclusively to this data source's collection and namespace.

        Args:
            embed_task_id (UUID): unique ID of the current ingestion job
            job_start_time (datetime): wall-clock time the job was initiated
            data_source (DataSource): the data source being ingested
            project_id (Optional[UUID]): unused; reserved for future project-scoped filtering
        """
        async_session = get_current_session()

        data_source_id = data_source.id

        file_svc, chunk_insertion_svc = self._build_ingestion_services(async_session)

        try:
            provider = IngestibleDataProvider.from_provider(data_source)
        except Exception as e:
            raise TaskSkipped(f"{data_source.type} is not ingestible: {e}")

        # use data source information to fetch relevant data & store in temp directory
        code_path, docs_path = await self._retrieve_data(provider, embed_task_id, file_svc, async_session)

        # determine which data source types were downloaded
        has_docs, has_code = self.is_dir_not_empty(docs_path), self.is_dir_not_empty(code_path)

        # validate retrieval resulted in some data being processed
        if not has_docs and not has_code:
            logger.warning("No new files ingested, skipping ingestion")
        
        # documentation files were ingested
        if has_docs:
            logger.info(f"EmbedTask for DataSource={data_source_id} has ingested relevant docs files; chunking & saving to ChromaDB")

            # run Docling conversion, chunking, and ChromaDB persistence 
            await chunk_insertion_svc.docs_convert_chunk_and_store(data_source, embed_task_id)

        # code files were ingested 
        if has_code:
            logger.info(f"EmbedTask for DataSource={data_source_id} has ingested relevant code files; chunking & saving to ChromaDB")
            await chunk_insertion_svc.code_chunk_and_store(data_source, embed_task_id)
        
        self._cleanup_tmp_dirs(embed_task_id)

        logger.info(
            f"Ingestion Job for DataSource={data_source_id} completed successfully"
        )


    async def update_embed_task(
            self, 
            embed_task_id: UUID, 
            status: ProcessingStatus,
            end_time: datetime, 
            duration: int, 
            session: AsyncSession,
            reason: str | None = None,
            commit: bool = False
        ):
        """
        Update existing EmbedTask with relevant status, end_time, and duration

        Args:
            embed_task_id (UUID): PK of EmbedTask
            status (ProcessingStatus): the status of the EmbedTask
            end_time (datetime): time of completion for EmbedTask 
            duration (int): total amount of time it took to complete ingestion job
            session (AsyncSession): the DB session to use
            reason (str | None): an optional string describing the failure or status
            commit (bool): whether to commit the transaction (default False)
        """

        embed_task = await session.get(EmbedTask, embed_task_id)
        if not embed_task:
            raise Exception(f"Failed to find EmbedTask by PK={embed_task_id}")

        embed_task.processing_status = status
        embed_task.end_time = end_time
        embed_task.total_duration = duration 
        
        if reason is not None:
            embed_task.reason = reason

        session.add(embed_task)
        await session.flush()
        
        if commit:
            await session.commit()

    
    async def create_embed_task(self, embed_task_id: UUID, data_source_id: UUID, start_time: datetime, job_id: UUID | None = None, async_session: AsyncSession | None = None):
        """
        Persist a new EmbedTask that we are kicking off for a particular DataSource

        Args:
            embed_task_id (UUID): PK for current ingestion job 
            data_source_id (UUID): data source this ingestion job is being ran for 
            start_time (datetime): start time of the EmbedTask
            async_session (AsyncSession?): optional background session
        """
        db = async_session or self.db
        embed_task = EmbedTask(
            id=embed_task_id, 
            processing_status=ProcessingStatus.IN_PROGRESS, 
            data_source_id=data_source_id,
            job_id=job_id,
            start_time=start_time
        )

        db.add(embed_task)
        await db.flush()

    async def get_embed_tasks_by_job_id(self, job_id: UUID, session: AsyncSession | None = None) -> list[EmbedTask]:
        """
        Retrieve all EmbedTasks associated with a specific job_id.

        Args:
            job_id (UUID): The ID of the job to retrieve the EmbedTasks for.
            session (AsyncSession, optional): The database session to use. Defaults to None.

        Returns:
            list[EmbedTask]: A list of EmbedTasks associated with the specified job_id.
        """
        db = session or self.db
        stmt = select(EmbedTask).where(EmbedTask.job_id == job_id)
        res = await db.execute(stmt)
        return list(res.scalars().all())

    async def get_all_embed_tasks(self) -> list[EmbedTask]:
        """
        Functionality to retrieve all persisted ingestion jobs
        """
        stmt = (
            select(EmbedTask)
            .order_by(EmbedTask.start_time.desc())
        )
        embed_tasks = await self.db.execute(stmt)
        return list(embed_tasks.scalars().all())
    

    async def _retrieve_data(
        self, provider: IngestibleDataProvider, embed_task_id: UUID, file_svc: "FileService", async_session: AsyncSession
    ) -> tuple[Path, Path]:
        """
        Retrieve relevant data from specified Data Source and store within temporary /data directory
        in order to be ingested into Chroma DB

        Args:
            provider - instantiated IngestibleDataProvider to ingest data from
            embed_task_id (UUID) - unique job id
            file_svc (FileService) - instantiated FileService to use for file state persistence

        NOTE: In future, we should make some sort of "diff" calculation each time we retreive data from data source
        in order to quickly determine what's already been retireving before
        """

        code_path, docs_path = self._create_tmp_dirs(embed_task_id) 

        touched_file_paths = None
        if provider.data_source.type == DataSourceType.REPOSITORY and provider.data_source.scope_by_issues:
            touched_file_paths = await self.diff_task_svc.get_project_touched_file_paths(provider.data_source.id, async_session=async_session)
            logger.info(f"DataSource {provider.data_source.id} is scoped by issues. Fetched {len(touched_file_paths)} touched file paths across projects.")

        await provider.ingest_data(embed_task_id=embed_task_id, file_svc=file_svc, touched_file_paths=touched_file_paths) 
        return code_path, docs_path


    def _create_tmp_dirs(self, embed_task_id: UUID):
        """
        Create temporary directory for storing downloaded code and documentation files

        Args:
            embed_task_id (UUID): unique ID for current job (used to ensure files downloaded for ingestion job stored in unique dir)
        """

        docs_path = Path(f"{settings.TMP_DOCS or 'tmp/docs'}/{embed_task_id}")
        docs_path.mkdir(exist_ok=True, parents=True)
        code_path = Path(f"{settings.TMP_CODE or 'tmp/code'}/{embed_task_id}")
        code_path.mkdir(exist_ok=True, parents=True)

        return code_path, docs_path


    def _cleanup_tmp_dirs(self, embed_task_id: UUID):
        """
        Recursively remove all files and subdirectories from the job-specific
        temporary directories, then attempt to remove the shared base dirs
        if no other jobs are currently using them.

        Args:
            embed_task_id (UUID): unique ID for current ingestion job 
        """
        
        logger.info(f"Cleaning up temporary directories for EmbedTask={embed_task_id}")

        # base dirs to remove
        tmp_dir = Path(settings.TMP or "/tmp")
        code_dir = Path(settings.TMP_CODE or "/tmp/code")
        docs_dir = Path(settings.TMP_DOCS or "/tmp/docs")

        # ingestion specific dirs to fully clean (may contain nested subdirectories)
        job_code_path = code_dir / str(embed_task_id)
        job_docs_path = docs_dir / str(embed_task_id)

        # recursively remove entire job-specific directory trees (files + subdirs)
        for job_path in [job_docs_path, job_code_path]: 
            if job_path.is_dir():
                try:
                    shutil.rmtree(job_path)
                    logger.debug(f"Removed temporary directory: {job_path}")
                except OSError as e:
                    logger.warning(f"Failed to remove temporary directory {job_path}: {e}")

        # attempt to remove shared base dirs
        # NOTE: rmdir() only succeeds when the directory is empty, so if another
        # ingestion job is still running this will safely no-op and log a warning
        for base_dir in [code_dir, docs_dir, tmp_dir]:
            if base_dir.is_dir():
                try:
                    base_dir.rmdir()
                except OSError:
                    logger.debug(f"Base directory {base_dir} still in use by another job, skipping removal")


    def is_dir_not_empty(self, path: Path):
        """
        Check if the specified path directory is empty

        TODO: Move this to a directory utils class or something along with the cleanup / create tmp directories
        """

        if not path.is_dir():
            raise Exception("Invalid directory path specified")

        return any(path.iterdir())



