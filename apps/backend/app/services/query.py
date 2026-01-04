from app.services.chroma import ChromaService
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DOCS, CODE

class QueryService:
    
    def __init__(
        self,
        db: AsyncSession,
        chroma_svc: ChromaService   
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

        # retreive relevant Chroma Collections corresponding to Project 
        collections = self.chroma_svc.get_collections_by_project(project_id)
        if not collections:
            raise Exception(f"No ingested data found for Project ID: {project_id}")

        collections_by_type = {collection.content_type: collection for collection in collections}
        if CODE not in collections_by_type or DOCS not in collections_by_type:
            raise Exception(f"Both Code and Documentation collections must be present for Project ID: {project_id}")
        

        # TODO: Remove me 
        return {"query": query, "project_id": project_id, "status": "success"}
        

