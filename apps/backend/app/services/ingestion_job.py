import logging
from pathlib import Path
from datetime import datetime
from uuid import UUID
from typing import Tuple, Iterator

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import DataSource
from app.data_providers import GithubDataProvider
from app.core import settings
from app.embeddings import EmbeddingManager

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.exceptions import ConversionError
from docling.pipeline.threaded_standard_pdf_pipeline import ThreadedStandardPdfPipeline
from docling.datamodel.pipeline_options import ThreadedPdfPipelineOptions
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.chunking import HybridChunker
from docling.datamodel.document import ConversionResult

logger = logging.getLogger(__name__)


class IngestionJobService:
    def __init__(self, db: Session):
        self.db = db

    def run_ingestion_job(self, data_source_id: UUID, project_id: UUID = None):
        """
        Kick off ingestion job for specified data source and store relevant ingested data into ChromaDB

        Args:
            data_source_id (UUID)
                - specifici data source to retrieve data from
            project_id (Optional(UUID))
                - optional project ID to only retrieve data for specified project

        TODO: Processing is taking very long, defintely need to convert to async and run this flow in background or request could timeout
        """

        job_start_time = datetime.now()

        # retrieve data source
        stmt = select(DataSource).where(DataSource.id == data_source_id)
        data_source = self.db.execute(stmt).scalar_one_or_none()

        if not data_source:
            raise Exception("Invalid specified Data Source ID to ingest data from")

        # use data source information to fetch relevant data & store in temp directory
        # TODO: Add configuration possibility to only retrieve data specific to the Jira Tickets provided in Project
        code_path, docs_path = self._retrieve_data(data_source, project_id)

        # determine which data source types were downloaded
        has_docs, has_code = self.is_dir_not_empty(docs_path), self.is_dir_not_empty(
            code_path
        )

        # validate retrieval resulted in some data being processed
        if not has_docs and not has_code:
            logger.warning("No new files ingested, skipping ingestion")
            return

        if has_docs:
            
            # convert docs to docling files 
            converted_files = self._convert_docs_files_to_docling()

            # iterate through docs and chunk
            self._chunk_docs(data_source, project_id, converted_files)

            # store results within Chroma DB, using embedding specified DataSource

        # persist IngestionJob to DB

        self._cleanup_tmp_dirs(code_path, docs_path)

        job_end_time = datetime.now()
        duration = job_end_time - job_start_time

        logger.info(
            f"Ingestion Job for DataSource={data_source_id} completed successfully in {duration.seconds} seconds"
        )

        # TODO: Return IngestionJob created ID
        return {"message": "Success"}

    def _retrieve_data(
        self, data_source: DataSource, project_id: UUID
    ) -> Tuple[Path, Path]:
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

        code_path, docs_path = self._create_tmp_dirs()

        # retrieve data based on provider & store within temp directory
        match data_source.provider:
            case "GitHub":
                logger.info(
                    f"Attempting to retrieve data from GitHub provider for URL: {data_source.url}"
                )
                provider = GithubDataProvider(url=data_source.url)
                provider.ingest_data()
            case _:
                logger.error(
                    f"The specified Data Source provider is not configured for this application"
                )

        return code_path, docs_path

    def _create_tmp_dirs(self):
        """
        Create temporary directory for storing downloaded code and documentation files
        """

        docs_path = Path(settings.TMP_DOCS)
        docs_path.mkdir(exist_ok=True, parents=True)
        code_path = Path(settings.TMP_CODE)
        code_path.mkdir(exist_ok=True, parents=True)

        return code_path, docs_path

    def _convert_docs_files_to_docling(self) -> Iterator[ConversionResult]:
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
        tmp_docs = Path(settings.TMP_DOCS)
        input_files = list(tmp_docs.glob("**/*"))
        filtered_doc_files = [
            f for f in input_files if f.is_file()
        ]  # only retrieve files

        # skip conversion if no new document files retrieved
        if not filtered_doc_files:
            logger.debug(
                f"No new Documentation files downloaded; skipping markdown conversion"
            )
            return

        # convert all docs files to Docling Docs
        try:
            conv_results = docs_converter.convert_all(filtered_doc_files)
        except ConversionError as e:
            logger.error(f"Failed to convert all documents ingested", exc_info=True)
            raise e


        return conv_results

    
    def _create_temporary_markdown_files(conversion_results: Iterator[ConversionResult]):
        """
        Helper function to store covnerted docs files as markdown files 
        """
        # create processed docs dir to save md files to
        path = settings.TMP_DOCS + settings.PROCESSED_DIR
        out_path = Path(path)
        out_path.mkdir(exist_ok=True, parents=True)

        # write docling files as md files in processed dir
        for res in conversion_results:
            file_name = f"{res.input.file.stem}.md"

            with open(out_path / f"{file_name}", "w") as fp:
                fp.write(res.document.export_to_markdown())


    def _cleanup_tmp_dirs(self, code_path: Path, docs_path: Path):
        """
        Remove files from temporary directory and remove directory altogether

        Args:
            code_path: directory storing code files
            docs_path: directory storing docs files
        """

        tmp_dir = Path(settings.TMP)

        # delete all files in /tmp & corresponding sub-directories
        for file_path in tmp_dir.rglob("*"):
            if file_path.is_file():
                file_path.unlink()

        # remove dirs
        path = Path(settings.TMP_DOCS + settings.PROCESSED_DIR)
        path.rmdir()

        docs_path.rmdir()
        code_path.rmdir()
        tmp_dir.rmdir()

    def is_dir_not_empty(self, path: Path):
        """
        Check if the specified path directory is empty

        TODO: Move this to a directory utils class or something along with the cleanup / create tmp directories
        """

        if not path.is_dir():
            raise Exception("Invalid directory path specified")

        return any(path.iterdir())
    


    def _chunk_docs(self, data_source: DataSource, project_id: UUID, docling_files: Iterator[ConversionResult]): 
        """
        Functionality to chunk docs via Dockling 

        Args:
            data_source (DataSource): data source we are ingesting docs for 
            project_id (UUID): Optional project to ingest docs for 
            docling_files (Iterator[ConversionResult]): converted docling files 
        """

        # retrieve projects corresponding to data soruce 
        projects = [record.project for record in data_source.project_data] if not project_id else [project_id]

        # iterate through each project
        for project in projects:

            # get EmbeddingManger 
            embedding_manager = EmbeddingManager(project.model_configs)

            chunker = HybridChunker(
                tokenizer=embedding_manager.get_docs_tokenizer(),
            )

            

            # TODO: Store chunked docs in ChromaDB


    def _store_chunked_files_in_chroma(self, source_type):
        """
        Store chunked files in ChromaDB

        Args:
            source_type (str): either docs or code
        """
        return None

