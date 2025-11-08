from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core import settings
from app.models import DataSource
from pathlib import Path
import logging
import re
import requests
import uuid


class IngestionJobService:
    def __init__(self, db: Session):
        self.db = db 
    

    def ingest_data(self, data_source_id):
        
        # retrieve data source 
        stmt = select(DataSource).where(DataSource.id == data_source_id)
        data_source = self.db.execute(stmt).scalar_one_or_none()

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

        # create temporary data directories
        docs_path = Path("tmp/docs")
        docs_path.mkdir()
        code_path = Path("/tmp/code")
        code_path.mkdir()


        # retrieve data differently based on provider & store within temp directory
        data = None
        match data_source.provider:
            case 'GitHub':
                data = self._fetch_github_repository_content(data_source.url)
            case _:
                logging.error(f"The specified Data Source provider is not configured for this application") 
        
        if not data:
            raise Exception('Failed to retrieve data from provider')


        # iterate through each file and chunk intelligently 

        # retrieve relevant projects corresponding to Data Source 


        # retrieve embedding 

        # use ChromaVectorStore to store 

        # remove temporary directory with retrieved files
        code_path.rmdir()
        docs_path.rmdir()
    

    def _fetch_github_repository_content(self, url: str): 
        """
        Functionality to parse our GitHub Url and invoke relevant functionality
        to DFS through repository and retrieve relevant files to store within our 
        temporary directory to be stored by Chroma DB 

        TODO: GitHub repositories may contain a /docs folder or some README files. These should 
        be stored within our docs collection 

        Args:
            url (str) - relevant URL 
        """
        
        # validate GitHub repository is specified 
        pattern = r"^https:\/\/github.com\/([^\/]+)\/([^\/]+)$" 
        if not re.match(pattern, url):
            raise Exception(f'The specified data source URL, {url}, is not in the proper format: https://github.com/<user>/<repository>')
        

        # extract user and repostiroy name from URL
        url_parts = url.split("/")
        user = url_parts[3]
        repository = url_parts[4]

        # reach out to GitHub and recurisvely fetch and store documentation within our temp directory 
        self._retrieve_repository_content(f"https://api.github.com/repos/{user}/{repository}/contents?ref=main")

        # store the files in the temporary directory to be ingested into Chroma DB 

    def _retrieve_repository_content(self, curr_url):
        """
        Functionality to recurisvely download files from the specified repository 

        TODO: Look into doing these reuqests async

        TODO: Look into handling private GitHub repositories 

        Args:
            url (str) - current URL to retrieve content from 
        """

        # make request to retrieve content from specific directory 
        content = None
        try:
            response = requests.get(curr_url)
            response.raise_for_status()
            content = response.json() 
        except Exception as e:
            raise Exception(f'Failure while attempting to retrieve data from the URL {curr_url}')
        

        # iterate through nodes in response
        for node in content: 
            
            # download file and put into temp directory
            if node['type'] == "file":
                self._download_file(node['download_url'], node['name'])
            else:
                # recursively download files in specificied directory 
                self._retrieve_repository_content(self, node['url'])

    

    def _download_file(self, url: str, file_name: str):
        """
        Helper function to download a file and store within relevant temporary directory
        """

        # ensure valid file name 
        if not file_name or "." not in file_name:
            logging.warning(f'Skipping attempt to download file from URL={url} and file_name={file_name}')
            return 

        # ensure valid file type          
        file_extension = file_name.split(".")[-1]  

        file_type = ""
        if file_extension in settings.CODE_FILE_EXTENSIONS:
            file_type = "CODE"
        elif file_extension in settings.DOCS_FILE_EXTENSIONS:
            file_type = "DOCS"
        else:
            logging.warning(f"File extension {file_extension} not a valid Docs / Code file extension, skipping download")
            return 


        try:
            # retrieve file from specific URL 
            response = requests.get(url, stream=True)
            response.raise_for_status()

            # write file to temporary directory 
            dir = "/tmp/docs" if file_type == "DOCS" else "/tmp/code"
            temp_file_name = f"{dir}/file_{str(uuid.uuid4())}" 

            with open(temp_file_name, 'wb') as f:
                for chunk in response.iter_content(8192):
                    f.write(chunk)


        except Exception as e:
            raise Exception(f"Failure occurred while attempt to download file: {file_name}")


                





    

        

