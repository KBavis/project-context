from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Citation
from app.services.file import FileService
from app.services.data_source import DataSourceService

class CitationService:
    def __init__(
        self, 
        db: AsyncSession,
        file_service: FileService,
        data_source_svc: DataSourceService
    ):
        self.db = db
        self.file_service = file_service
        self.data_source_svc = data_source_svc
    

    async def get_citations(self, nodes: list[Node]) -> list[Citation]:
        """
            Retrieves the citations for a list of nodes 
                - creates new citations for relevant files if doesn't exist 
                - retrieves existing citations for files that already have them
        """
        citations = []

        for node in nodes: 
            
            # TODO: check if citation exists for this file by user file service functionality 
            # if it does, return it 
            # if it doesn't, create it and return it 

            if node.metadata and node.metadata.get("data_source_id"):

                # get url by data source ID 
                data_source_id = node.metadata.get("data_source_id")
                data_source = await self.data_source_svc.get_data_source_by_id(data_source_id)

                file_name = node.metadata.get("file_path", node.metadata.get("source"))
                if not file_name:
                    raise Exception(f"Unable to extract file path from node={node.id_} when generating Citation")
                
                # clean file name (/app/tmp/<TYPE>/<JOBPK>/filename --> filename)
                if file_name.startswith("/app/tmp/"): 
                    split_url = file_name.split("/")
                    file_name= "/".join(split_url[4:])
                
                # complete URL 
                url = f"{data_source.url}/{file_name}"

                # TODO: generate Citation record and persist to database 


        return citations
        


    async def create_citation(self, file_id: UUID, url: str) -> Citation:

        # TODO: create citation record and persist to database 
        return Citation(
            url=url,
            file_id=file_id,
            node_id=node.id_
        )