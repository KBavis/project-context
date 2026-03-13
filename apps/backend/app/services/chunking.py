from sqlalchemy.ext.asyncio import AsyncSession
from sentence_transformers import CrossEncoder

from llama_index.core.schema import NodeWithScore
from llama_index.vector_stores.chroma import ChromaVectorStore # type: ignore
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core import VectorStoreIndex
from llama_index.core.node_parser import CodeSplitter
from llama_index.core.readers import SimpleDirectoryReader
from llama_index.vector_stores.chroma import ChromaVectorStore # type: ignore
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode

from app.services.chroma import ChromaService
from app.core import DOCS, CODE, settings
from app.embeddings import EmbeddingManager
from app.models.collection import ChromaCollection
from app.models.data_source import DataSource
from app.embeddings import EmbeddingManager
from app.services.util import get_normalized_project_name

from docling_core.transforms.chunker.doc_chunk import DocChunk, DocMeta
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling.datamodel.document import ConversionResult

from collections import defaultdict
import logging
from typing import Any
from uuid import UUID
import asyncio

logger = logging.getLogger(__name__)

class ChunkingService:
    def __init__(self, db: AsyncSession, chroma_svc: ChromaService):
        self.db: AsyncSession = db
        self.chroma_svc: ChromaService = chroma_svc



    async def retrieve_chunks_by_decomposition(
        self, 
        decomposition: dict[str, Any], 
        project_id: UUID,
        original_query: str
    ) -> list[NodeWithScore]:
        """
        Retrieve chunks by the decompositon of the User's Query 

        Args:
            decomposition (dict[str, Any]): The decomposition of the User's Query
            project_id (UUID): The project the query corresponds to
            original_query (str): The original query the user passed in

        Returns:
            list[NodeWithScore]: The chunks retrieved by the decomposition
        """

        if not decomposition['requires_retrieval']:
            return []

        # retrieve all chunks for each query (decomposition of users original query)
        chunks_by_type: dict[str, list[NodeWithScore]] = {
            CODE: [],
            DOCS: []
        }

        for item in decomposition['queries']:
            logger.info(f"Retrieving chunks for query: {item['query']} from collections: {item['collections']}")

            # Case-insensitive check to be safe
            collections_upper = [c.upper() for c in item['collections']]
            needs_code = CODE in collections_upper
            needs_docs = DOCS in collections_upper
            
            query_chunks = await self.get_relevant_chunks(
                query=item['query'], 
                project_id=project_id, 
                needs_docs=needs_docs, 
                needs_code=needs_code
            )

            logger.info(f"Retrieved {len(query_chunks.get(CODE, []))} code chunks and {len(query_chunks.get(DOCS, []))} doc chunks for sub-query")
            chunks_by_type[CODE].extend(query_chunks.get(CODE, []))
            chunks_by_type[DOCS].extend(query_chunks.get(DOCS, []))
        

        logger.debug(f"Chunks retrieved based on decomposition:\nCODE CHUNKS:\n\t{chunks_by_type[CODE]}\nDOC CHUNKS:\n\t{chunks_by_type[DOCS]}")
            

        # deduplicate chunks 
        deduplicated_chunks = await self.deduplicate_chunks_by_type(chunks_by_type)

        # rank chunks 
        ranked_chunks = await self.get_rankings(
                chunks=deduplicated_chunks,
                query=original_query,
                top_k=5 # TODO: Make this a configuration 
            )

        # return ranked chunks 
        return ranked_chunks


    async def get_relevant_chunks(
        self, 
        query: str, 
        project_id: UUID, 
        needs_docs: bool = True, 
        needs_code: bool = True
    ) -> defaultdict[str, list[NodeWithScore]]: 
        """
        Retrieve relevant code and documentation chunks from Chroma based on the query and project ID.

        Args:
            query (str): user passed in query 
            project_id (UUID): the project the query corresponds to 
        """


        # retreive relevant Chroma Collections corresponding to Project 
        collections = self.chroma_svc.get_collections_by_project(project_id)
        if not collections:
            raise Exception(f"No ingested data found for Project ID: {project_id}")

        collections_by_type = {collection.content_type: collection for collection in collections}
        if CODE not in collections_by_type or DOCS not in collections_by_type:
            raise Exception(f"Both Code and Documentation collections must be present for Project ID: {project_id}")
        
        # Create embedding manager with project_id for caching
        embedding_manager = EmbeddingManager(collections_by_type, project_id=project_id)

        # load required embedding models (with caching)
        embedding_docs = None
        embedding_code = None

        if needs_docs:
            embedding_docs = await embedding_manager.aget_embedding_model_cached(DOCS)
        if needs_code:
            embedding_code = await embedding_manager.aget_embedding_model_cached(CODE)

        # determine which retrieval tasks are required 
        fetch_tasks: dict[str, Any] = {} 
        if needs_docs and embedding_docs:
            fetch_tasks[DOCS] = self._get_chunks(
                query=query,
                collection=collections_by_type[DOCS],
                embedding=embedding_docs
            )
        if needs_code and embedding_code:
            fetch_tasks[CODE] = self._get_chunks(
                query=query,
                collection=collections_by_type[CODE],
                embedding=embedding_code
            )
    
        # execute retrieval tasks in parallel 
        keys = list(fetch_tasks.keys())
        results = await asyncio.gather(*fetch_tasks.values())
        
        # organize results by type 
        chunks: defaultdict[str, list[NodeWithScore]] = defaultdict(list)
        for key, result in zip(keys, results):
            chunks[key] = result

        return chunks


    async def deduplicate_chunks_by_type(
        self, 
        chunks_by_type: dict[str, list[NodeWithScore]]
    ) -> dict[str, list[NodeWithScore]]:
        """
        Deduplicate chunks based on their content.

        Args:
            chunks_by_type (dict[str, list[NodeWithScore]]): The chunks to deduplicate
        """

        # deduplicate doc chunks 
        for content_type in [DOCS, CODE]:

            chunks = chunks_by_type.get(content_type, [])
            unique_chunk_ids = set()
            unique_chunks = []
            
            for curr_chunk in chunks:
                if curr_chunk.id_ not in unique_chunk_ids:
                    logger.debug(f"Deduplicated chunk: {curr_chunk.id_}")
                    unique_chunk_ids.add(curr_chunk.id_)
                    unique_chunks.append(curr_chunk)
                else:
                    logger.debug(f"Duplicate chunk: {curr_chunk.id_}")
            
            chunks_by_type[content_type] = unique_chunks
        
        return chunks_by_type
    

    async def get_rankings(self, chunks: dict[str, list[NodeWithScore]], query: str, top_k: int = 5) -> list[NodeWithScore]:
        """
        Rank code and documentation chunks based on relevance to query 

        Args:
            code_chunks (list): List of code chunks to rank.
            doc_chunks (list): List of documentation chunks to rank.
        """

        logger.debug(f"Ranking top {top_k} chunks for query: {query}")

        # initialize cross encoder model 
        cross_encoder = await asyncio.to_thread(self._get_cross_encoder, settings.CROSS_ENCODING_MODEL)

        # construct pairs for cross encoder scoring
        all_chunks = chunks.get(CODE, []) + chunks.get(DOCS, [])
        pairs = [[query, chunk.get_content()] for chunk in all_chunks]

        # score & sort pairs 
        scores = cross_encoder.predict(pairs)
        scored_nodes = list(zip(all_chunks, scores))
        scored_nodes.sort(key=lambda x: x[1], reverse=True)

        # log re-ranked nodes for debugging
        logger.debug(f"Top ranked chunks after re-ranking: \n")
        for i, chunk in enumerate(scored_nodes):
            logger.debug(f"\tRanked Chunk {i+1}: Score={chunk[1]}, Text={chunk[0].node.get_content()}")

        return [node for node, score in scored_nodes[:top_k]]


    def _get_cross_encoder(self, model_name: str) -> CrossEncoder:
        """
        Retrieve CrossEncoder configured in configurations in a seperate worker thread 
        in order to no block main thread with long I/O process

        TODO: Cache this model for performance gains 

        Args:
            modeL_name (str): the name of the cross encoding model 
        """
        try:

            return CrossEncoder(model_name)
        
        except Exception as e:
            logger.error(f"Failure occurred while downloading the following CrossEncoder: {model_name}", exc_info=True) 
            raise e

    ##############################################################################
    ########### START OF INGESTION JOB CHUNKING LOGIC#############################
    ##############################################################################

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
        nodes = await self.chunk_code(data_source, project_id, job_pk)

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
    


    async def _get_chunks(
        self, 
        query: str, 
        collection: ChromaCollection, 
        embedding: BaseEmbedding
    ) -> list[NodeWithScore]:
        """
        Retrieve chunks directly from ChromaDB based on the query and specified collection

        Args:
            query (str): user passed in query
            collection (ChromaCollection): the Chroma collection to query against
            embedding: the LlamaIndex embedding model to use for querying
        """

        # get actual Chroma Collection 
        chroma_collection = self.chroma_svc.get_real_chroma_collection(collection_name=collection.name)

        # configure LlamaIndex retriever from Chroma collection 
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store, embed_model=embedding) # pass embed_model explicitly to avoid race conditions with global Settings
        retriever = index.as_retriever(similarity_top_k=5) # TODO: Make this configurable 

        # retrieve relevant chunks from collection
        nodes = await retriever.aretrieve(query)

        logger.debug(f"Retrieved {len(nodes)} chunks from collection {collection.name} for query: {query}")

        return nodes 


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