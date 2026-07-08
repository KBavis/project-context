from __future__ import annotations

import logging
from uuid import UUID 
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.services.data_source import DataSourceService
from app.models.data_source import DataSourceType, DataSource
from app.models.project import Project
from app.models.project_repo_summary import ProjectRepoSummary
from app.models.project_affected_file import ProjectAffectedFile
from app.models.project_file_diff import ProjectFileDiff
from app.models.pull_request import PullRequest
from app.models.git_commit import GitCommit
from app.models.diff_task import DiffTask
from app.pydantic.status import ProcessingStatus
from app.models.project_data import ProjectData
from app.models.file import File
from app.exceptions import TaskSkipped
from app.data_providers.fetchable.issue_tracker import IssueTrackerDataProvider
from app.data_providers.ingestible.repository import RepositoryDataProvider
from app.pydantic.pull_request import PullRequestDetail
from app.pydantic.file_diff_patch import FileDiffPatch
from app.pydantic.change_type import ChangeType
from app.core import get_current_session
import hashlib

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.services.repository_changes import RepositoryChangesService

logger = logging.getLogger(__name__)

# Maximum number of bytes of unified-diff text stored per file PR diff; larger
# diffs are capped and flagged via ProjectFileDiff.diff_truncated.
MAX_DIFF_BYTES = 256 * 1024


