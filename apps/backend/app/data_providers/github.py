from __future__ import annotations
import logging
import re
import asyncio
from uuid import UUID
from pathlib import Path
import httpx
from io import BytesIO

from .base import DataProvider
from app.core import settings
from app.pydantic import File, FileProcesingStatus
from app.models.data_source import DataSource
from app.services.file import FileService


logger = logging.getLogger(__name__)

 
class GithubDataProvider(DataProvider):

    def __init__(self, data_source: DataSource, job_pk: UUID, file_svc: FileService):
        super().__init__(data_source, job_pk, file_svc)
        self._validate_url()

        # deconstruct URL 
        parsed_url = self.url.split("/")
        self.repository_user = parsed_url[3]
        self.repository_name = parsed_url[4]
        self.branch_name = data_source.branch

        self.base_api_url = f"https://api.github.com/repos/{self.repository_user}/{self.repository_name}/contents"
        self.branch_reference = f"?ref={self.branch_name}"
        
        self.file_download_base_url = f"https://raw.githubusercontent.com/{self.repository_user}/{self.repository_name}/{self.branch_name}"

    async def ingest_data(self):
        """
        Functionality to parse our GitHub Url and invoke relevant functionality
        to DFS through repository and retrieve relevant files to store within our
        temporary directory to be stored by Chroma DB
        """

        # reach out to GitHub and recurisvely fetch and store documentation within our temp directory
        root_url = f"{self.base_api_url}{self.branch_reference}"
        await self._get_repository_data(root_url)

        # cleanup any files assocaited with DataSource not processed via current job
        await self.file_svc.cleanup(self.data_source.id, self.job_pk)


    def _get_request_headers(self) -> dict[str, str] | None:
        """
        Get headers for current Data Provider
        """

        return (
            {"Authorization": f"token {settings.GITHUB_SECRET_TOKEN}"}
            if settings.GITHUB_SECRET_TOKEN
            else None
        )


    def _validate_url(self):
        """
        Validate the given URL corresponds to the expected Data Provider
        """

        pattern = r"^https:\/\/github.com\/([^\/]+)\/([^\/]+)$"
        if not re.match(pattern, self.url):
            raise Exception(
                f"The specified data source URL, {self.url}, is not in the proper format: https://github.com/<user>/<repository>"
            )

    async def _get_repository_data(self, curr_url):
        """
        Functionality to recurisvely download files from the specified repository

        TODO: Look into handling private GitHub repositories

        TODO: Consider making the "get_repo_data" function more generic for BitBucket re-use

        Args:
            curr_url (str) - current URL to retrieve content from
        """

        # make request to retrieve content from specific directory
        content = None
        try:
            # make async request to curr URL 
            async with httpx.AsyncClient() as client:
                response = await client.get(curr_url, headers=self.request_headers)
                response.raise_for_status()
                content = response.json()
        except Exception as e:
            logger.error(
                f"Failure while attempting to retrieve data from the URL {curr_url}"
            )
            raise e
        
        # iterate through nodes in response
        for node in content:

            # download file and put into temp directory
            if node["type"] == "file":
                await self._download_file(node["download_url"], node["name"], node["path"], node["size"])
            else:
                # recursively download files in specificied directory
                await self._get_repository_data(node["url"])


    async def _download_file(self, url: str, file_name: str, file_path: str, size: int):
        """
        Helper function to download a file and store within relevant temporary directory

        """

        # ensure valid file name
        if not file_name or "." not in file_name:
            logger.warning(
                f"Skipping attempt to download file from URL={url} and file_name={file_name}"
            )
            return

        # ensure valid file type
        file_extension = file_name.split(".")[-1]

        file_type = ""
        if file_extension in settings.CODE_FILE_EXTENSIONS:
            file_type = "CODE"
        elif file_extension in settings.DOCS_FILE_EXTENSIONS:
            file_type = "DOCS"
        else:
            logger.warning(
                f"File extension {file_extension} not a valid Docs / Code file extension, skipping download"
            )
            return

        try:
            # retrieve file from specific URL asynchronously
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.request_headers)
                response.raise_for_status()

            # hash file content & store in buffer 
            buffer = BytesIO()
            hashed_content = await asyncio.to_thread(self.file_svc.hash_file_content, response, buffer)

            # determine file status 
            file = File(
                path=file_path, 
                file_name=file_name, 
                file_type=file_extension, 
                size=size, 
                hash=hashed_content,
                file_url=url
            )
            file_status = await self.file_svc.process_file(file, self.data_source, self.job_pk)

            # skip files already processed & unchanged 
            if file_status == FileProcesingStatus.UNCHANGED:
                return 

            # write file to temporary directory if needed
            dir = f"{settings.TMP_DOCS}/{self.job_pk}" if file_type == "DOCS" else f"{settings.TMP_CODE}/{self.job_pk}"
            
            # create parent directories if they don't exist
            full_path = Path(f"{dir}/{file_path}")
            
            await asyncio.to_thread(self._write_file, full_path, buffer)

        except Exception as e:
            logger.error(f"Failure downloading file={file_path} with exception={str(e)}")
            raise Exception(
                f"Failure occurred while attempt to download file: {file_name}", e
            )
    
    def _write_file(self, full_path: Path, buffer: BytesIO):
        """Sync helper: write buffered content to disk (runs in worker thread)."""

        """ TODO: This can get expensive in terms of memory when we read the entire file into Buffer
        Consider alternative approach for iterating through chunks of response without storing in memory 
        while still being able to Hash
        """
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(buffer.getbuffer())
   

    async def view_file(self, file_path: str) -> str:
        """
        View the contents of a particular file based on it's absolute path 

        Args:
            file_path (str): The absolute path to the file to view 
        """


        try:
            # build url to retrieve data
            url = f"{self.file_download_base_url}/{file_path}"

            # make async request to retrieve data
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.request_headers)
                response.raise_for_status()

                return response.text

        except Exception as e:
            logger.error(f"Failure viewing file={file_path} with exception={str(e)}")
            raise Exception(
                f"Failure occurred while attempt to view file: {file_path}", e
            )

        

    async def list_directory(self, path: str) -> str:
        """
        List the contents of a directory

        Args:
            path (str): The absolute path to the directory to list the contents of 
                - NOTE: should contain prefixed "/" if not root directory
        """
        
        content = None 

        try:
            # build url to retrieve data
            url = f"{self.base_api_url}{path}{self.branch_reference}"

            # retrieve file from specific URL asynchronously
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.request_headers)
                response.raise_for_status()

                content = response.json() 

            # iterate over nodes in response and extract file / directory names 
            path_contents = [f"Contents of {path}:"]
            for node in content:

                # determine if the node is a directory or a file 
                if node['type'] == 'dir':
                    path_contents.append(f"{node['name']}/")
                else:
                    path_contents.append(f"{node['name']}")
            

            # return back contents of path 
            return "\n".join(path_contents)

        except Exception as e:
            logger.error(f"Failure listing directory={path} with exception={str(e)}")
            raise Exception(
                f"Failure occurred while attempt to list directory: {path}", e
            )
        




            