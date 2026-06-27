from __future__ import annotations
import logging
import re
import asyncio
from uuid import UUID
from pathlib import Path
import httpx
from io import BytesIO
from datetime import datetime
from typing import TYPE_CHECKING

from .base import RepositoryDataProvider
from app.core import settings
from app.pydantic import File, FileProcesingStatus, GitCommitDetail
from app.pydantic.pull_request import PullRequestDetail
from app.pydantic.file_diff_patch import FileDiffPatch
from app.pydantic.change_type import ChangeType
from app.models.data_source import DataSource
from app.services.file import FileService

if TYPE_CHECKING:
    from app.data_providers.fetchable.issue_tracker.base import IssueTrackerDataProvider


logger = logging.getLogger(__name__)

 
class GithubDataProvider(RepositoryDataProvider):

    def __init__(self, data_source: DataSource):
        super().__init__(data_source)
    

    def _parse_repository_ref(self) -> tuple[str, str]:
        """
        Extract relevant information from the specified URL 

        Returns
            (repository_owner, repository_name)
        """

        parsed_url = self.url.split("/")

        owner = parsed_url[3]
        repo_name = parsed_url[4]

        return owner, repo_name
    

    def _construct_base_urls(self):

        self.base_url = f"https://github.com/{self.repository_owner}/{self.repository_name}/blob/{self.branch_name}/"
        self.base_api_url = f"https://api.github.com/repos/{self.repository_owner}/{self.repository_name}/contents"
        self.branch_reference = f"?ref={self.branch_name}"
        self.file_download_base_url = f"https://raw.githubusercontent.com/{self.repository_owner}/{self.repository_name}/{self.branch_name}"


    async def ingest_data(self, file_svc: FileService, job_pk: UUID):
        """
        Functionality to parse our GitHub Url and invoke relevant functionality
        to DFS through repository and retrieve relevant files to store within our
        temporary directory to be stored by Chroma DB
        """

        self.file_svc = file_svc
        self.job_pk = job_pk
        self.new_or_modified_file_ids = []

        if not self.file_svc or not self.job_pk:
            raise Exception(f"FileService and JobPK not provided when attempting to ingest data")

        # reach out to GitHub and recurisvely fetch and store documentation within our temp directory
        root_url = f"{self.base_api_url}{self.branch_reference}"
        await self._get_repository_data(root_url)

        # cleanup any files assocaited with DataSource not processed via current job
        await self.file_svc.cleanup(self.data_source.id, self.job_pk, self.new_or_modified_file_ids)


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

    async def _get_repository_data(self, curr_url: str):
        """
        Functionality to recurisvely download files from the specified repository

        TODO: Look into handling private GitHub repositories

        # TODO: Refactor this function to be more generic for re-use across BitBucket & GitHub  
        # (https://github.com/KBavis/contextualized/issues/42)

        Args:
            curr_url (str) - current URL to retrieve content from
        """
        assert self.file_svc and self.job_pk

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
                # enforce inclusive ingest_paths scoping
                if not self._is_in_ingest_paths(node["path"]):
                    continue

                # skip vendored/build/generated/fixture files before downloading them
                if self._is_excluded_path(node["path"]):
                    logger.debug(f"Skipping excluded file: {node['path']}")
                    continue
                await self._download_file(node["download_url"], node["name"], node["path"], node["size"])
            else:
                # prune traversal to scoped directories
                if self._should_descend(node["path"]):
                    await self._get_repository_data(node["url"])


    async def _download_file(self, url: str, file_name: str, file_path: str, size: int):
        """
        Helper function to download a file and store within relevant temporary directory

        """
        assert self.file_svc and self.job_pk

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
                file_type=self.file_svc.get_file_extension(file_extension), 
                size=size, 
                hash=hashed_content,
                file_url=url
            )
            file_status = await self.file_svc.process_file(file, self.data_source, self.job_pk, self.new_or_modified_file_ids)

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
    

    ############################################################
    ### Internal Tool Definitions For Ingestable Data Providers 
    ############################################################

    async def view_file(self, file_path: str) -> str:
        """
        View the contents of a particular file based on it's absolute path 

        Args:
            file_path (str): The absolute path to the file to view 
                Usage:
                    - file_path == "file.py" --> <REPO_HOME>/file.py
                    - file_path == "dir/file.py" --> <REPO_HOME>/dir/file.py
        """

        try:
            # Tolerate agent-supplied leading slashes; file_download_base_url has
            # no trailing slash, so a leading slash here yields a `//` 404.
            url = f"{self.file_download_base_url}/{file_path.lstrip('/')}"

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
                Usage: 
                    - path == "" --> root directory 
                    - path == "/app" --> app directory 
        """
        
        content = None 

        try:
            # base_api_url ends in `/contents` with no separator, so normalize the
            # path to exactly one leading slash (and none for the repo root).
            clean_path = path.strip("/")
            path_segment = f"/{clean_path}" if clean_path else ""
            url = f"{self.base_api_url}{path_segment}{self.branch_reference}"

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
        

    async def generate_citation(self, path: str) -> str:
        """
        Generate a citation for a particular file based on its absolute path. Returns
        the citation in markdown format so the Agent can properly format the citation in the Chat UI

        Args:
            path (str): The absolute path to the file to generate a citation for 
                - NOTE: should contain prefixed "/" (IF NOT ROOT DIRECTORY)
        """

        try:
            # base_url ends in a trailing slash, so strip any leading slash off the
            # path to avoid a `//` in the citation link.
            return f"[{path}]({self.base_url}{path.lstrip('/')})"
        except Exception as e:
            logger.error(f"Failure generating citation for path={path} with exception={str(e)}")
            raise Exception(
                f"Failure occurred while attempt to generate citation for path: {path}", e
            )
    

    async def resolve_prs(
        self,
        issue_keys: list[str],
        issue_provider: IssueTrackerDataProvider,
    ) -> list[PullRequestDetail]:
        """
        Resolve merged pull requests targeting this data source's branch whose
        source branch name (or title/body) references one of the supplied issue
        keys.

        ``issue_provider`` is accepted for interface parity with providers that
        delegate the issue<->pull-request lookup to the issue tracker (e.g.
        Bitbucket -> Jira); GitHub resolves the linkage itself and ignores it.

        TODO: This currently enumerates every closed pull request targeting the
        branch and matches client-side, which does not scale to large
        repositories. It should be updated to avoid iterating over every pull
        request ever opened (GitHub's ``head:`` search qualifier only does a
        prefix match on branch names, so it cannot match an issue key embedded
        mid-path in the branch — a different linkage strategy is needed).
        """
        if not issue_keys:
            return []

        needles = [key.lower() for key in issue_keys]
        repo_api = f"https://api.github.com/repos/{self.repository_owner}/{self.repository_name}"
        matched: list[PullRequestDetail] = []

        try:
            async with httpx.AsyncClient() as client:
                page = 1
                while True:
                    url = (
                        f"{repo_api}/pulls?state=closed&base={self.branch_name}"
                        f"&sort=updated&direction=desc&per_page=100&page={page}"
                    )
                    resp = await client.get(url, headers=self.request_headers)
                    resp.raise_for_status()
                    prs = resp.json()
                    if not prs:
                        break

                    for pr in prs:
                        if not pr.get("merged_at"):
                            continue  # closed but not merged
                        key = self._match_issue_key(pr, issue_keys, needles)
                        if not key:
                            continue
                        matched.append(await self._to_pull_request_detail(client, repo_api, pr, key))

                    if len(prs) < 100:
                        break
                    page += 1

            logger.info(
                "Resolved %d linked pull requests for %s matching issues %s",
                len(matched), self.full_name, issue_keys,
            )
            return matched
        except Exception as e:
            logger.error(f"Failure resolving pull requests with exception={str(e)}")
            raise Exception(
                f"Failure occurred while attempting to resolve pull requests for repository: {self.full_name}", e
            )

    def _match_issue_key(self, pr: dict, issue_keys: list[str], needles: list[str]) -> str | None:
        """
        Return the single child issue key this pull request references via its
        source branch name (primary signal) or title/body (safety net), or
        ``None`` when nothing matches. A pull request maps one-to-one to a child
        issue, so the first match wins.
        """
        head_ref = (pr.get("head") or {}).get("ref", "") or ""
        haystack = " ".join([
            head_ref,
            pr.get("title", "") or "",
            pr.get("body", "") or "",
        ]).lower()
        for key, needle in zip(issue_keys, needles):
            if needle in haystack:
                return key
        return None

    async def _to_pull_request_detail(
        self, client: httpx.AsyncClient, repo_api: str, pr: dict, issue_key: str
    ) -> PullRequestDetail:
        user = pr.get("user") or {}
        source_branch = (pr.get("head") or {}).get("ref", "") or ""
        target_branch = (pr.get("base") or {}).get("ref", "") or self.branch_name
        merged_at = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))

        return PullRequestDetail(
            pr_number=pr["number"],
            title=pr.get("title", "") or "",
            description=pr.get("body"),
            author_name=user.get("login") or "Unknown",
            author_email=None,
            source_branch=source_branch,
            target_branch=target_branch,
            merged_at=merged_at,
            issue_key=issue_key,
            url=pr.get("html_url"),
            commits=await self._fetch_pr_commits(client, repo_api, pr["number"]),
        )

    async def _fetch_pr_commits(
        self, client: httpx.AsyncClient, repo_api: str, pr_number: int
    ) -> list[GitCommitDetail]:
        """
        Fetch the non-merge commits contained in a pull request (descriptive
        metadata). Merge commits (parents > 1) are excluded.
        """
        commits: list[GitCommitDetail] = []
        page = 1
        while True:
            url = f"{repo_api}/pulls/{pr_number}/commits?per_page=100&page={page}"
            resp = await client.get(url, headers=self.request_headers)
            resp.raise_for_status()
            items = resp.json()
            if not items:
                break

            for item in items:
                if len(item.get("parents", [])) > 1:
                    continue  # skip merge commits
                commit_data = item.get("commit", {}) or {}
                author = commit_data.get("author", {}) or {}
                date_str = (author.get("date") or "").replace("Z", "+00:00")
                commit_dt = datetime.fromisoformat(date_str) if date_str else datetime.now()
                commits.append(GitCommitDetail(
                    sha=item["sha"],
                    author_name=author.get("name") or "Unknown",
                    author_email=author.get("email", "") or "",
                    commit_datetime=commit_dt,
                    message=commit_data.get("message", "") or "",
                    files_modified=[],
                ))

            if len(items) < 100:
                break
            page += 1

        return commits

    async def get_pr_diff(self, pr_number: int) -> list[FileDiffPatch]:
        """
        Return the per-file diffs introduced by a pull request, using GitHub's
        per-file ``/pulls/{n}/files`` patches.
        """
        repo_api = f"https://api.github.com/repos/{self.repository_owner}/{self.repository_name}"
        patches: list[FileDiffPatch] = []
        try:
            async with httpx.AsyncClient() as client:
                page = 1
                while True:
                    url = f"{repo_api}/pulls/{pr_number}/files?per_page=100&page={page}"
                    resp = await client.get(url, headers=self.request_headers)
                    resp.raise_for_status()
                    files = resp.json()
                    if not files:
                        break

                    for file in files:
                        patches.append(self._to_file_patch(file))

                    if len(files) < 100:
                        break
                    page += 1
            return patches
        except Exception as e:
            logger.error(f"Failure getting PR diff for PR={pr_number} with exception={str(e)}")
            raise Exception(
                f"Failure occurred while attempting to get diff for PR {pr_number} in repository: {self.full_name}", e
            )

    def _to_file_patch(self, file: dict) -> FileDiffPatch:
        """
        Map a GitHub PR file entry onto a FileDiffPatch, wrapping the patch body
        (which starts at ``@@``) with git-style headers.
        """
        filename = file.get("filename", "")
        previous_filename = file.get("previous_filename")
        status = file.get("status", "modified")
        patch_body = file.get("patch")  # absent for binary / very large files

        if status == "added":
            change_type, previous_path = ChangeType.ADDED, None
            src_path, dst_path = None, filename
        elif status == "removed":
            change_type, previous_path = ChangeType.DELETED, None
            src_path, dst_path = filename, None
        else:  # modified | changed | renamed
            change_type = ChangeType.MODIFIED
            previous_path = previous_filename if status == "renamed" else None
            src_path = previous_filename or filename
            dst_path = filename

        a = src_path or dst_path
        b = dst_path or src_path
        lines = [f"diff --git a/{a} b/{b}"]
        lines.append("--- /dev/null" if src_path is None else f"--- a/{src_path}")
        lines.append("+++ /dev/null" if dst_path is None else f"+++ b/{dst_path}")
        body = patch_body if patch_body else ""
        unified = "\n".join(lines) + ("\n" + body if body else "") + "\n"

        return FileDiffPatch(
            file_path=dst_path or src_path or filename,
            previous_path=previous_path,
            change_type=change_type,
            unified_diff=unified,
            truncated=patch_body is None,
        )