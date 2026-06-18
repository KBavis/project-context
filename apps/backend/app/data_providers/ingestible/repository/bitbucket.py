from __future__ import annotations
import logging
import re
import asyncio
from uuid import UUID
from pathlib import Path
import httpx
from io import BytesIO
from datetime import datetime
import base64

from .base import RepositoryDataProvider
from app.core import settings
from app.pydantic import File, FileProcesingStatus, GitCommitDetail
from app.models.data_source import DataSource
from app.services.file import FileService

logger = logging.getLogger(__name__)

class BitbucketDataProvider(RepositoryDataProvider):

    def __init__(self, data_source: DataSource):
        super().__init__(data_source)

    def _parse_repository_ref(self) -> tuple[str, str]:
        parsed_url = self.url.rstrip("/").split("/")
        # URL format: https://<domain>/projects/<project>/repos/<repo_name>[/browse]
        try:
            projects_idx = parsed_url.index("projects")
            project = parsed_url[projects_idx + 1]
            repos_idx = parsed_url.index("repos")
            repo_name = parsed_url[repos_idx + 1]
            self.domain = parsed_url[2]
            return project, repo_name
        except ValueError:
            raise Exception(f"URL {self.url} does not match expected Bitbucket Server format: https://<domain>/projects/<project>/repos/<repo_name>")

    def _construct_base_urls(self):
        self.base_url = f"https://{self.domain}/projects/{self.repository_owner}/repos/{self.repository_name}/browse?at={self.branch_name}"
        self.base_api_url = f"https://{self.domain}/rest/api/1.0/projects/{self.repository_owner}/repos/{self.repository_name}"
        self.file_download_base_url = f"https://{self.domain}/projects/{self.repository_owner}/repos/{self.repository_name}/raw"

    async def ingest_data(self, file_svc: FileService, job_pk: UUID):
        self.file_svc = file_svc
        self.job_pk = job_pk

        if not self.file_svc or not self.job_pk:
            raise Exception("FileService and JobPK not provided when attempting to ingest data")

        # Reach out to Bitbucket and recursively fetch and store documentation within our temp directory
        await self._get_repository_data(self.base_api_url)

        # Cleanup any files associated with DataSource not processed via current job
        await self.file_svc.cleanup(self.data_source.id, self.job_pk)

    def _get_request_headers(self) -> dict[str, str] | None:
        if settings.BITBUCKET_USERNAME and settings.BITBUCKET_SECRET_TOKEN:
            auth_str = f"{settings.BITBUCKET_USERNAME}:{settings.BITBUCKET_SECRET_TOKEN}"
            b64_auth_str = base64.b64encode(auth_str.encode()).decode()
            return {"Authorization": f"Basic {b64_auth_str}"}
        elif settings.BITBUCKET_SECRET_TOKEN:
            return {"Authorization": f"Bearer {settings.BITBUCKET_SECRET_TOKEN}"}
        return None

    def _validate_url(self):
        if "/projects/" not in self.url or "/repos/" not in self.url:
            raise Exception(
                f"The specified data source URL, {self.url}, is not in the proper format: https://<domain>/projects/<project>/repos/<repo_name>"
            )

    async def _get_repository_data(self, curr_url: str):
        assert self.file_svc and self.job_pk

        # Bitbucket Server /files endpoint to get all files
        # E.g. /rest/api/1.0/projects/{proj}/repos/{repo}/files?at={branch}
        files_url = f"{self.base_api_url}/files?at={self.branch_name}&limit=10000"
        content = None
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(files_url, headers=self.request_headers)
                response.raise_for_status()
                content = response.json()
        except Exception as e:
            logger.error(f"Failure while attempting to retrieve data from the URL {files_url}")
            raise e
        
        values = content.get("values", [])
        for path in values:
            # Construct raw download url
            download_url = f"{self.file_download_base_url}/{path}?at={self.branch_name}"
            # File size isn't directly available in /files, so pass 0 (it will be computed when read)
            await self._download_file(download_url, Path(path).name, path, 0)
            
        # Handle pagination if necessary (though limit=10000 usually gets all)
        while not content.get("isLastPage", True):
            next_start = content.get("nextPageStart")
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{files_url}&start={next_start}", headers=self.request_headers)
                    response.raise_for_status()
                    content = response.json()
                    
                    for path in content.get("values", []):
                        download_url = f"{self.file_download_base_url}/{path}?at={self.branch_name}"
                        await self._download_file(download_url, Path(path).name, path, 0)
            except Exception as e:
                logger.error(f"Failure while attempting to retrieve paginated data")
                raise e

    async def _download_file(self, url: str, file_name: str, file_path: str, size: int):
        assert self.file_svc and self.job_pk

        if not file_name or "." not in file_name:
            logger.warning(f"Skipping attempt to download file from URL={url} and file_name={file_name}")
            return

        file_extension = file_name.split(".")[-1]

        file_type = ""
        if file_extension in settings.CODE_FILE_EXTENSIONS:
            file_type = "CODE"
        elif file_extension in settings.DOCS_FILE_EXTENSIONS:
            file_type = "DOCS"
        else:
            logger.warning(f"File extension {file_extension} not a valid Docs / Code file extension, skipping download")
            return

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.request_headers)
                response.raise_for_status()

            buffer = BytesIO()
            hashed_content = await asyncio.to_thread(self.file_svc.hash_file_content, response, buffer)

            file = File(
                path=file_path, 
                file_name=file_name, 
                file_type=self.file_svc.get_file_extension(file_extension), 
                size=size, 
                hash=hashed_content,
                file_url=url
            )
            file_status = await self.file_svc.process_file(file, self.data_source, self.job_pk)

            if file_status == FileProcesingStatus.UNCHANGED:
                return 

            dir = f"{settings.TMP_DOCS}/{self.job_pk}" if file_type == "DOCS" else f"{settings.TMP_CODE}/{self.job_pk}"
            full_path = Path(f"{dir}/{file_path}")
            
            await asyncio.to_thread(self._write_file, full_path, buffer)

        except Exception as e:
            logger.error(f"Failure downloading file={file_path} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempt to download file: {file_name}", e)

    async def view_file(self, file_path: str) -> str:
        try:
            url = f"{self.file_download_base_url}/{file_path}?at={self.branch_name}"
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.request_headers)
                response.raise_for_status()
                return response.text
        except Exception as e:
            logger.error(f"Failure viewing file={file_path} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempt to view file: {file_path}", e)

    async def list_directory(self, path: str) -> str:
        try:
            url = f"{self.base_api_url}/browse/{path}?at={self.branch_name}"
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.request_headers)
                response.raise_for_status()
                content = response.json() 

            path_contents = [f"Contents of {path or '/'}:"]
            for node in content.get("children", {}).get("values", []):
                if node['type'] == 'DIRECTORY':
                    path_contents.append(f"{node['path']['name']}/")
                else:
                    path_contents.append(f"{node['path']['name']}")
            
            return "\n".join(path_contents)
        except Exception as e:
            logger.error(f"Failure listing directory={path} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempt to list directory: {path}", e)

    async def generate_citation(self, path: str) -> str:
        try:
            return f"[{path}](https://{self.domain}/projects/{self.repository_owner}/repos/{self.repository_name}/browse/{path}?at={self.branch_name})"
        except Exception as e:
            logger.error(f"Failure generating citation for path={path} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempt to generate citation for path: {path}", e)

    async def get_latest_commit_sha(self, child_issues: list[str]) -> str | None:
        if not child_issues:
            raise Exception("Issue numbers must be provided to filter commits by")

        try:
            url = f"{self.base_api_url}/commits"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.request_headers)
                response.raise_for_status()
                commits = response.json()
                
                for item in commits.get("values", []):
                    message = item.get("message", "")
                    if any(issue in message for issue in child_issues):
                        return item["id"]
                
                return None
        except Exception as e:
            logger.error(f"Failure getting latest commit SHA with exception={str(e)}")
            raise Exception(f"Failure occurred while attempt to get latest commit SHA for repository: {self.full_name}", e)

    async def get_all_commits_info(self, child_issues: list[str], latest_commit_date: datetime | None = None) -> list[GitCommitDetail]:
        if not child_issues:
            raise Exception("Issue numbers must be provided to filter commits by")

        try:
            url = f"{self.base_api_url}/commits"
            commit_details = []
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.request_headers)
                response.raise_for_status()
                commits = response.json()
                
                for item in commits.get("values", []):
                    commit_date_ms = item["committerTimestamp"]
                    commit_date = datetime.fromtimestamp(commit_date_ms / 1000.0)
                    
                    if latest_commit_date and commit_date <= latest_commit_date:
                        continue
                        
                    message = item.get("message", "")
                    if any(issue in message for issue in child_issues):
                        sha = item["id"]
                        detail = await self.get_commit_detail(sha)
                        commit_details.append(detail)
                        
                return commit_details

        except Exception as e:
            logger.error(f"Failure getting all commits info with exception={str(e)}")
            raise Exception(f"Failure occurred while attempting to get all commits info for repository: {self.full_name}", e)

    async def get_commit_detail(self, sha: str) -> GitCommitDetail:
        url_commit = f"{self.base_api_url}/commits/{sha}"
        url_changes = f"{self.base_api_url}/commits/{sha}/changes"
        
        try:
            async with httpx.AsyncClient() as client:
                resp_commit = await client.get(url_commit, headers=self.request_headers)
                resp_commit.raise_for_status()
                commit_data = resp_commit.json()
                
                resp_changes = await client.get(url_changes, headers=self.request_headers)
                resp_changes.raise_for_status()
                changes_data = resp_changes.json()
                
                files_modified = []
                for item in changes_data.get("values", []):
                    if "path" in item:
                        files_modified.append(item["path"]["toString"])
                
                author_data = commit_data.get("author", {})
                author_name = author_data.get("displayName", "Unknown")
                author_email = author_data.get("emailAddress", "")
                
                commit_date_ms = commit_data["committerTimestamp"]
                commit_date = datetime.fromtimestamp(commit_date_ms / 1000.0)
                
                return GitCommitDetail(
                    sha=sha,
                    author_name=author_name,
                    author_email=author_email,
                    commit_datetime=commit_date,
                    message=commit_data.get("message", ""),
                    files_modified=list(set(files_modified))
                )
        except Exception as e:
            logger.error(f"Failure getting commit details for SHA={sha} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempting to get commit details for SHA {sha} in repository: {self.full_name}", e)
