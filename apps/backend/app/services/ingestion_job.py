import logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import UUID, uuid4
from collections.abc import Iterator
from typing import Any
import asyncio
import threading
import shutil
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataSource, IngestionJob, ProcessingStatus, RecordType, ProjectData, Project
from app.data_providers import GithubDataProvider
from app.core import settings, get_async_session_maker, DOCS, CODE
from app.embeddings import EmbeddingManager
from app.services.util import get_normalized_project_name
from app.services.chroma import ChromaService 
from app.services.record_lock import RecordLockService
from app.services.file import FileService

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.exceptions import ConversionError
from docling.pipeline.threaded_standard_pdf_pipeline import ThreadedStandardPdfPipeline
from docling.datamodel.pipeline_options import ThreadedPdfPipelineOptions
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling.datamodel.document import ConversionResult
from docling_core.transforms.chunker.doc_chunk import DocChunk, DocMeta

from llama_index.vector_stores.chroma import ChromaVectorStore # type: ignore
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.core.node_parser import CodeSplitter
from llama_index.core.readers import SimpleDirectoryReader



logger = logging.getLogger(__name__)

class IngestionJobService:
    """
    TODO: Consider shifting over some of this chunking logic over to the Chunking Service and then removing the dependency on the 
    Chroma Service and adding the Chunking Service as a dependency
    """

    def __init__(
            self, 
            db: AsyncSession, 
            chroma_svc: ChromaService,
            record_lock_svc: RecordLockService,
            file_svc: FileService
    ):
        self.db: AsyncSession = db
        self.chroma_svc: ChromaService = chroma_svc
        self.record_lock_svc: RecordLockService = record_lock_svc
        self.file_svc: FileService = file_svc

    
    async def init_ingestion_job(self, data_source_id: UUID, job_start_time: datetime): 
        """
        Validate Datasource & create inital ingestion job with IN_PROGRESS status 

        Args:
            data_source_id (UUID): the data source this ingestion job corresponds to 
        """
        
        # retrieve data source (EAGERLY load project_data, project, and chroma collections for future processing)
        stmt = (
            select(DataSource)
                .options( 
                    selectinload(DataSource.project_data) 
                    .selectinload(ProjectData.project) 
                    .selectinload(Project.chroma_collections)
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
        Kick off ingestion job for specified data source and store relevant ingested data into ChromaDB

        Args:
            data_source_id (UUID)
                - specifici data source to retrieve data from
            project_id (Optional(UUID))
                - optional project ID to only retrieve data for specified project

        TODO:
            1. Consider adding multi-threading concurrency to this approach to speed up larger IngestionJobs 
            2. Look into total amount of time processing takes when ONLY using CPU (any optimizations we can make?)
        """

        # begin processing for current IngestionJob
        data_source_id = data_source.id

        try:

            # use data source information to fetch relevant data & store in temp directory
            # TODO: Add configuration possibility to only retrieve data specific to the Jira Tickets provided in Project
            code_path, docs_path = await self._retrieve_data(data_source, project_id, job_pk)

            # determine which data source types were downloaded
            has_docs, has_code = self.is_dir_not_empty(docs_path), self.is_dir_not_empty(code_path)

            # validate retrieval resulted in some data being processed
            if not has_docs and not has_code:
                logger.warning("No new files ingested, skipping ingestion")
            
            # TODO: Ensure we're not duplicating chunks when reingesting a fie

            # documentation files were ingested
            # TODO: Consider moving logic surronding chunking & converting & storing to Chroma in their own seperate services 
            if has_docs:
                logger.info(f"IngestionJob for DataSource={data_source_id} has ingested relevant docs files; chunking & saving to ChromaDB")

                #  TODO: How can we update this logic to intelligently use images/graphs/tables/charts that may be on documents? 

                # TODO: Consider thread pool based on available resources to user (CPU cores, GPU, etc)
                # run Docling conversion, chunking, and ChromaDB persistence 
                await self.docs_convert_chunk_and_store(data_source, project_id, job_pk)


            # code files were ingested 
            if has_code:
                logger.info(f"IngestionJob for DataSource={data_source_id} has ingested relevant code files; chunking & saving to ChromaDB")
                await self.code_chunk_and_store(data_source, project_id, job_pk)


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


        

    async def code_chunk_and_store(
            self, 
            data_source: DataSource, 
            project_id: UUID | None, 
            job_pk: UUID
    ):
        """
        TODO: Combine this function with docs convert chunk and store 

        Functionality to Chunk ingested code files and store them within Chroma DB collection

        Args:
            data_source (DataSource): the data source corresponding to current ingestion job 
            project_id (Optional[UUID]): optional specified proejct to run ingestion job for 
            job_pk (UUID): pk of current ingesetion job
        """
        logger.info(f"Chunking and storing downloaded Code files")

        # chunk & convert relevant code files (using CodeSplitter from LlamaIndex)
        nodes = await self._chunk_code(data_source, project_id, job_pk)

        # save LlamaIndex nodes to ChromaDB collection
        await asyncio.to_thread(
            self._save_to_chroma, 
            nodes, 
            CODE, 
            data_source
        )

        logger.info(f"Succesfully chunked and stored downloaded Code files")



    async def docs_convert_chunk_and_store(
            self,
            data_source: DataSource, 
            project_id: UUID | None,
            job_pk: UUID
        ):
        """
        TODO: Combine this function with code chunk & store 

        Convert downloaded Documentation files to Docling files, chunk using Docling's HybridChunker,
        convert to LlamaIndex TextNodes & store in relevant Chroma DB collection

        NOTE: This functionality will offload blocking processes to seperate worker threads 

        Args:
            data_source (DataSource): the data source corresponding to current ingestion job
            project_id (Optional[UUID]): optional specified project to run ingestion job for 
            job_pk (UUID): pk of current ingesetion job
        """

        logger.info(f"Converting, chunking, and storing downloaded Documentation via workerThreadId={threading.get_ident()}")

        # convert docs to docling files 
        converted_files = await asyncio.to_thread(
            self._convert_docs_files_to_docling, 
            job_pk
        )
        if not converted_files:
            logger.warning("No documentation files were converted, skipping ingestion")
            return

        # chunk ingested documentation based on configured project embedding model
        project_chunks = await asyncio.to_thread(
            self._chunk_docs, 
            data_source, 
            project_id,
            converted_files
        )
        logger.debug('Successfully chunked ingested documentation for each project')

        # convert Docling chunks to LlamaIndex TextNodes (NOTE: Async call to file_svc, so must be on main loop)
        nodes = await self._convert_to_text_nodes(project_chunks, data_source.id)
        logger.debug(f"Successfully convert DocChunks to LlamaIndex TextNode's")

        # store results within Chroma DB, using embedding specified DataSource
        await asyncio.to_thread(
            self._save_to_chroma, 
            nodes, 
            DOCS, 
            data_source
        )

        logger.info(f"Succesfully converted, chunked, and stored downloaded Documentation files")


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
        return ingestion_jobs.scalars().all()
    

    async def _retrieve_data(
        self, data_source: DataSource, project_id: UUID | None, job_pk: UUID,
    ) -> tuple[Path, Path]:
        """
        Retrieve relevant data from specified Data Source and store within temporary /data directory
        in order to be ingested into Chroma DB

        Args:
            data_source (DataSource) - data source to ingest data from
            project_id (UUID) - optional specific project_id to only retrieve data for

        NOTE: In future, we should make some sort of "diff" calculation each time we retreive data from data source
        in order to quickly determine what's already been retireving before

        TODO: Allow for providers such as GitHub & BitBucket to be parsed by commit messages containing the
        Jira Ticket number
        """

        code_path, docs_path = self._create_tmp_dirs(job_pk) 

        # retrieve data based on provider & store within temp directory
        match data_source.provider:
            case "GitHub":
                provider = GithubDataProvider(data_source=data_source, job_pk=job_pk, file_svc=self.file_svc)
            case _:
                logger.error(
                    f"The specified Data Source provider is not configured for this application"
                )
            

        await provider.ingest_data() 
        return code_path, docs_path
    

    async def _convert_to_text_nodes(
        self, 
        chunks: dict[str, list[dict[str, Any]]], 
        data_source_id: UUID
    ) -> dict[str, list[TextNode]]:
        """
        Convert Docling chunks to TextNodes in order to store within ChromaDB 

        Args:
            chunks (dict): mapping of a Project to a list of Docling chunks for relevant ingested Documents 
        """
        project_nodes = {}

        logger.debug(f"Converting Chunks to LlamaIndex TextNodes in order to store in ChromaDB")
        for project, chunked_data in chunks.items():

            project_nodes[project] = []
            for i, data in enumerate(chunked_data):

                # extract DocChunk & ContextChunk from mapping
                doc_chunk = data['doc_chunk']
                context_chunk = data['contextualized_chunk']
                file_path = data['file_path']

                project_nodes[project].append(
                    TextNode(
                        _id=f"{doc_chunk.meta.origin.filename}_{i}", 
                        text=context_chunk,
                        metadata=await self._get_chunk_meta_data(doc_chunk, i, project, data_source_id, file_path)
                    )
                )
        
        return project_nodes


    async def _get_chunk_meta_data(
        self, 
        chunk: DocChunk, 
        i: int, 
        project: str,
        data_source_id: UUID,
        file_path: str
    ) -> dict[str, str]:
            """
            Helper function to extract relevant metadata for a particular Document Chunk 

            Args:
                chunk (DocChunk): document chunk to extract meta data for 
                i (int): current position 
                project (str): relevant project this chunk belongs to
                data_source_id (UUID): data source this chunk belongs to
                file_path (str): absolute file path of the file this chunk belongs to
            """
            chunks_meta_data: DocMeta = chunk.meta 

            origin_file = chunks_meta_data.origin.filename if chunks_meta_data.origin else ""
            mimetype = chunks_meta_data.origin.mimetype if chunks_meta_data.origin else ""
            headings = chunks_meta_data.headings 
            document_hash = str(chunks_meta_data.origin.binary_hash) if chunks_meta_data.origin else ""

            cleaned_file_path = self._clean_file_path(file_path)

            file = await self.file_svc.get_file_by_path_and_data_source(cleaned_file_path, data_source_id)
            if not file:
                raise Exception(f"Unable to locate File assocaited with the DataSource={data_source_id} and Path={cleaned_file_path}")

            content_types = ",".join(list(set([
                str(item.label)
                for item in chunks_meta_data.doc_items 
            ])))

            # TODO: Add file name, file path, file hash too
            return {
                "chunk_idx": f"{get_normalized_project_name(project)}_{i}",
                "source": origin_file,
                "file_path": file_path,
                "mimetype": mimetype,
                "headings": " > ".join(headings) if headings else "No Headings",
                "document_hash": document_hash,
                "content_types": content_types,
                "file_id": str(file.id)
            }

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

    def _convert_docs_files_to_docling(self, job_pk: UUID) -> Iterator[ConversionResult] | None:
        """
        Convert each temporary document downloaded to a markdown file

        TODO: Configure onnxruntime
        """

        # convert configured docs file extensions to docling InputFormats
        allowed_formats = [
            InputFormat(allowed_format.lower())
            for allowed_format in settings.DOCS_FILE_EXTENSIONS
        ]

        # setup pipeline pipeline options
        try:
            # TODO: Consider toggling on OCR for extracting text from image-based content
            pipeline_options = ThreadedPdfPipelineOptions(
                accelerator_options=AcceleratorOptions(
                    device=AcceleratorDevice(settings.DOCLING_ACCELERATOR_DEVICE)
                ),
                table_batch_size=4,
                layout_batch_size=64,
            )
            pipeline_options.do_table_structure = True
        except ValueError as e:
            logger.error(f"Failed to created ThreadStandardPdfPipeline", exc_info=True)
            raise e

        # create converter for creating Docling Documents from our local files
        docs_converter = DocumentConverter(
            allowed_formats=allowed_formats,
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=ThreadedStandardPdfPipeline,
                    pipeline_options=pipeline_options,
                )
            },
        )

        # retrieve list of files from tmp docs
        tmp_docs = Path(f"{settings.TMP_DOCS}/{job_pk}") 
        input_files = list(tmp_docs.glob("**/*"))
        filtered_doc_files = [
            f for f in input_files if f.is_file()
        ]  # only retrieve files

        # skip conversion if no new document files retrieved
        if not filtered_doc_files:
            logger.debug(
                f"No new Documentation files downloaded; skipping Docling conversion"
            )
            return None

        # convert all docs files to Docling Docs
        try:
            conv_results = docs_converter.convert_all(filtered_doc_files)
            logger.info(f"Successfully converted ingested Documentation files to Docling files")
        except ConversionError as e:
            logger.error(f"Failed to convert all documents ingested", exc_info=True)
            raise e


        return conv_results


    def _save_to_chroma(self, project_chunks: dict[str | UUID, list[TextNode]], source_type: str, data_source: DataSource) -> None: 
        """
        Save context-rich ingested documentation and code to our relevant Chroma collections based on Projects 
        this ingested job is being ran for 

        TODO: Consider moving this to Chroma Service 

        Args:
            project_chunks (dict): relevant chunked docs/code 
            source_type (str): the content type of the files being saved 
        """
        
        # create mapping of project name to Project model 
        project_mapping = {record.project.project_name: record.project for record in data_source.project_data} 

        for project, nodes in project_chunks.items():

            # get Project model 
            curr_project = project_mapping[str(project)]

            # get embedding manager for project
            embedding_manager = EmbeddingManager(curr_project.collections_by_type)

            # retrieve Chroma DB collection 
            collection = self.chroma_svc.get_real_chroma_collection(
                f"{get_normalized_project_name(str(project))}_{source_type}"
            )

            # get chroma vector store corresponding to our projects DOCS collection
            vector_store = ChromaVectorStore(chroma_collection=collection)
            storage_context = StorageContext.from_defaults(vector_store=vector_store)

            # store nodes within Chroma 
            index = VectorStoreIndex(
                nodes=nodes, # NOTE: Instead of using LlamaIndex's Document object, we will use our manually generated nodes
                storage_context=storage_context,
                embed_model=embedding_manager.get_embedding_model(source_type) # use configured embedding model for current Project
            )

            # TODO: Update ChromaDB Collection with Document Count OR Remove Doc Count entirely from DB 


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


    async def _chunk_code(
        self, 
        data_source: DataSource, 
        project_id: UUID | None, 
        job_pk: UUID
    ) -> dict[str | UUID, list[TextNode]]:
        """
        Functionality to chunk code files via LlamaIndex (using CodeSplitter)

        CodeSplitter uses treesitter under the hood to generate AST & create context-driven chunks

        Args:
            data_source (DataSource): data source we are ingesting docs for 
            project_id (UUID): Optional project to ingest docs for 
            job_pk (UUID): unique ID of current ingestion job
        """    

        # read files from temporary directory 
        reader = SimpleDirectoryReader( # TODO: Look into leveraging "num_workers" attribute if we choose to utilize multi-threading & 
            input_dir=f"{settings.TMP_CODE or 'tmp/code'}/{job_pk}", 
            recursive=True,
            raise_on_error=True
        )

        # split files based on language support
        try:
            all_docs = defaultdict(list)
            for docs in reader.iter_data():  
                for doc in docs: 

                    # clean file path to remove the temporary directory path
                    file_path = self._clean_file_path(doc.metadata["file_path"])

                    # get file by data source and path 
                    file = await self.file_svc.get_file_by_path_and_data_source(file_path, data_source.id)
                    if not file:
                        raise Exception(f"Unable to find File for the DataSource={data_source.id} and Path={file_path}")

                    # add meta data for file ID 
                    doc.metadata["file_id"] = str(file.id)

                    # get file extension and determine file type
                    ext = Path(doc.metadata["file_name"]).suffix.lower().lstrip(".")
                    curr_file_type = settings.EXTENSION_TO_LANGUAGE[ext] if ext in settings.EXTENSION_TO_LANGUAGE else "plain_text"
                    all_docs[curr_file_type].append(doc)

            logger.debug(f"Successfully split ingested Code files into following language groups: {all_docs.keys()}") 

        except Exception as e:
            logger.error(f"Failed to read ingested code files from temporary directory", exc_info=True)
            raise e


        # chunk files based on language 
        nodes = []
        for file_type, docs in all_docs.items():
            
            # configure splitter to be used for grouped file types
            splitter = CodeSplitter(language=file_type) # TODO: Consider tweaking max_chars or other attributes here
            nodes.extend(splitter.get_nodes_from_documents(docs)) #TODO: Consider if using async get nodes from docs provides any benefits in performance

            logger.debug(f"Successfully chunked ingested code files for language={file_type} into {len(nodes)} nodes")
        

        # setup mapping for project to corresponding nodes 
        project_nodes: dict[str | UUID, list[TextNode]] = {record.project.project_name: nodes for record in data_source.project_data} if not project_id else {project_id: nodes}
        return project_nodes

        



    def _chunk_docs(self, data_source: DataSource, project_id: UUID | None, conversion_results: Iterator[ConversionResult]) -> dict[str, list[dict[str, Any]]]: 
        """
        Functionality to chunk docs via Dockling 

        Args:
            data_source (DataSource): data source we are ingesting docs for 
            project_id (UUID): Optional project to ingest docs for 
            conversion_results (Iterator[ConversionResult]): converted docling files results
        """

        # retrieve projects corresponding to data soruce 
        projects: list[Project] = [record.project for record in data_source.project_data] # TODO: Account for single Projecto nly

        # generate mapping of project to relevant ingested documentation chunks 
        chunked_docs = {project.project_name: [] for project in projects}
        for project in projects:
            
            # get chunker based on configured embedding model for the current project
            embedding_manager = EmbeddingManager(project.collections_by_type)
            chunker = HybridChunker(
                tokenizer=embedding_manager.get_docs_tokenizer(), 
                #TODO: Consider setting maximum length of tokens = 512 
            )

            # iterate through converted Docling documents 
            for res in conversion_results:
                logger.debug(f'Conversion result confidence for Document={res.document.name} = {res.confidence}')

                # extract absolute file 
                file_path = str(res.input.file)

                # chunk current Docling document into DocChunk's
                curr_doc_chunks = list(chunker.chunk(dl_doc=res.document))

                # iterate through chunks in current document 
                for chunk in curr_doc_chunks:
                    chunked_docs[project.project_name].append(
                        {
                            "doc_chunk": chunk,
                            "contextualized_chunk": chunker.contextualize(chunk=chunk),
                            "file_path": file_path
                        }
                    )


        return chunked_docs
    

    def _clean_file_path(self, file_path: str): 
        """
        Clean file path to remove the temporary directory path

        Args:
            file_path (str): absolute file path to clean
            job_pk (UUID): unique ID of current ingestion job
        """

        file_path_split = file_path.split("/")
        if len(file_path_split) < 5:
            raise Exception(f"Unable to clean file path: {file_path}: Expected at least 5 components in file path")
        
        return "/".join(file_path_split[5:])