class DiffTaskService:
    """
    Service responsible for handling all operations related 
    to `Repository Code Changes` for a particular Project 
    """

    def __init__(
        self, 
        async_db: AsyncSession, 
        data_source_svc: DataSourceService,
        repo_changes_svc: RepositoryChangesService,
    ):
        self.async_db: AsyncSession = async_db
        self.data_source_svc = data_source_svc
        self.repo_changes_svc = repo_changes_svc
    



    async def init_diff_task(self, project_id: UUID, data_source_id: UUID, job_id: UUID | None = None, async_session: AsyncSession | None = None) -> DiffTask:
        """
        Validate ProjectData and create initial diff sync job with IN_PROGRESS status

        Args:
            project_id (UUID): the PK for the project to sync
            data_source_id (UUID): the PK for the repository to sync
            async_session: optional background session

        Returns:
            DiffTask: the initialized DiffTask
        """
        db = async_session or self.async_db
        
        # validate ProjectData exists
        stmt = select(ProjectData).where(ProjectData.project_id == project_id, ProjectData.data_source_id == data_source_id)
        res = await db.execute(stmt)
        project_data = res.scalar_one_or_none()
        
        if not project_data:
            raise Exception("ProjectData link does not exist. Cannot sync.")
        




        job = DiffTask(
            job_id=job_id,
            project_id=project_id,
            data_source_id=data_source_id,
            status=ProcessingStatus.IN_PROGRESS,
            start_time=datetime.now(timezone.utc),
        )
        db.add(job)
        await db.flush()
        
        return job

    async def update_diff_task(
        self,
        diff_task_id: UUID,
        status: ProcessingStatus,
        end_time: datetime,
        duration: int,
        session: AsyncSession,
        reason: str | None = None,
        commit: bool = False
    ):
        """
        Update existing DiffTask with relevant status, end_time, and duration.
        """
        job = await session.get(DiffTask, diff_task_id)
        if not job:
            raise Exception(f"Failed to find DiffTask by ID={diff_task_id}")

        job.status = status
        job.end_time = end_time
        job.total_duration = duration
        if reason is not None:
            job.reason = reason

        session.add(job)
        await session.flush()
        
        if commit:
            await session.commit()

    async def _validate_diff_task_preconditions(
        self,
        project: Project,
        repository_ds: DataSource,
        async_session: AsyncSession
    ) -> None:
        """
        Validate whether the DiffTask should run based on the Project's configuration.
        Raises TaskSkipped if preconditions are not met.
        """
        # Pre-condition 1: The data source must be a REPOSITORY and scoped by issues
        if repository_ds.type != DataSourceType.REPOSITORY or not repository_ds.scope_by_issues:
            raise TaskSkipped(f"DataSource={repository_ds.id} is not an issue-scoped repository")

        # Pre-condition 2: The Project must have available Parent Issues
        if not project.parent_issues:
            raise TaskSkipped(f"Project={project.id} has no parent_issues configured")

        # Pre-condition 3: validate that an ISSUE_TRACKER data source is configured for Project
        all_project_ds = await self.data_source_svc.aget_project_data_sources(
            project_id=project.id,
            async_session=async_session
        )
        issue_trackers = [ds for ds in all_project_ds if ds.type == DataSourceType.ISSUE_TRACKER]
        if not issue_trackers:
            raise TaskSkipped(f"No ISSUE_TRACKER configured for Project={project.id}")

    async def execute_repository_sync_job(self, diff_task_id: UUID):
        """
        Execute an initalized DiffTask keyed by the specified DiffTask PK. This job will be ran in 
        a FastAPI.BackgroundTask and will be responsbile for syncing the code changes introduced
        to a particular Repository DataSource by a specific Project. 

        Args:
            diff_task_id (UUID): the DiffTask PK to execute 
        """
        async_session = get_current_session()

        # retrieve the initalized DiffTask
        stmt = select(DiffTask).where(DiffTask.id == diff_task_id)
        res = await async_session.execute(stmt)
        job = res.scalar_one_or_none()
        
        if not job:
            logger.error(f"No DiffTask found for ID: {diff_task_id}")
            raise Exception(f"No DiffTask found for ID: {diff_task_id}")

        # Fetch the associated Project and DataSource inside this session
        stmt = select(Project).where(Project.id == job.project_id)
        res = await async_session.execute(stmt)
        project = res.scalars().one()
        
        stmt = select(DataSource).where(DataSource.id == job.data_source_id)
        res = await async_session.execute(stmt)
        repository_ds = res.scalars().one()

        job_start_time = job.start_time

        # Validate job preconditions. Will raise TaskSkipped if not met.
        await self._validate_diff_task_preconditions(
            project=project,
            repository_ds=repository_ds,
            async_session=async_session
        )

        # get the IssueTracker tied to this Project (NOTE: This is REQUIRED when scoping a Repository's changes by Issues)
        issue_tracker_ds = await self.data_source_svc.get_issue_tracker_data_source(
            project_id=job.project_id,
            async_session=async_session
        )

        # resolve the merged pull requests linked to this project's issues, then
        # persist any that have not been processed yet (merged PRs are immutable,
        # so previously-processed PRs never need recomputing).
        metrics = await self.sync_project_pull_requests(
            project=project,
            repository_ds=repository_ds,
            issue_tracker_ds=issue_tracker_ds,
            diff_task_id=diff_task_id,
            async_session=async_session,
        )

        logger.info(
            f"DiffTask {diff_task_id} completed successfully for "
            f"Project={project.id} (Repository DataSource={repository_ds.id}): "
            f"{metrics['new_prs']} new pull request(s) processed of "
            f"{metrics['resolved_prs']} linked, {metrics['files_touched']} file(s) "
            f"now tracked in the repository change history."
        )


    async def sync_project_pull_requests(
        self,
        project: Project,
        repository_ds: DataSource,
        issue_tracker_ds: DataSource,
        diff_task_id: UUID,
        async_session: AsyncSession,
    ) -> dict[str, int]:
        """
        Resolve and persist the merged pull requests linked to a project's issues
        for a single repository.

        Merged pull requests are immutable, so previously-processed PRs are
        skipped and their stored diff slices are never recomputed. For each new
        PR (oldest first), its metadata + non-merge commits are persisted and its
        per-file diff is appended as an ordered ProjectFileDiff on each file.
        """
        # derive the project's issue keys from the issue tracker (Jira: epic -> stories)
        issue_provider = IssueTrackerDataProvider.from_provider(issue_tracker_ds)
        child_issues = await issue_provider.get_issues(project.parent_issues)

        # ensure the aggregate record exists before persisting PRs (composite FK target)
        repo_changes = await self._ensure_project_repo_summary(
            project.id, repository_ds.id, diff_task_id, async_session
        )

        if not child_issues:
            logger.warning(
                f"No child issues found for Project={project.id} and IssueTracker={issue_tracker_ds.id} "
                f"-- nothing to sync for DataSource={repository_ds.id}"
            )
            await self._update_repository_changes_summary(
                repo_changes, project.id, repository_ds.id, diff_task_id, async_session
            )
            return {"resolved_prs": 0, "new_prs": 0, "files_touched": repo_changes.file_count}

        repository_provider = RepositoryDataProvider.from_provider(repository_ds)
        resolved_prs = await repository_provider.resolve_prs(child_issues, issue_provider)

        processed_numbers = await self._get_processed_pr_numbers(
            project.id, repository_ds.id, async_session
        )
        new_prs = sorted(
            (pr for pr in resolved_prs if pr.pr_number not in processed_numbers),
            key=lambda pr: pr.merged_at,
        )

        if not new_prs:
            logger.info(
                f"All {len(resolved_prs)} linked pull request(s) already processed for "
                f"Project={project.id} and DataSource={repository_ds.id} -- up to date"
            )
            await self._update_repository_changes_summary(
                repo_changes, project.id, repository_ds.id, diff_task_id, async_session
            )
            return {
                "resolved_prs": len(resolved_prs),
                "new_prs": 0,
                "files_touched": repo_changes.file_count,
            }

        logger.info(
            f"Processing {len(new_prs)} new pull request(s) for Project={project.id} "
            f"and DataSource={repository_ds.id}"
        )
        all_patches = []
        for pr_detail in new_prs:
            pr_record = await self._persist_pull_request(
                pr_detail, project.id, repository_ds.id, async_session
            )
            patches = await repository_provider.get_pr_diff(pr_detail.pr_number)
            all_patches.extend(patches)
            await self._apply_pr_file_diffs(
                pr_record=pr_record,
                patches=patches,
                project_id=project.id,
                repository_data_source_id=repository_ds.id,
                diff_task_id=diff_task_id,
                async_session=async_session,
            )



        await self._update_repository_changes_summary(
            repo_changes, project.id, repository_ds.id, diff_task_id, async_session
        )

        return {
            "resolved_prs": len(resolved_prs),
            "new_prs": len(new_prs),
            "files_touched": repo_changes.file_count,
        }


    async def _get_processed_pr_numbers(
        self, project_id: UUID, repository_data_source_id: UUID, async_session: AsyncSession
    ) -> set[int]:
        """Return the PR numbers already persisted for this project + data source."""
        stmt = select(PullRequest.pr_number).where(
            PullRequest.project_id == project_id,
            PullRequest.data_source_id == repository_data_source_id,
        )
        res = await async_session.execute(stmt)
        return set(res.scalars().all())


    async def _ensure_project_repo_summary(
        self,
        project_id: UUID,
        repository_data_source_id: UUID,
        diff_task_id: UUID,
        async_session: AsyncSession,
    ) -> ProjectRepoSummary:
        """Get the ProjectRepoSummary row, creating an empty one on first sync."""
        repo_changes = await self.repo_changes_svc.get_project_repo_summary(
            project_id=project_id,
            data_source_id=repository_data_source_id,
            async_session=async_session,
        )
        if not repo_changes:
            repo_changes = ProjectRepoSummary(
                project_id=project_id,
                data_source_id=repository_data_source_id,
                last_diff_task_id=diff_task_id,
                file_count=0,
            )
            async_session.add(repo_changes)
            await async_session.flush()
        return repo_changes


    async def _persist_pull_request(
        self,
        pr_detail: PullRequestDetail,
        project_id: UUID,
        repository_data_source_id: UUID,
        async_session: AsyncSession,
    ) -> PullRequest:
        """Persist a pull request and its non-merge commit metadata."""
        pr_record = PullRequest(
            project_id=project_id,
            data_source_id=repository_data_source_id,
            pr_number=pr_detail.pr_number,
            title=pr_detail.title,
            description=pr_detail.description,
            author_name=pr_detail.author_name,
            author_email=pr_detail.author_email,
            source_branch=pr_detail.source_branch,
            target_branch=pr_detail.target_branch,
            merged_at=pr_detail.merged_at,
            issue_key=pr_detail.issue_key,
            url=pr_detail.url,
        )
        async_session.add(pr_record)
        await async_session.flush()

        for commit in pr_detail.commits:
            async_session.add(GitCommit(
                pull_request_id=pr_record.id,
                commit_hash=commit.sha,
                author_name=commit.author_name,
                author_email=commit.author_email,
                commit_datetime=commit.commit_datetime,
                message=commit.message,
                files_modified=commit.files_modified,
            ))
        await async_session.flush()
        return pr_record


    async def _apply_pr_file_diffs(
        self,
        pr_record: PullRequest,
        patches: list[FileDiffPatch],
        project_id: UUID,
        repository_data_source_id: UUID,
        diff_task_id: UUID,
        async_session: AsyncSession,
    ):
        """
        Persist a pull request's file changes as ONE net effect per path.

        A PR has a single net effect on each path it touches (added, modified, or
        deleted). We first consolidate all raw patches into a path -> net-effect
        map, then persist exactly one ProjectFileDiff per path
        """
        for file_path, effect in self._consolidate_pr_patches(patches).items():
            await self._apply_file_net_effect(
                file_path=file_path,
                change_type=effect.change_type,
                unified_diff=effect.unified_diff,
                provider_truncated=effect.truncated,
                pr_record=pr_record,
                project_id=project_id,
                repository_data_source_id=repository_data_source_id,
                diff_task_id=diff_task_id,
                async_session=async_session,
            )

    def _get_deletion_unified_diff(self, file_path: str) -> str:
        """
        Build a header-only git deletion diff for a path (no hunks).

        Used for the "delete at the old path" half of a rename: the provider only
        gives the changed hunks (which belong to the new path), so the old path
        gets an accurate "removed from here" marker without fabricating content.
        """
        return (
            f"diff --git a/{file_path} b/{file_path}\n"
            f"--- a/{file_path}\n"
            f"+++ /dev/null\n"
        )


    def _consolidate_pr_patches(self, patches: list[FileDiffPatch]) -> dict[str, FileDiffPatch]:
        """
        Reduce a PR's raw per-file patches to a single net effect per path.

        NOTE: 
            - for handling renames, this is a "DELETE" at old path, and a "ADDED" at new path 
            - to account for this in FileDiffPatch, we manually specify unified diff to be DELETED
        """
        net: dict[str, FileDiffPatch] = {}
        for patch in patches:
            if patch.previous_path and patch.previous_path != patch.file_path:
                # a move/rename is a delete at the old path + an add at the new path
                net[patch.previous_path] = FileDiffPatch(
                    file_path=patch.previous_path,
                    change_type=ChangeType.DELETED,
                    unified_diff=self._get_deletion_unified_diff(patch.previous_path),
                    truncated=patch.truncated,
                )
                net[patch.file_path] = FileDiffPatch(
                    file_path=patch.file_path,
                    change_type=ChangeType.ADDED,
                    unified_diff=patch.unified_diff,
                    truncated=patch.truncated,
                )
            else:
                net[patch.file_path] = FileDiffPatch(
                    file_path=patch.file_path,
                    change_type=patch.change_type,
                    unified_diff=patch.unified_diff,
                    truncated=patch.truncated,
                )
        return net


    async def _apply_file_net_effect(
        self,
        file_path: str,
        change_type: ChangeType,
        unified_diff: str,
        provider_truncated: bool,
        pr_record: PullRequest,
        project_id: UUID,
        repository_data_source_id: UUID,
        diff_task_id: UUID,
        async_session: AsyncSession,
    ):
        """
        Persist one file's net effect from a pull request onto its change history.

        Called exactly once per path per PR (patches are consolidated upstream),
        so each PR contributes at most one ProjectFileDiff per path.
        Applies the change-type reconciliation rule:

          - A file the project ADDED that is later deleted is net-zero: the whole
            file history (and its per-PR diffs) is removed rather than left as a
            phantom "deleted" entry. This also covers a project-added file that is
            later renamed/moved (the delete-old half of the move).
          - A pre-existing file the project deletes keeps its history and its
            roll-up change_type becomes DELETED.
        """
        stmt = select(ProjectAffectedFile).options(
            selectinload(ProjectAffectedFile.pr_diffs)
        ).where(
            ProjectAffectedFile.project_id == project_id,
            ProjectAffectedFile.data_source_id == repository_data_source_id,
            ProjectAffectedFile.file_path == file_path,
        )
        res = await async_session.execute(stmt)
        file_history = res.scalar_one_or_none()

        if file_history is None:
            # first time the project touches this path -> seed the roll-up change_type
            file_history = ProjectAffectedFile(
                project_id=project_id,
                data_source_id=repository_data_source_id,
                file_path=file_path,
                change_type=change_type,
                last_diff_task_id=diff_task_id,
            )
            async_session.add(file_history)
            await async_session.flush()
            await self._add_pr_diff(
                file_history, pr_record, ordinal=0, change_type=change_type,
                unified_diff=unified_diff, provider_truncated=provider_truncated,
                async_session=async_session,
            )
            await async_session.flush()
            return

        if change_type == ChangeType.DELETED and file_history.change_type == ChangeType.ADDED:
            # the project created then removed this file -> net-zero, drop entirely
            await async_session.delete(file_history)
            await async_session.flush()
            return

        next_ordinal = len(file_history.pr_diffs)
        await self._add_pr_diff(
            file_history, pr_record, ordinal=next_ordinal, change_type=change_type,
            unified_diff=unified_diff, provider_truncated=provider_truncated,
            async_session=async_session,
        )

        if change_type == ChangeType.DELETED:
            # pre-existing file removed by the project -> roll-up becomes DELETED
            file_history.change_type = ChangeType.DELETED
        elif file_history.change_type == ChangeType.DELETED:
            # a path the project had deleted is back -> it was modified over time
            file_history.change_type = ChangeType.MODIFIED
        file_history.last_diff_task_id = diff_task_id
        await async_session.flush()


    def _prepare_diff_payload(
        self, unified_diff: str, provider_truncated: bool
    ) -> tuple[str, str, bool]:
        """Cap the diff to MAX_DIFF_BYTES and return (stored_text, sha256_hash, truncated)."""
        raw_bytes = unified_diff.encode("utf-8")
        capped = raw_bytes[:MAX_DIFF_BYTES]
        truncated = provider_truncated or len(capped) < len(raw_bytes)
        stored = capped.decode("utf-8", errors="ignore")
        return stored, hashlib.sha256(stored.encode("utf-8")).hexdigest(), truncated


    async def _add_pr_diff(
        self,
        file_history: ProjectAffectedFile,
        pr_record: PullRequest,
        ordinal: int,
        change_type: ChangeType,
        unified_diff: str,
        provider_truncated: bool,
        async_session: AsyncSession,
    ):
        """Create and stage a ProjectFileDiff for a file under a pull request."""
        stored, diff_hash, truncated = self._prepare_diff_payload(
            unified_diff, provider_truncated
        )
        async_session.add(ProjectFileDiff(
            file_history_id=file_history.id,
            pull_request_id=pr_record.id,
            ordinal=ordinal,
            change_type=change_type,
            unified_diff=stored,
            diff_hash=diff_hash,
            diff_truncated=truncated,
        ))


    async def _update_repository_changes_summary(
        self,
        repo_changes: ProjectRepoSummary,
        project_id: UUID,
        repository_data_source_id: UUID,
        diff_task_id: UUID,
        async_session: AsyncSession,
    ):
        """Refresh the denormalized counts / sync metadata."""
        stmt = select(func.count()).select_from(ProjectAffectedFile).where(
            ProjectAffectedFile.project_id == project_id,
            ProjectAffectedFile.data_source_id == repository_data_source_id,
        )
        res = await async_session.execute(stmt)
        file_count = res.scalar_one()

        repo_changes.file_count = file_count
        repo_changes.last_diff_task_id = diff_task_id
        repo_changes.last_synced_time = datetime.now(timezone.utc)
        async_session.add(repo_changes)
        await async_session.flush()



    async def get_diff_tasks_by_job_id(self, job_id: UUID, session: AsyncSession | None = None) -> list[DiffTask]:
        """
        Retrieve all DiffTasks associated with a specific job_id.

        Args:
            job_id (UUID): The ID of the job to retrieve the DiffTasks for.
            session (AsyncSession, optional): The database session to use. Defaults to None.

        Returns:
            list[DiffTask]: A list of DiffTasks associated with the specified job_id.
        """
        db = session or self.async_db
        stmt = select(DiffTask).where(DiffTask.job_id == job_id)
        res = await db.execute(stmt)
        return list(res.scalars().all())

