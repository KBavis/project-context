import logging
from pathlib import Path
from datetime import datetime
from uuid import UUID
from typing import Tuple, Iterator, Dict, List

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import DataSource
from app.data_providers import GithubDataProvider
from app.core import settings
from app.embeddings import EmbeddingManager
from app.core import ChromaClientManager
from app.services.util import get_normalized_project_name

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.exceptions import ConversionError
from docling.pipeline.threaded_standard_pdf_pipeline import ThreadedStandardPdfPipeline
from docling.datamodel.pipeline_options import ThreadedPdfPipelineOptions
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.chunking import HybridChunker
from docling.datamodel.document import ConversionResult

from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode

logger = logging.getLogger(__name__)


class IngestionJobService:
    def __init__(self, db: Session, chroma_client_manager: ChromaClientManager):
        self.db = db
        self.chroma_mnger = chroma_client_manager

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

        # documentation files were ingested
        if has_docs:
            logger.info(f"IngestionJob for DataSource={data_source_id} has ingested relevant docs files; chunking & saving to ChromaDB")

            # convert docs to docling files 
            converted_files = self._convert_docs_files_to_docling()
            logger.debug(f'Converted files to Docling files')

            # chunk ingested documentation based on configured project embedding model
            project_chunks = self._chunk_docs(data_source, project_id, converted_files)
            logger.debug('Successfully chunked ingested documentation for each project')

            # convert docling project chunks to LlamaIndex TextNodes
            nodes = self._convert_to_text_nodes(project_chunks)

            # store results within Chroma DB, using embedding specified DataSource
            # self._save_to_chroma(nodes, "DOCS")

        # code files were ingested 
        if has_code:
            # TODO: Handle chunking and saving of Code files to Chroma DB 
            logger.info(f"IngestionJob for DataSource={data_source_id} has ingested relevant code files; chunking & saving to ChromaDB")


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
    

    def _convert_to_text_nodes(self, chunks: Dict) -> Dict[str, List[TextNode]]:
        """
        Convert Docling chunks to TextNodes in order to store within ChromaDB 

        Args:
            chunks (Dict): mapping of a Project to a list of Docling chunks for relevant ingested Documents 
        """
        project_nodes = {}

        for project, chunked_data in chunks.items():

            project_nodes[project] = []
            for data in chunked_data:
                logger.debug(f"Project={project}, DocChunk={data['doc_chunk'][:20]}, ContextChunk={data['contextualized_chunk'][:20]}")

                # TODO: Generate MetaData for TextNode and create TextNode with current chunked data 
        
        return project_nodes


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
            logger.info(f"Successfully converted ingested Documentation files to Docling files")
        except ConversionError as e:
            logger.error(f"Failed to convert all documents ingested", exc_info=True)
            raise e


        return conv_results


    def _save_to_chroma(self, project_chunks: dict, source_type: str): 
        """
        Save context-rich ingested documentation and code to our relevant Chroma collections based on Projects 
        this ingested job is being ran for 

        Args:
            project_chunks (dict): relevant chunked docs/code 
            source_type (str): the content type of the files being saved 
        """

        chroma_client = self.chroma_mnger.get_sync_client()

        for project in project_chunks:

            # retrieve Chroma DB collection 
            collection = chroma_client.get_collection(
                f"{get_normalized_project_name(project)}_{source_type}"
            )

            # get vector store 
            vector_store = ChromaVectorStore(chroma_collection=collection)
            storage_context = StorageContext.from_defaults(vector_store=vector_store)

            index = VectorStoreIndex.from_documents()

            #TODO: Finish me 



    
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
        if path.exists():
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
    


    def _chunk_docs(self, data_source: DataSource, project_id: UUID, conversion_results: Iterator[ConversionResult]) -> Dict: 
        """
        Functionality to chunk docs via Dockling 

        Args:
            data_source (DataSource): data source we are ingesting docs for 
            project_id (UUID): Optional project to ingest docs for 
            conversion_results (Iterator[ConversionResult]): converted docling files results
        """

        # retrieve projects corresponding to data soruce 
        projects = [record.project for record in data_source.project_data] if not project_id else [project_id]

        # generate mapping of project to relevant ingested documentation chunks 
        chunked_docs = {project.project_name: [] for project in projects}
        for project in projects:

            # get chunker based on configured embedding model for the current project
            embedding_manager = EmbeddingManager(project.model_configs)
            chunker = HybridChunker(
                tokenizer=embedding_manager.get_docs_tokenizer(), #TODO: Use Maximum Length of 512 for tokens
            )

            # iterate through converted Docling documents 
            for res in conversion_results:
                logger.debug(f'Conversion result confidence for Document={res.document.name} = {res.confidence}')

                # chunk current Docling document into DocChunk's
                curr_doc_chunks = list(chunker.chunk(dl_doc=res.document))

                # iterate through chunks in current document 
                for chunk in curr_doc_chunks:
                    chunked_docs[project.project_name].append(
                        {
                            "doc_chunk": chunk,
                            "contextualized_chunk": chunker.contextualize(chunk=chunk)
                        }
                    )

                
                



        return chunked_docs



    def _store_chunked_files_in_chroma(self, source_type):
        """
        Store chunked files in ChromaDB

        Args:
            source_type (str): either docs or code
        """
        return None

