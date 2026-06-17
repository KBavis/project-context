from __future__ import annotations
import logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import UUID, uuid4
import shutil

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataSource, IngestionJob, ProcessingStatus, RecordType, ProjectData, Project
from app.core import settings, get_async_session_maker
from app.services.record_lock import RecordLockService
from app.services.file import FileService
from app.services.chunk_insertion import ChunkInsertionService
from typing import TYPE_CHECKING
from app.data_providers.ingestible.base import IngestibleDataProvider

if TYPE_CHECKING:
    from app.services.data_source import DataSourceService
logger = logging.getLogger(__name__)

class IngestionJobService:

    def __init__(
            self, 
            db: AsyncSession, 
            record_lock_svc: RecordLockService,
            file_svc: "FileService",
            chunk_insertion_service: "ChunkInsertionService",
            data_source_svc: "DataSourceService"
    ):
        """
        Initialize IngestionJobService with necessary dependencies

        Args:
            db (AsyncSession): Database session for ORM operations
            record_lock_svc (RecordLockService): Service for managing record locks
            file_svc (FileService): Service for file operations
            chunk_insertion_service (ChunkInsertionService): Service for chunking and storing data
            data_source_svc (DataSourceService): Service for managing data sources
        """
        self.db: AsyncSession = db
        self.record_lock_svc: RecordLockService = record_lock_svc
        self.file_svc: "FileService" = file_svc
        self.chunk_insertion_service: "ChunkInsertionService" = chunk_insertion_service
        self.data_source_svc: "DataSourceService" = data_source_svc

    async def get_project_ingestion_state(self, project_id: UUID) -> str:
        """
        Determine whether every ingestible DataSource (REPOSITORY, DOCUMENTATION)
        for this project has a successful IngestionJob.

        Returns a ProcessingStatus string value: 'success', 'in_progress', or 'failed'.
        """
        ingestible = await self.data_source_svc.get_ingestible_data_sources(project_id, self.db)

        if not ingestible:
            logger.info(f"[IngestionState] project_id={project_id}: no ingestible sources → success")
            return ProcessingStatus.SUCCESS.value

        states = []
        for ds in ingestible:
            stmt = (
                select(IngestionJob)
                .where(IngestionJob.data_source_id == ds.id)
                .order_by(IngestionJob.start_time.desc())
                .limit(1)
            )
            res = await self.db.execute(stmt)
            latest_job = res.scalar_one_or_none()

            if not latest_job:
                logger.info(
                    f"[IngestionState] project_id={project_id}, ds={ds.id} ({ds.name}): "
                    "no IngestionJob found → failed"
                )
                states.append(ProcessingStatus.FAILED.value)
                continue

            job_state = latest_job.processing_status.value
            logger.info(
                f"[IngestionState] project_id={project_id}, ds={ds.id} ({ds.name}): "
                f"latest IngestionJob={latest_job.id}, status={job_state}"
            )
            states.append(ProcessingStatus.FAILED.value if job_state == ProcessingStatus.SKIPPED.value else job_state)

        logger.info(f"[IngestionState] project_id={project_id}: states={states}")

        if ProcessingStatus.IN_PROGRESS.value in states:
            return ProcessingStatus.IN_PROGRESS.value
        if ProcessingStatus.FAILED.value in states:
            return ProcessingStatus.FAILED.value
        return ProcessingStatus.SUCCESS.value



    

    async def init_ingestion_job(self, data_source_id: UUID, job_start_time: datetime): 
        """
        Validate Datasource & create inital ingestion job with IN_PROGRESS status 

        Args:
            data_source_id (UUID): the data source this ingestion job corresponds to 
        """
        
        # retrieve data source (EAGERLY load project_data and project for future processing)
        stmt = (
            select(DataSource)
                .options( 
                    selectinload(DataSource.project_data) 
                    .selectinload(ProjectData.project) 
                ) 
                .where(DataSource.id == data_source_id)
        )
        res = await self.db.execute(stmt)
        data_source = res.scalar_one_or_none()

        if not data_source:
            logger.error(f"Failed to find DataSource corresponding to ID={data_source_id}")
            raise Exception("Invalid specified Data Source ID to ingest data from")
        
        # lock specified DataSource 
        locked = await self.record_lock_svc.lock(data_source.id, RecordType.DATA_SOURCE)
        if not locked:
            raise Exception(f"Failed to acquire lock for DataSource={data_source_id}: Record already locked")
            
        
        # generate current IngestionJob id & persist inital record
        job_pk = uuid4() 
        await self.create_ingestion_job(job_pk=job_pk, data_source_id=data_source_id, start_time=job_start_time)

        logger.info(f"Successfully created inital IngestionJob with ID={job_pk}")
        return data_source, job_pk



    async def run_ingestion_job(
            self, 
            job_pk: UUID, 
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
            job_pk (UUID): unique ID of the current ingestion job
            job_start_time (datetime): wall-clock time the job was initiated
            data_source (DataSource): the data source being ingested
            project_id (Optional[UUID]): unused; reserved for future project-scoped filtering
        """

        data_source_id = data_source.id

        try:
            provider = IngestibleDataProvider.from_provider(data_source)
        except Exception as e:
            logger.info(
                f"Skipping ingestion for DataSource={data_source_id}: "
                f"type={data_source.type} is not ingestible. Reason: {e}"
            )
            job_end_time = datetime.now(ZoneInfo("America/New_York"))
            duration = job_end_time - job_start_time
            await self.update_ingestion_job(
                job_pk=job_pk,
                status=ProcessingStatus.SKIPPED,
                end_time=job_end_time,
                duration=duration.seconds,
                session=self.db
            )
            return

        try:

            # use data source information to fetch relevant data & store in temp directory
            code_path, docs_path = await self._retrieve_data(provider, job_pk)

            # determine which data source types were downloaded
            has_docs, has_code = self.is_dir_not_empty(docs_path), self.is_dir_not_empty(code_path)

            # validate retrieval resulted in some data being processed
            if not has_docs and not has_code:
                logger.warning("No new files ingested, skipping ingestion")
            
            # documentation files were ingested
            if has_docs:
                logger.info(f"IngestionJob for DataSource={data_source_id} has ingested relevant docs files; chunking & saving to ChromaDB")

                #  TODO: How can we update this logic to intelligently use images/graphs/tables/charts that may be on documents? 

                # TODO: Consider thread pool based on available resources to user (CPU cores, GPU, etc)
                # run Docling conversion, chunking, and ChromaDB persistence 
                await self.chunk_insertion_service.docs_convert_chunk_and_store(data_source, job_pk)


            # code files were ingested 
            if has_code:
                logger.info(f"IngestionJob for DataSource={data_source_id} has ingested relevant code files; chunking & saving to ChromaDB")
                await self.chunk_insertion_service.code_chunk_and_store(data_source, job_pk)
            
            self._cleanup_tmp_dirs(job_pk)

            job_end_time = datetime.now(ZoneInfo("America/New_York"))
            duration = job_end_time - job_start_time

            # update IngestionJob status to be SUCCESS
            await self.update_ingestion_job(
                job_pk=job_pk, 
                status=ProcessingStatus.SUCCESS,
                end_time=job_end_time,
                duration=duration.seconds,
                session=self.db # use main DB session
            )

            logger.info(
                f"Ingestion Job for DataSource={data_source_id} completed successfully in {duration.seconds} seconds"
            )

        except Exception as e:
            logger.error(f"Failure occurred while performing IngestionJob={job_pk}: {str(e)}")

            job_fail_time = datetime.now(ZoneInfo("America/New_York"))
            duration=(job_fail_time - job_start_time).seconds

            # NOTE: seperate session required in order to ensure status update is not rolled back
            session_maker = get_async_session_maker()
            async with session_maker() as session:

                # update IngestionJob with status/duration
                await self.update_ingestion_job(
                    job_pk=job_pk,
                    status=ProcessingStatus.FAILED,
                    end_time=job_fail_time,
                    duration=duration,
                    session=session
                )
        finally:
            # unlock DataSource after processing 
            await self.record_lock_svc.unlock(data_source_id, record_type=RecordType.DATA_SOURCE)


    async def update_ingestion_job(
            self, 
            job_pk: UUID, 
            status: ProcessingStatus,
            end_time: datetime, 
            duration: int, 
            session: AsyncSession
        ):
        """
        Update existing IngestionJob with relevant status, end_time, and duration

        Args:
            job_pk (UUID): PK of IngestionJob
            status (ProcessingStatus): the status of the IngestionJob
            end_time (datetime): time of completion for IngestionJob 
            duration (int): total amount of time it took to complete ingestion job
        """

        ingestion_job = await session.get(IngestionJob, job_pk)
        if not ingestion_job:
            raise Exception(f"Failed to find IngestionJob by PK={job_pk}")

        ingestion_job.processing_status = status
        ingestion_job.end_time = end_time
        ingestion_job.total_duration = duration 

        session.add(ingestion_job)
        await session.flush()
        await session.commit()

    
    async def create_ingestion_job(self, job_pk: UUID, data_source_id: UUID, start_time: datetime):
        """
        Persist a new IngestionJob that we are kicking off for a particular DataSource

        Args:
            job_pk (UUID): PK for current ingestion job 
            data_source_id (UUID): data source this ingestion job is being ran for 
            start_time (datetime): start time of the IngestionJob
        """
        ingestion_job = IngestionJob(
            id=job_pk, 
            processing_status=ProcessingStatus.IN_PROGRESS, 
            data_source_id=data_source_id,
            start_time=start_time
        )

        self.db.add(ingestion_job)
        await self.db.flush()

    async def get_all_ingestion_jobs(self) -> list[IngestionJob]:
        """
        Functionality to retrieve all persisted ingestion jobs
        """
        stmt = (
            select(IngestionJob)
            .order_by(IngestionJob.start_time.desc())
        )
        ingestion_jobs = await self.db.execute(stmt)
        return list(ingestion_jobs.scalars().all())
    

    async def _retrieve_data(
        self, provider: IngestibleDataProvider, job_pk: UUID,
    ) -> tuple[Path, Path]:
        """
        Retrieve relevant data from specified Data Source and store within temporary /data directory
        in order to be ingested into Chroma DB

        Args:
            provider - instantiated IngestibleDataProvider to ingest data from
            project_id (UUID) - optional specific project_id to only retrieve data for

        NOTE: In future, we should make some sort of "diff" calculation each time we retreive data from data source
        in order to quickly determine what's already been retireving before
        """

        code_path, docs_path = self._create_tmp_dirs(job_pk) 

        await provider.ingest_data(job_pk=job_pk, file_svc=self.file_svc) 
        return code_path, docs_path


    def _create_tmp_dirs(self, job_pk: UUID):
        """
        Create temporary directory for storing downloaded code and documentation files

        Args:
            job_pk (UUID): unique ID for current job (used to ensure files downloaded for ingestion job stored in unique dir)
        """

        docs_path = Path(f"{settings.TMP_DOCS or 'tmp/docs'}/{job_pk}")
        docs_path.mkdir(exist_ok=True, parents=True)
        code_path = Path(f"{settings.TMP_CODE or 'tmp/code'}/{job_pk}")
        code_path.mkdir(exist_ok=True, parents=True)

        return code_path, docs_path


    def _cleanup_tmp_dirs(self, job_pk: UUID):
        """
        Recursively remove all files and subdirectories from the job-specific
        temporary directories, then attempt to remove the shared base dirs
        if no other jobs are currently using them.

        Args:
            job_pk (UUID): unique ID for current ingestion job 
        """
        
        logger.info(f"Cleaning up temporary directories for IngestionJob={job_pk}")

        # base dirs to remove
        tmp_dir = Path(settings.TMP or "/tmp")
        code_dir = Path(settings.TMP_CODE or "/tmp/code")
        docs_dir = Path(settings.TMP_DOCS or "/tmp/docs")

        # ingestion specific dirs to fully clean (may contain nested subdirectories)
        job_code_path = code_dir / str(job_pk)
        job_docs_path = docs_dir / str(job_pk)

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



