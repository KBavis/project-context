from app.services.chroma import ChromaService
from app.services.ranking import RankingService
from app.core.constants import DOCS, CODE
from app.embeddings import EmbeddingManager

from sqlalchemy.ext.asyncio import AsyncSession


class QueryService:
    
    def __init__(
        self,
        db: AsyncSession,
        chroma_svc: ChromaService,
        ranking_svc: RankingService
    ):
        self.db = db
        self.chroma_svc = chroma_svc
    

    async def execute_simple_query(self, query: str, project_id: str):
        """
        Execute a one-time query against the ingested documentation and code for a specified Project

        NOTE: This is a placeholder implementation. Down the line, relevant logic will be setup 
        to create a Converation and have multiple interactions with the LLM in one singular session.

        Args:
            query (str): The query string to execute.
            project_id (str): The ID of the Project to query against.
        """

        doc_chunks, code_chunks = await self.get_relevant_chunks(query, project_id)

        re_ranked_chunks = await self.ranking_svc.get_rankings(
            code_chunks=code_chunks,
            doc_chunks=doc_chunks,
            query=query,
            top_k=5 # TODO: Make this a configuration 
        )



        

    async def get_relevant_chunks(self, query, project_id): 
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
        

        embedding_manager = EmbeddingManager(collections_by_type)

        # TODO: Call _get_chunks concurrentyl for both DOCS and CODE collections  

    

    async def _get_chunks(self, query, collection, embedding):
        """
        Retrieve relevant documentation chunks from Chroma based on the query.

        Args:
            query (str): user passed in query
            collection (ChromaCollection): the Chroma collection to query against
            embedding: the LlamaIndex embedding model to use for querying
        """


        # TODO: 1) Setting Settings.embed_model to llama index embeding, 2) Get ChromaStore based on "actual" chroma collection, 3) load existing index uisng Chroma store, 4) use index as retriever, 5) get nodes using passed in query 
    

        

        

    
    

