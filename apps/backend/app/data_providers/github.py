import logging
import re
import requests
from io import BytesIO

from .base import DataProvider
from app.core import settings
from app.pydantic import File
from app.files import FileProcesingStatus


logger = logging.getLogger(__name__)


class GithubDataProvider(DataProvider):

    def __init__(self, file_service, data_source, job_pk, url: str = "", branch: str = "main"):
        super().__init__(file_service, data_source, job_pk, url)
        self._validate_url()

        # deconstruct URL 
        parsed_url = self.url.split("/")
        self.repository_user = parsed_url[3]
        self.repository_name = parsed_url[4]
        self.branch_name = branch
        self.repository_url = f"https://api.github.com/repos/{self.repository_user}/{self.repository_name}/contents?ref={self.branch_name}"

    def ingest_data(self):
        """
        Functionality to parse our GitHub Url and invoke relevant functionality
        to DFS through repository and retrieve relevant files to store within our
        temporary directory to be stored by Chroma DB

        TODO: GitHub repositories may contain a /docs folder or some README files. These should
        be stored within our docs collection
        """

        # reach out to GitHub and recurisvely fetch and store documentation within our temp directory
        self._get_repository_data(self.repository_url)

        # cleanup any files assocaited with DataSource not processed via current job
        self.file_handler.cleanup(self.data_source.id, self.job_pk)

    def _get_request_headers(self):
        """
        Get headers for current Data Provider
        """

        return (
            {"Authorization": f"token {settings.GITHUB_SECRET_TOKEN}"}
            if settings.GITHUB_SECRET_TOKEN
            else {}
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

    def _get_repository_data(self, curr_url):
        """
        Functionality to recurisvely download files from the specified repository

        TODO: Look into doing these reuqests async

        TODO: Look into handling private GitHub repositories

        TODO: Consider making the "get_repo_data" function more generic for BitBucket re-use

        Args:
            curr_url (str) - current URL to retrieve content from
        """

        # make request to retrieve content from specific directory
        content = None
        try:
            response = requests.get(curr_url, headers=self.request_headers)
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
                self._download_file(node["download_url"], node["name"], node["path"], node["size"])
            else:
                # recursively download files in specificied directory
                self._get_repository_data(node["url"])

    def _download_file(self, url: str, file_name: str, file_path: str, size: int):
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
            # retrieve file from specific URL
            response = requests.get(url, stream=True, headers=self.request_headers)
            response.raise_for_status()

            # hash file content & store in buffer 
            buffer = BytesIO()
            hashed_content = self.file_handler.hash_file_content(response, buffer)

            # determine file status 
            file = File(
                path=file_path, 
                file_name=file_name, 
                file_type=file_extension, 
                size=size, 
                hash=hashed_content
            )
            file_status = self.file_handler.process_file(file, self.data_source, self.job_pk)

            # TODO: Account for additional statuses that main indicate we can skip
            if file_status in {FileProcesingStatus.UNCHANGED, FileProcesingStatus.MOVED}:
                return 

            # write file to temporary directory if needed
            dir = settings.TMP_DOCS if file_type == "DOCS" else settings.TMP_CODE
            temp_file_name = f"{dir}/{self._get_file_name(url)}" 
            
            """
            TODO: This can get expensive in terms of memory when we read the entire file into Buffer
            Consider alternative approach for iterating through chunks of response without storing in memory 
            while still being able to Hash
            """
            with open(temp_file_name, "wb") as f:
                f.write(buffer.getbuffer())

        except Exception as e:
            logger.debug(f"Failure downloading file={file_name} with exception={str(e)}")
            raise Exception(
                f"Failure occurred while attempt to download file: {file_name}", e
            )
    


    def _get_file_name(self, url: str):
        """
        Helper function to retrieve the relevatn file name to store in temporary directory

        Args
            url (str) - download URL for the specified file
        """

        file_paths = url.split("/")
        if not file_paths:
            raise Exception(f"Invalid GitHub download URL specified: {url}")

        # find index of specified branch in download URL
        branch_idx = file_paths.index(self.branch_name)

        return "-".join(path for path in file_paths[branch_idx + 1 :])
