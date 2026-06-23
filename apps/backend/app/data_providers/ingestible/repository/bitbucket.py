from __future__ import annotations
import logging
import asyncio
from uuid import UUID
from pathlib import Path
from urllib.parse import quote
import httpx
from io import BytesIO
from datetime import datetime, timezone
import base64
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

class BitbucketDataProvider(RepositoryDataProvider):

    def __init__(self, data_source: DataSource):
        super().__init__(data_source)

    def _parse_repository_ref(self) -> tuple[str, str]:
        # Web/browse URL: https://<domain>/projects/<project>/repos/<repo_name>[/browse]
        parsed_url = self.url.rstrip("/").split("/")
        self.domain = parsed_url[2]
        try:
            projects_idx = parsed_url.index("projects")
            repos_idx = parsed_url.index("repos")
            project = parsed_url[projects_idx + 1]
            repo_name = parsed_url[repos_idx + 1]
            return project, repo_name
        except (ValueError, IndexError):
            raise Exception(
                f"URL {self.url} does not match the expected Bitbucket Server format: "
                f"https://<domain>/projects/<project>/repos/<repo_name>"
            )

    def _construct_base_urls(self):
        self.base_url = f"https://{self.domain}/projects/{self.repository_owner}/repos/{self.repository_name}/browse?at={self.branch_name}"
        self.base_api_url = f"https://{self.domain}/rest/api/1.0/projects/{self.repository_owner}/repos/{self.repository_name}"
        self.file_download_base_url = f"{self.base_api_url}/raw"

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
        # Validate the web/browse URL; the clone URL is derived separately.
        if "/projects/" not in self.url or "/repos/" not in self.url:
            raise Exception(
                f"The specified data source URL, {self.url}, is not in the proper Bitbucket format: "
                f"https://<domain>/projects/<project>/repos/<repo_name>"
            )

    async def _get_repository_data(self, curr_url: str):
        assert self.file_svc and self.job_pk

        # Bitbucket Server /files endpoint to get all files
        # E.g. /rest/api/1.0/projects/{proj}/repos/{repo}/files?at={branch}
        files_url = f"{self.base_api_url}/files?at={self.branch_name}&limit=10000"

        # reuse single pooled client
        max_concurrency = max(1, settings.BITBUCKET_MAX_CONCURRENT_DOWNLOADS) # max downloads occuring at one time
        limits = httpx.Limits(
            max_connections=max_concurrency,
            max_keepalive_connections=max_concurrency,
        )
        timeout = httpx.Timeout(settings.BITBUCKET_DOWNLOAD_TIMEOUT_SECONDS)

        async with httpx.AsyncClient(
            headers=self.request_headers, limits=limits, timeout=timeout
        ) as client:
            # 1. Enumerate every file path on the branch (handling pagination).
            paths: list[str] = []
            start = None
            while True:
                page_url = files_url if start is None else f"{files_url}&start={start}"
                try:
                    response = await client.get(page_url)
                    response.raise_for_status()
                    content = response.json()
                except Exception as e:
                    logger.error(f"Failure while attempting to retrieve data from the URL {page_url}")
                    raise e

                paths.extend(content.get("values", []))
                if content.get("isLastPage", True):
                    break
                start = content.get("nextPageStart")

            # exclude irrelevant paths before downloading them
            paths = self._filter_excluded_paths(paths)

            # 2. Download relevant files with bounded concurrency: parallel enough
            #    to ingest large repos quickly, capped so we don't flood the server.
            semaphore = asyncio.Semaphore(max_concurrency)

            # Downloads run concurrently, but the shared AsyncSession is not safe for
            # concurrent use; this lock serializes persistence so only one coroutine
            # touches the session at a time
            persist_lock = asyncio.Lock()

            async def _download_with_limit(path: str):
                async with semaphore:
                    # safely encode path, but keep forward slashes 
                    download_url = f"{self.file_download_base_url}/{quote(path, safe='/')}?at={self.branch_name}"
                    await self._download_file(client, download_url, Path(path).name, path, persist_lock)

            # schedule all downloads concurrently, but run with bounded concurrency due to the semaphore (default is 8 max concurrent downloads)
            results = await asyncio.gather(
                *(_download_with_limit(path) for path in paths),
                return_exceptions=True,
            )

        # A single file's failure should not waste the entire ingestion run: every
        # file that downloaded successfully has already been persisted. Log the
        # failures and report a summary, but let the job complete so that work is
        # retained.
        failures = [
            (path, result)
            for path, result in zip(paths, results)
            if isinstance(result, Exception)
        ]
        if failures:
            for path, err in failures:
                logger.error(f"Failed to ingest file={path}: {err}")
            logger.warning(
                f"Completed ingestion of {self.full_name} with {len(failures)} of "
                f"{len(paths)} file(s) failing to download; the remaining "
                f"{len(paths) - len(failures)} file(s) were processed successfully."
            )

    async def _download_file(
        self, client: httpx.AsyncClient, url: str, file_name: str, file_path: str, persist_lock: asyncio.Lock
    ):
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
            response = await client.get(url)
            response.raise_for_status()

            buffer = BytesIO()
            hashed_content = await asyncio.to_thread(self.file_svc.hash_file_content, response, buffer)

            # Bitbucket's /files listing carries no metadata, so derive the true
            # byte count from the downloaded content rather than the listing.
            size = buffer.getbuffer().nbytes

            file = File(
                path=file_path, 
                file_name=file_name, 
                file_type=self.file_svc.get_file_extension(file_extension), 
                size=size, 
                hash=hashed_content,
                file_url=url
            )
            # The session backing FileService is shared across concurrent downloads,
            # so serialize all session access through the lock.
            async with persist_lock:
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
            # Normalize a leading slash so we don't build a `/raw//...` 404.
            url = f"{self.file_download_base_url}/{quote(file_path.lstrip('/'), safe='/')}?at={self.branch_name}"
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.request_headers)
                response.raise_for_status()
                return response.text
        except Exception as e:
            logger.error(f"Failure viewing file={file_path} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempt to view file: {file_path}", e)

    async def list_directory(self, path: str) -> str:
        try:
            # Agents may pass paths with a leading slash; the API 404s on the
            # resulting `/browse//...` double slash, so normalize it off.
            url = f"{self.base_api_url}/browse/{quote(path.lstrip('/'), safe='/')}?at={self.branch_name}"
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
            return f"[{path}](https://{self.domain}/projects/{self.repository_owner}/repos/{self.repository_name}/browse/{quote(path.lstrip('/'), safe='/')}?at={self.branch_name})"
        except Exception as e:
            logger.error(f"Failure generating citation for path={path} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempt to generate citation for path: {path}", e)

    def _parse_timestamp(self, ts) -> datetime:
        """
        Parse a dev-status ``authorTimestamp`` into a tz-aware UTC datetime.
        Jira returns either an ISO-8601 string with offset or epoch ms.
        """
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
        if isinstance(ts, str) and ts:
            try:
                dt = datetime.fromisoformat(ts)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(tz=timezone.utc)

    async def resolve_prs(
        self,
        issue_keys: list[str],
        issue_provider: IssueTrackerDataProvider,
    ) -> list[PullRequestDetail]:
        """
        Resolve the merged pull requests linked to a set of issue keys.

        The issue<->pull-request linkage is delegated to the project's Jira
        issue provider (Jira's dev-status ``dataType=pullrequest`` API), so only
        the pull requests Jira reports as linked to these issues are fetched from
        Bitbucket — we never enumerate every merged pull request in the repo.
        Only MERGED pull requests targeting this data source's branch are kept.
        """
        if not issue_keys:
            return []

        from app.data_providers.fetchable.issue_tracker.jira import JiraDataProvider

        if not isinstance(issue_provider, JiraDataProvider):
            raise Exception(
                "A Jira issue provider is required to resolve pull requests for a Bitbucket "
                f"repository ({self.full_name}). Bitbucket repositories must be linked to a "
                "project that has an associated Jira issue tracker when scope_by_issues is enabled."
            )

        needles = [key.lower() for key in issue_keys]
        matched: list[PullRequestDetail] = []

        try:
            linked_prs = await issue_provider.get_linked_pull_requests(
                issue_keys, self.repository_owner, self.repository_name
            )

            async with httpx.AsyncClient() as client:
                seen: set[int] = set()
                for linked in linked_prs:
                    # dev-status reports all states; we only ingest merged PRs.
                    if (linked.get("status") or "").upper() != "MERGED":
                        continue

                    raw_id = str(linked.get("id") or "").lstrip("#")
                    if not raw_id.isdigit():
                        continue
                    pr_id = int(raw_id)
                    if pr_id in seen:
                        continue
                    seen.add(pr_id)

                    # fetch full detail for this single PR (not every repo PR).
                    pr = await self._fetch_pull_request(client, pr_id)
                    if pr is None:
                        continue

                    # keep only PRs that target this data source's branch.
                    target_branch = (pr.get("toRef") or {}).get("displayId", "") or ""
                    if target_branch and target_branch != self.branch_name:
                        continue

                    key = self._match_issue_key(pr, issue_keys, needles)
                    if not key:
                        continue
                    matched.append(await self._to_pull_request_detail(client, pr, key))

            logger.info(
                "Resolved %d linked pull requests for %s matching issues %s",
                len(matched), self.full_name, issue_keys,
            )
            return matched
        except Exception as e:
            logger.error(f"Failure resolving pull requests with exception={str(e)}")
            raise Exception(f"Failure occurred while attempting to resolve pull requests for repository: {self.full_name}", e)

    async def _fetch_pull_request(self, client: httpx.AsyncClient, pr_id: int) -> dict | None:
        """Fetch a single pull request's full detail by id, or None if missing."""
        url = f"{self.base_api_url}/pull-requests/{pr_id}"
        resp = await client.get(url, headers=self.request_headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def _match_issue_key(self, pr: dict, issue_keys: list[str], needles: list[str]) -> str | None:
        """
        Return the single child issue key this pull request references via its
        source branch name (primary signal) or title/description (safety net),
        or ``None`` when nothing matches. A pull request maps one-to-one to a
        child issue, so the first match wins.
        """
        source_branch = (pr.get("fromRef") or {}).get("displayId", "") or ""
        haystack = " ".join([
            source_branch,
            pr.get("title", "") or "",
            pr.get("description", "") or "",
        ]).lower()
        for key, needle in zip(issue_keys, needles):
            if needle in haystack:
                return key
        return None

    async def _to_pull_request_detail(
        self, client: httpx.AsyncClient, pr: dict, issue_key: str
    ) -> PullRequestDetail:
        author_user = (pr.get("author") or {}).get("user", {}) or {}
        source_branch = (pr.get("fromRef") or {}).get("displayId", "") or ""
        target_branch = (pr.get("toRef") or {}).get("displayId", "") or self.branch_name
        self_links = (pr.get("links") or {}).get("self") or []
        url = self_links[0].get("href") if self_links else None

        return PullRequestDetail(
            pr_number=pr["id"],
            title=pr.get("title", "") or "",
            description=pr.get("description"),
            author_name=author_user.get("displayName") or author_user.get("name") or "Unknown",
            author_email=author_user.get("emailAddress"),
            source_branch=source_branch,
            target_branch=target_branch,
            merged_at=self._parse_timestamp(pr.get("closedDate")),
            issue_key=issue_key,
            url=url,
            commits=await self._fetch_pr_commits(client, pr["id"]),
        )

    async def _fetch_pr_commits(self, client: httpx.AsyncClient, pr_id: int) -> list[GitCommitDetail]:
        """
        Fetch the non-merge commits contained in a pull request (descriptive
        metadata). Merge commits (parents > 1) are excluded.
        """
        commits: list[GitCommitDetail] = []
        start = 0
        while True:
            url = f"{self.base_api_url}/pull-requests/{pr_id}/commits?limit=100&start={start}"
            resp = await client.get(url, headers=self.request_headers)
            resp.raise_for_status()
            page = resp.json()

            for commit in page.get("values", []):
                if len(commit.get("parents", [])) > 1:
                    continue  # skip merge commits
                author = commit.get("author", {}) or {}
                commits.append(GitCommitDetail(
                    sha=commit["id"],
                    author_name=author.get("name") or author.get("displayName") or "Unknown",
                    author_email=author.get("emailAddress", "") or "",
                    commit_datetime=self._parse_timestamp(commit.get("authorTimestamp")),
                    message=commit.get("message", "") or "",
                    files_modified=[],
                ))

            if page.get("isLastPage", True):
                break
            start = page.get("nextPageStart", start + 100)

        return commits

    async def get_pr_diff(self, pr_number: int) -> list[FileDiffPatch]:
        """
        Return the per-file diffs introduced by a pull request, reconstructed
        from Bitbucket's structured diff JSON (the three-dot diff:
        merge-base(target, source)..source).
        """
        url = f"{self.base_api_url}/pull-requests/{pr_number}/diff?withComments=false"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=self.request_headers)
                resp.raise_for_status()
                data = resp.json()

            response_truncated = bool(data.get("truncated"))
            patches: list[FileDiffPatch] = []
            for file_diff in data.get("diffs", []):
                patch = self._reconstruct_file_patch(file_diff, response_truncated)
                if patch is not None:
                    patches.append(patch)
            return patches
        except Exception as e:
            logger.error(f"Failure getting PR diff for PR={pr_number} with exception={str(e)}")
            raise Exception(f"Failure occurred while attempting to get diff for PR {pr_number} in repository: {self.full_name}", e)

    def _reconstruct_file_patch(self, file_diff: dict, response_truncated: bool) -> FileDiffPatch | None:
        """
        Rebuild a git-style unified diff for a single file from Bitbucket's
        structured diff JSON ({source, destination, hunks:[{segments:[{lines}]}]}).

        We rebuild the canonical `diff --git ... @@` text so 
            a) every provider yields the same FileDiffPatch shape downstream (GitHub already returns a patch body)
            b) the stored diff reads as a normal git diff for the agent. 
        """
        source = file_diff.get("source")
        destination = file_diff.get("destination")
        src_path = source.get("toString") if source else None
        dst_path = destination.get("toString") if destination else None

        # No paths at all -> nothing we can represent.
        if src_path is None and dst_path is None:
            return None

        # Presence of source/destination is how Bitbucket encodes the change type:
        #   no source      -> file created       (added)
        #   no destination -> file removed        (deleted)
        #   both, differ   -> file moved/renamed  (modified + previous_path)
        if src_path is None:
            change_type = ChangeType.ADDED
            file_path, previous_path = dst_path, None
        elif dst_path is None:
            change_type = ChangeType.DELETED
            file_path, previous_path = src_path, None
        else:
            change_type = ChangeType.MODIFIED
            file_path = dst_path
            previous_path = src_path if src_path != dst_path else None

        # Header: `--- /dev/null` / `+++ /dev/null` mark a creation/deletion the
        # same way git does, so the add/delete intent survives in the diff text.
        a = src_path or dst_path
        b = dst_path or src_path
        lines = [f"diff --git a/{a} b/{b}"]
        lines.append("--- /dev/null" if src_path is None else f"--- a/{src_path}")
        lines.append("+++ /dev/null" if dst_path is None else f"+++ b/{dst_path}")

        # Body: one `@@ -srcLine,srcSpan +dstLine,dstSpan @@` header per hunk,
        # then each line prefixed by its segment type (+ added, - removed, space
        # for unchanged context) 
        for hunk in file_diff.get("hunks") or []:
            lines.append(
                f"@@ -{hunk.get('sourceLine', 0)},{hunk.get('sourceSpan', 0)} "
                f"+{hunk.get('destinationLine', 0)},{hunk.get('destinationSpan', 0)} @@"
            )
            for segment in hunk.get("segments") or []:
                seg_type = segment.get("type")
                prefix = "+" if seg_type == "ADDED" else "-" if seg_type == "REMOVED" else " "
                for line in segment.get("lines") or []:
                    lines.append(prefix + line.get("line", ""))

        return FileDiffPatch(
            file_path=file_path,
            previous_path=previous_path,
            change_type=change_type,
            unified_diff="\n".join(lines) + "\n",
            truncated=response_truncated or bool(file_diff.get("truncated")),
        )
