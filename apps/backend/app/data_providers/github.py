from .base import DataProvider
import re 
from app.core import settings
import requests
import logging
import uuid

class GithubDataProvider(DataProvider):

    def __init__(self, url = ""):
        super().__init__(url)

    def ingest_data(self):
        """
        Functionality to parse our GitHub Url and invoke relevant functionality
        to DFS through repository and retrieve relevant files to store within our 
        temporary directory to be stored by Chroma DB 

        TODO: GitHub repositories may contain a /docs folder or some README files. These should 
        be stored within our docs collection 
        """
        
        # validate GitHub repository is specified 
        self._validate_url() 

        # extract user and repostiroy name from URL
        url_parts = self.url.split("/")
        user = url_parts[3]
        repository = url_parts[4]

        # reach out to GitHub and recurisvely fetch and store documentation within our temp directory 
        self._get_repository_data(f"https://api.github.com/repos/{user}/{repository}/contents?ref=main")
    

    def _get_request_headers(self):
        """
        Get headers for current Data Provider
        """

        return {'Authorization': f'token {settings.GITHUB_SECRET_TOKEN}'} if settings.GITHUB_SECRET_TOKEN else {}


    def _validate_url(self):
        """
        Validate the given URL corresponds to the expected Data Provider
        """

        pattern = r"^https:\/\/github.com\/([^\/]+)\/([^\/]+)$" 
        if not re.match(pattern, self.url):
            raise Exception(f'The specified data source URL, {self.url}, is not in the proper format: https://github.com/<user>/<repository>')
        
        
    def _get_repository_data(self, curr_url: str):
        """
        Functionality to recurisvely download files from the specified repository 

        TODO: Look into doing these reuqests async

        TODO: Look into handling private GitHub repositories 

        TODO: Consider making the "get_repo_data" function more generic for BitBucket re-use

        Args:
            url (str) - current URL to retrieve content from 
            headers (dict) - relevant headers to make request
        """

        # make request to retrieve content from specific directory 
        content = None
        try:
            response = requests.get(curr_url, headers=self.request_headers)
            response.raise_for_status()
            content = response.json() 
        except Exception as e:
            logging.error(f'Failure while attempting to retrieve data from the URL {curr_url}')
            raise e
        

        # iterate through nodes in response
        for node in content: 
            
            # download file and put into temp directory
            if node['type'] == "file":
                self._download_file(node['download_url'], node['name'])
            else:
                # recursively download files in specificied directory 
                self._get_repository_data(node['url'])

    

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
            response = requests.get(url, stream=True, headers=self.request_headers)
            response.raise_for_status() 

            # write file to temporary directory 
            dir = settings.TMP_DOCS if file_type == "DOCS" else settings.TMP_CODE
            temp_file_name = f"{dir}/file_{str(uuid.uuid4())}" 

            with open(temp_file_name, 'wb') as f:
                for chunk in response.iter_content(8192):
                    f.write(chunk)


        except Exception as e:
            raise Exception(f"Failure occurred while attempt to download file: {file_name}")