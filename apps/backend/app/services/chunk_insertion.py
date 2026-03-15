from sqlalchemy.ext.asyncio import AsyncSession

from llama_index.vector_stores.chroma import ChromaVectorStore # type: ignore
from llama_index.core import VectorStoreIndex
from llama_index.core.node_parser import CodeSplitter
from llama_index.core.readers import SimpleDirectoryReader
from llama_index.vector_stores.chroma import ChromaVectorStore # type: ignore
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode

from app.services.chroma import ChromaService
from app.core import DOCS, CODE, settings
from app.embeddings import EmbeddingManager
from app.models.data_source import DataSource
from app.models.project import Project
from app.services.file import FileService
from app.services.util import get_normalized_project_name

from docling_core.transforms.chunker.doc_chunk import DocChunk, DocMeta
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling.datamodel.document import ConversionResult
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.exceptions import ConversionError
from docling.pipeline.threaded_standard_pdf_pipeline import ThreadedStandardPdfPipeline
from docling.datamodel.pipeline_options import ThreadedPdfPipelineOptions
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions

from pathlib import Path
from collections import defaultdict
import logging
from typing import Any
from uuid import UUID
import asyncio
from collections.abc import Iterator

logger = logging.getLogger(__name__)

class ChunkInsertionService:
    """
    Service class responsible for chunking and storing data within ChromaDB collection during file Ingestion 
    """

    def __init__(self, db: AsyncSession, chroma_svc: ChromaService, file_svc: FileService):
        self.db: AsyncSession = db
        self.chroma_svc: ChromaService = chroma_svc
        self.file_svc: FileService = file_svc

    async def code_chunk_and_store(
            self, 
            data_source: DataSource, 
            project_id: UUID | None, 
            job_pk: UUID
    ):
        """
        Functionality to Chunk ingested code files and store them within Chroma DB collection

        Args:
            data_source (DataSource): the data source corresponding to current ingestion job 
            project_id (Optional[UUID]): optional specified proejct to run ingestion job for 
            job_pk (UUID): pk of current ingesetion job
        """
        logger.info(f"Chunking and storing downloaded Code files")

        # chunk & convert relevant code files (using CodeSplitter from LlamaIndex)
        nodes = await self.chunk_code(data_source, project_id, job_pk)

        # save LlamaIndex nodes to ChromaDB collection
        await asyncio.to_thread(
            self._save_to_chroma, 
            nodes, 
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
        Convert downloaded Documentation files to Docling files, chunk using Docling's HybridChunker,
        convert to LlamaIndex TextNodes & store in relevant Chroma DB collection

        TODO: Setup router for determining if we should leverage Docling or LlamaIndex for chunking 
                - Docling for PDF/DOCX & then LlamaIndex for alternative types 


        Args:
            data_source (DataSource): the data source corresponding to current ingestion job
            project_id (Optional[UUID]): optional specified project to run ingestion job for 
            job_pk (UUID): pk of current ingesetion job
        """

        logger.info(f"Converting, chunking, and storing downloaded Documentation")

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
            data_source
        )

        logger.info(f"Succesfully converted, chunked, and stored downloaded Documentation files")

    async def _convert_to_text_nodes(
        self, 
        chunks: dict[str, list[dict[str, Any]]], 
        data_source_id: UUID
    ) -> dict[str | UUID, list[TextNode]]:
        """
        Convert Docling chunks to TextNodes in order to store within ChromaDB 

        Args:
            chunks (dict): mapping of a Project to a list of Docling chunks for relevant ingested Documents 
        """
        project_nodes: dict[str | UUID, list[TextNode]] = {}

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

    async def chunk_code(
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
            embedding_manager = EmbeddingManager(project.chroma_collection)
            chunker = HybridChunker(
                tokenizer=embedding_manager.get_tokenizer(), 
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
    

    def _save_to_chroma(self, project_chunks: dict[str | UUID, list[TextNode]],  data_source: DataSource) -> None: 
        """
        Save context-rich ingested documentation and code to our relevant Chroma collections based on Projects 
        this ingested job is being ran for 

        Args:
            project_chunks (dict): relevant chunked docs/code 
            data_source (DataSource): data source we are ingesting docs for 
        """
        
        # create mapping of project name to Project model 
        project_mapping = {record.project.project_name: record.project for record in data_source.project_data} 

        for project, nodes in project_chunks.items():

            # get Project model 
            curr_project = project_mapping[str(project)]

            # get embedding manager for project
            embedding_manager = EmbeddingManager(curr_project.chroma_collection)

            # retrieve Chroma DB collection 
            collection = self.chroma_svc.get_real_chroma_collection(
                f"{get_normalized_project_name(str(project))}"
            )

            # get chroma vector store corresponding to our projects DOCS collection
            vector_store = ChromaVectorStore(chroma_collection=collection)
            storage_context = StorageContext.from_defaults(vector_store=vector_store)

            # store nodes within Chroma 
            _ = VectorStoreIndex(
                nodes=nodes, # NOTE: Instead of using LlamaIndex's Document object, we will use our manually generated nodes
                storage_context=storage_context,
                embed_model=embedding_manager.get_embedding_model() # use configured embedding model for current Project
            )

            # TODO: Update ChromaDB Collection with Document Count OR Remove Doc Count entirely from DB 

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