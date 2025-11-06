from sqlalchemy.orm import Session
from sqlalchemy import select
from models import DataSource
from pathlib import Path
import logging


class IngestionJobService:
    def __init__(self, db: Session):
        self.db = db 
    

    def ingest_data(self, data_source_id):
        
        # retrieve data source 
        data_source = select(DataSource).where(DataSource.id == data_source_id)

        if not data_source:
            raise Exception('Invalid specified Data Source ID to ingest data from')

        # use data source information to fetch relevant data & store in temp directory 
        self._retrieve_data(data_source)


        # retrieve chroma DB collection 

        # use relevant chunking mechanism based on content type 

        # use vector store index to ingest data 
        return None
    


    def _retrieve_data(self, data_source: DataSource):
        """
        Retrieve relevant data from specified Data Source and store within temporary /data directory 
        in order to be ingested into Chroma DB 

        NOTE: In future, we should make some sort of "diff" calculation each time we retreive data from data source 
        in order to quickly determine what's already been retireving before
        """

        # create temporary data directory 
        path = Path("tmp")
        path.mkdir()


        # retrieve data differently based on provider 
        data = None
        match data_source.provider:
            case 'GitHub':
                data = self._fetch_github_repository_content(data_source.url)
            case _:
                logging.error(f"The specified Data Source provider is not configured for this application") 
        

        if not data:
            raise Exception('Failed to retrieve ')
        

        # remove temporary directory with retrieved files
        path.rmdir()
    

    def _fetch_github_repository_content(self, url: str): 

        # extract 
    

        

