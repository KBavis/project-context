from __future__ import annotations
from abc import abstractmethod
from fnmatch import fnmatch
from uuid import UUID
from typing import TYPE_CHECKING
import logging

from app.data_providers.ingestible.base import IngestibleDataProvider
from app.data_providers import Provider
from app.core import settings
from app.models.data_source import DataSource
from app.services.file import FileService
from app.pydantic.pull_request import PullRequestDetail
from app.pydantic.file_diff_patch import FileDiffPatch

if TYPE_CHECKING:
    from app.data_providers.fetchable.issue_tracker.base import IssueTrackerDataProvider

logger = logging.getLogger(__name__)

class RepositoryDataProvider(IngestibleDataProvider):
    """
    Abstract base class for Repository data providers (like GitHub, BitBucket, etc).
    Contains methods specific to pulling source code and PR diffs.
    """

    def __init__(self, data_source: DataSource):
        super().__init__(data_source=data_source)

        # extract relevant from URL & data source
        repository_owner, repository_name = self._parse_repository_ref()
        self._repository_name = repository_name
        self._branch_name = data_source.branch
        self._repository_owner = repository_owner

        # construct requried URLs
        self._construct_base_urls()


    @classmethod
    def from_provider(cls, data_source: DataSource) -> RepositoryDataProvider:
        match data_source.provider:
            case Provider.GITHUB:
                from app.data_providers.ingestible.repository import GithubDataProvider
                return GithubDataProvider(data_source=data_source)
            case Provider.BITBUCKET:
                from app.data_providers.ingestible.repository.bitbucket import BitbucketDataProvider
                return BitbucketDataProvider(data_source=data_source)
            case _:
                raise Exception(f"Data Source provider {data_source.provider} is not configured as a Repository Data Provider")


    @property
    def repository_owner(self) -> str:
        """
        The username of the repository owner.
        """
        return self._repository_owner

    @property
    def repository_name(self) -> str:
        """
        The name of the repository.
        """
        return self._repository_name

    @property
    def branch_name(self) -> str:
        """
        The name of the branch.
        """
        return self._branch_name

    @property
    def full_name(self) -> str:
        """
        Full name of repository (owner & repo name)
        """
        return f"{self._repository_owner}/{self._repository_name}"
    

    def _is_excluded_path(self, path: str) -> bool:
        """
        Return True if a repo file path matches any configured ingestion exclude glob
        (company-agnostic INGESTION_EXCLUDE_PATTERNS plus repo-specific
        INGESTION_EXCLUDE_PATTERNS_EXTRA). Used to skip vendored/build/generated/fixture files.

        Args:
            path (str): repository file path to test
        """
        patterns = settings.INGESTION_EXCLUDE_PATTERNS + settings.INGESTION_EXCLUDE_PATTERNS_EXTRA
        return any(fnmatch(path, pattern) for pattern in patterns)


    def _filter_excluded_paths(self, paths: list[str]) -> list[str]:
        """
        Drop repo file paths matching the configured exclude globs so they are never downloaded,
        embedded, or stored. Combines the company-agnostic INGESTION_EXCLUDE_PATTERNS defaults with
        any repo-specific INGESTION_EXCLUDE_PATTERNS_EXTRA supplied via .env.

        Args:
            paths (list[str]): all file paths enumerated from the repository
        """
        kept = [p for p in paths if not self._is_excluded_path(p)]

        excluded = len(paths) - len(kept)
        if excluded:
            logger.info(
                f"Excluded {excluded} of {len(paths)} file(s) from ingestion via "
                f"exclude patterns; {len(kept)} remain"
            )

        return kept

    def _is_in_ingest_paths(self, path: str) -> bool:
        """
        Return True if a repo file path is within the configured ingest_paths for this data source.
        If ingest_paths is empty, the entire repository is considered in-scope.
        
        Args:
            path (str): repository file path to test
        """
        if not self.data_source.ingest_paths:
            return True
            
        path = path.strip("/")
        for prefix in self.data_source.ingest_paths:
            # Segment-aware match: exactly the directory itself, or inside the directory
            if path == prefix or path.startswith(f"{prefix}/"):
                return True
                
        return False

    def _collapse_ingest_paths(self) -> list[str]:
        """
        Minimal prefix set: drop any prefix that already sits under another
        (e.g., my/path is removed when my/ is present).
        Prevents double-listing / double-descent.
        """
        if not self.data_source.ingest_paths:
            return []

        paths = sorted(self.data_source.ingest_paths)
        collapsed = []
        for p in paths:
            if not collapsed:
                collapsed.append(p)
                continue
            
            last = collapsed[-1]
            if p == last or p.startswith(f"{last}/"):
                continue
            
            collapsed.append(p)
        return collapsed

    def _should_descend(self, dir_path: str) -> bool:
        """
        For tree-walkers (GitHub): return True if we should enter this directory.
        - ingest_paths is empty (whole repo)
        - dir is root ("") -> always True
        - dir equals a prefix
        - dir is inside a prefix
        - dir is an ancestor of a prefix
        """
        if not self.data_source.ingest_paths:
            return True
            
        d = dir_path.strip("/")
        if not d:
            return True
            
        for p in self.data_source.ingest_paths:
            if d == p or d.startswith(f"{p}/") or p.startswith(f"{d}/"):
                return True
                
        return False

    def _filter_ingest_paths(self, paths: list[str]) -> list[str]:
        """
        Drop repo file paths that do not match any prefix configured in ingest_paths.
        If ingest_paths is empty, all paths are kept.
        
        Args:
            paths (list[str]): all file paths enumerated from the repository
        """
        if not self.data_source.ingest_paths:
            return paths
            
        kept = [p for p in paths if self._is_in_ingest_paths(p)]
        
        excluded = len(paths) - len(kept)
        if excluded:
            logger.info(
                f"Excluded {excluded} of {len(paths)} file(s) from ingestion because they "
                f"are outside the configured ingest_paths={self.data_source.ingest_paths}; {len(kept)} remain"
            )
            
        return kept


    @abstractmethod
    def _parse_repository_ref(self) -> tuple[str, str]:
        """
        Extract (repository_owner, repository_name) from provided Data Source URL 
        """
        raise NotImplementedError()
    
    @abstractmethod
    def _construct_base_urls(self):
        """
        Construct the base URLs for the repository.
        """
        raise NotImplementedError()
        
    @abstractmethod
    async def _get_repository_data(self, curr_url: str, file_svc: FileService, job_pk: UUID):
        """
        Recursively pull down the repository contents.
        """
        raise NotImplementedError()
        
    @abstractmethod
    async def _download_file(self, url: str, file_name: str, file_path: str, size: int, file_svc: FileService, job_pk: UUID):
        """
        Download a file to the temporary directory.
        """
        raise NotImplementedError()
    

    @abstractmethod
    async def resolve_prs(
        self,
        issue_keys: list[str],
        issue_provider: IssueTrackerDataProvider,
    ) -> list[PullRequestDetail]:
        """
        Resolve the merged pull requests linked to a set of issue keys.

        ``issue_provider`` is the project's issue tracker. Providers that resolve
        the issue<->pull-request linkage natively use it (e.g. Bitbucket resolves
        PRs through Jira's dev-status API rather than scanning Bitbucket); other
        providers may match locally and ignore it. Only MERGED pull requests
        targeting this data source's branch are returned. The returned commit
        metadata excludes merge commits (parents > 1).
        """
        raise NotImplementedError()

    @abstractmethod
    async def get_pr_diff(self, pr_number: int) -> list[FileDiffPatch]:
        """
        Return the per-file diffs introduced by a single pull request.

        Each entry is one file's unified diff for this pull request (the
        provider-native three-dot diff: merge-base(target, source)..source).
        Renames are reported with ``previous_path`` set so the caller can treat
        them as a delete at the old path + add at the new path.
        """
        raise NotImplementedError()
        
