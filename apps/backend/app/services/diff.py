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
from app.models.diff_sync_job import DiffSyncJob
from app.models.ingestion_job import ProcessingStatus
from app.models.record_lock import RecordType
from app.services.record_lock import RecordLockService
from app.models.project_data import ProjectData
from app.models.file import File
from app.data_providers.fetchable.issue_tracker import IssueTrackerDataProvider
from app.data_providers.ingestible.repository import RepositoryDataProvider
from app.pydantic.pull_request import PullRequestDetail
from app.pydantic.file_diff_patch import FileDiffPatch
from app.pydantic.change_type import ChangeType
from app.core import get_async_db_session_context, get_async_session_maker
import hashlib
import uuid

logger = logging.getLogger(__name__)

# Maximum number of bytes of unified-diff text stored per file PR diff; larger
# diffs are capped and flagged via ProjectFileDiff.diff_truncated.
MAX_DIFF_BYTES = 256 * 1024


class DiffService:
    """
    Service responsible for handling all operations related 
    to `Repository Code Changes` for a particular Project 
    """

    def __init__(
        self, 
        async_db: AsyncSession, 
        data_source_svc: DataSourceService,
        record_lock_svc: RecordLockService,
    ):
        self.async_db: AsyncSession = async_db
        self.data_source_svc = data_source_svc
        self.record_lock_svc = record_lock_svc
    

    async def get_project_sync_state(self, project_id: UUID) -> tuple[str, list[str]]:
        """
        Determines the overall synchronization state of a project's repository data sources.
        Returns: tuple(status_string, list_of_reasons)
        """
        linked_data_sources = await self.data_source_svc.aget_project_data_sources(project_id)
        repo_data_sources = [ds for ds in linked_data_sources if ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues]
        
        logger.info(f"[SyncState] project_id={project_id}: found {len(linked_data_sources)} linked data sources, {len(repo_data_sources)} are issue-scoped repositories")
        
        if not repo_data_sources:
            logger.info(f"[SyncState] project_id={project_id}: no issue-scoped repos → success")
            return ProcessingStatus.SUCCESS.value, []
            
        states = []
        reasons = []
        for ds in repo_data_sources:
            
            # check latest diff job
            stmt = select(DiffSyncJob).where(
                DiffSyncJob.project_id == project_id,
                DiffSyncJob.data_source_id == ds.id
            ).order_by(DiffSyncJob.start_time.desc()).limit(1)
            res = await self.async_db.execute(stmt)
            job = res.scalar_one_or_none()
            
            if job:
                job_state = job.status.value
                logger.info(f"[SyncState] project_id={project_id}, ds={ds.id} ({ds.name}): latest DiffSyncJob={job.id}, status={job_state}")
                states.append(job_state)
                
                if job_state == ProcessingStatus.FAILED.value:
                    reasons.append(f"Latest diff sync job failed for repository '{ds.name}'.")
                elif job_state == ProcessingStatus.IN_PROGRESS.value:
                    reasons.append(f"Repository '{ds.name}' is currently being synced.")
                elif job_state == ProcessingStatus.SKIPPED.value:
                    reasons.append(f"Diff sync was skipped for repository '{ds.name}' due to missing configuration.")
            else:
                logger.info(f"[SyncState] project_id={project_id}, ds={ds.id} ({ds.name}): no DiffSyncJob found → not yet synced")
                states.append(ProcessingStatus.NOT_YET_SYNCED.value)
                reasons.append(f"Repository '{ds.name}' has not yet been synced.")
        
        logger.info(f"[SyncState] project_id={project_id}: all states={states}")
        
        if ProcessingStatus.IN_PROGRESS.value in states or ProcessingStatus.SKIPPED.value in states:
            return ProcessingStatus.IN_PROGRESS.value, reasons
        if ProcessingStatus.FAILED.value in states:
            return ProcessingStatus.FAILED.value, reasons
        if ProcessingStatus.NOT_YET_SYNCED.value in states:
            return ProcessingStatus.NOT_YET_SYNCED.value, reasons
            
        return ProcessingStatus.SUCCESS.value, []


    async def init_diff_sync_job(self, project_id: UUID, data_source_id: UUID, async_session: AsyncSession | None = None) -> DiffSyncJob:
        """
        Validate ProjectData and create initial diff sync job with IN_PROGRESS status

        Args:
            project_id (UUID): the PK for the project to sync
            data_source_id (UUID): the PK for the repository to sync
            async_session: optional background session

        Returns:
            DiffSyncJob: the initialized DiffSyncJob
        """
        db = async_session or self.async_db
        
        # validate ProjectData exists
        stmt = select(ProjectData).where(ProjectData.project_id == project_id, ProjectData.data_source_id == data_source_id)
        res = await db.execute(stmt)
        project_data = res.scalar_one_or_none()
        
        if not project_data:
            raise Exception("ProjectData link does not exist. Cannot sync.")
        


        # lock the resource
        pair_lock_key = f"sync:{project_id}:{data_source_id}"
        lock_uuid = uuid.uuid5(uuid.NAMESPACE_OID, pair_lock_key)
        locked = await self.record_lock_svc.lock(lock_uuid, RecordType.PROJECT_DATA)
        if not locked:
            raise Exception(f"Failed to acquire lock for project_data: Record already locked")

        job = DiffSyncJob(
            project_id=project_id,
            data_source_id=data_source_id,
            status=ProcessingStatus.IN_PROGRESS,
            start_time=datetime.now(timezone.utc),
        )
        db.add(job)
        await db.flush()
        
        return job

    async def update_diff_sync_job(
        self,
        job_id: UUID,
        status: ProcessingStatus,
        end_time: datetime,
        duration: int,
        session: AsyncSession,
        error_message: str | None = None,
        commit: bool = False
    ):
        """
        Update existing DiffSyncJob with relevant status, end_time, and duration.
        """
        job = await session.get(DiffSyncJob, job_id)
        if not job:
            raise Exception(f"Failed to find DiffSyncJob by ID={job_id}")

        job.status = status
        job.end_time = end_time
        job.total_duration = duration
        if error_message is not None:
            job.error_message = error_message

        session.add(job)
        await session.flush()
        
        if commit:
            await session.commit()

    async def _validate_diff_sync_preconditions(
        self,
        job_id: UUID,
        job_start_time: datetime,
        project: Project,
        repository_ds: DataSource,
        async_session: AsyncSession
    ) -> bool:
        """
        Validate whether the DiffSyncJob should run based on the Project's configuration.
        Returns True if preconditions are met, False if the job was skipped.
        """
        # Pre-condition 1: The data source must be a REPOSITORY and scoped by issues
        if repository_ds.type != DataSourceType.REPOSITORY or not repository_ds.scope_by_issues:
            logger.info(f"DataSource={repository_ds.id} is not an issue-scoped repository — skipping DiffSyncJob={job_id}")
            end_time = datetime.now(timezone.utc)
            await self.update_diff_sync_job(
                job_id=job_id,
                status=ProcessingStatus.SKIPPED,
                end_time=end_time,
                duration=int((end_time - job_start_time).total_seconds()),
                session=async_session,
                commit=True
            )
            return False

        # Pre-condition 2: The Project must have available Parent Issues
        if not project.parent_issues:
            logger.info(f"Project={project.id} has no parent_issues configured — skipping DiffSyncJob={job_id}")
            end_time = datetime.now(timezone.utc)
            await self.update_diff_sync_job(
                job_id=job_id,
                status=ProcessingStatus.SKIPPED,
                end_time=end_time,
                duration=int((end_time - job_start_time).total_seconds()),
                session=async_session,
                commit=True
            )
            return False

        # Pre-condition 3: validate that an ISSUE_TRACKER data source is configured for Project
        all_project_ds = await self.data_source_svc.aget_project_data_sources(
            project_id=project.id,
            async_session=async_session
        )
        issue_trackers = [ds for ds in all_project_ds if ds.type == DataSourceType.ISSUE_TRACKER]
        if not issue_trackers:
            logger.info(
                f"No ISSUE_TRACKER configured for Project={project.id} — "
                f"skipping DiffSyncJob={job_id} (pre-condition not met)"
            )
            end_time = datetime.now(timezone.utc)
            duration = int((end_time - job_start_time).total_seconds())
            await self.update_diff_sync_job(
                job_id=job_id,
                status=ProcessingStatus.SKIPPED,
                end_time=end_time,
                duration=duration,
                session=async_session,
                commit=True
            )
            return False
            
        return True

    async def execute_repository_sync_job(self, job_id: UUID):
        """
        Execute an initalized DiffSyncJob keyed by the specified JobID. This job will be ran in 
        a FastAPI.BackgroundTask and will be responsbile for syncing the code changes introduced
        to a particular Repository DataSource by a specific Project. The associated PROJECT_DATA
        record is locked to prohibit parallel DiffSyncJob's running at once, and will be unlocked
        following its completetion

        Args:
            job_id (UUID): the DiffSyncJob PK to execute 
        """

        async with get_async_db_session_context() as async_session:

            # retrieve the initalized DiffSyncJob
            stmt = select(DiffSyncJob).where(DiffSyncJob.id == job_id)
            res = await async_session.execute(stmt)
            job = res.scalar_one_or_none()
            
            if not job:
                logger.error(f"No DiffSyncJob found for ID: {job_id}")
                raise Exception(f"No DiffSyncJob found for ID: {job_id}")

            # Fetch the associated Project and DataSource inside this session
            stmt = select(Project).where(Project.id == job.project_id)
            res = await async_session.execute(stmt)
            project = res.scalars().one()
            
            stmt = select(DataSource).where(DataSource.id == job.data_source_id)
            res = await async_session.execute(stmt)
            repository_ds = res.scalars().one()

            pair_lock_key = f"sync:{job.project_id}:{job.data_source_id}"
            lock_uuid = uuid.uuid5(uuid.NAMESPACE_OID, pair_lock_key)
            job_start_time = job.start_time

            try:
                # Validate job preconditions. If they aren't met, the job is cleanly skipped.
                is_valid = await self._validate_diff_sync_preconditions(
                    job_id=job_id,
                    job_start_time=job_start_time,
                    project=project,
                    repository_ds=repository_ds,
                    async_session=async_session
                )
                
                if not is_valid:
                    return

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
                    diff_sync_job_id=job_id,
                    async_session=async_session,
                )

                # update DiffSyncJob status as successful
                end_time = datetime.now(timezone.utc)
                duration = int((end_time - job_start_time).total_seconds())
                await self.update_diff_sync_job(
                    job_id=job_id,
                    status=ProcessingStatus.SUCCESS,
                    end_time=end_time,
                    duration=duration,
                    session=async_session,
                    commit=True
                )

                logger.info(
                    f"DiffSyncJob {job_id} completed successfully in {duration}s for "
                    f"Project={project.id} (Repository DataSource={repository_ds.id}): "
                    f"{metrics['new_prs']} new pull request(s) processed of "
                    f"{metrics['resolved_prs']} linked, {metrics['files_touched']} file(s) "
                    f"now tracked in the repository change history."
                )

            except Exception as e:
                logger.error(f"Error during execute_repository_sync_job for job {job_id}: {e}", exc_info=True)
                
                # update the DiffSyncJob with appropaite status and error message when failing 
                # NOTE: This is done in seperate session as all other changes will be rolled back
                async with get_async_db_session_context() as session:
                    fail_end_time = datetime.now(timezone.utc)
                    fail_duration = int((fail_end_time - job_start_time).total_seconds())
                    await self.update_diff_sync_job(
                        job_id=job_id,
                        status=ProcessingStatus.FAILED,
                        end_time=fail_end_time,
                        duration=fail_duration,
                        session=session,
                        error_message=str(e),
                        commit=True
                    )

                # re-raise so changes are rolled back
                raise
            finally:
                # always unlock ProjectData record after job completes
                await self.record_lock_svc.unlock(lock_uuid, record_type=RecordType.PROJECT_DATA)


    async def sync_project_pull_requests(
        self,
        project: Project,
        repository_ds: DataSource,
        issue_tracker_ds: DataSource,
        diff_sync_job_id: UUID,
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
            project.id, repository_ds.id, diff_sync_job_id, async_session
        )

        if not child_issues:
            logger.warning(
                f"No child issues found for Project={project.id} and IssueTracker={issue_tracker_ds.id} "
                f"-- nothing to sync for DataSource={repository_ds.id}"
            )
            await self._update_repository_changes_summary(
                repo_changes, project.id, repository_ds.id, diff_sync_job_id, async_session
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
                repo_changes, project.id, repository_ds.id, diff_sync_job_id, async_session
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
                diff_sync_job_id=diff_sync_job_id,
                async_session=async_session,
            )



        await self._update_repository_changes_summary(
            repo_changes, project.id, repository_ds.id, diff_sync_job_id, async_session
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
        diff_sync_job_id: UUID,
        async_session: AsyncSession,
    ) -> ProjectRepoSummary:
        """Get the ProjectRepoSummary row, creating an empty one on first sync."""
        repo_changes = await self.get_project_repo_summary(
            project_id=project_id,
            data_source_id=repository_data_source_id,
            async_session=async_session,
        )
        if not repo_changes:
            repo_changes = ProjectRepoSummary(
                project_id=project_id,
                data_source_id=repository_data_source_id,
                diff_sync_job_id=diff_sync_job_id,
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
        diff_sync_job_id: UUID,
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
                diff_sync_job_id=diff_sync_job_id,
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
        diff_sync_job_id: UUID,
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
                diff_sync_job_id=diff_sync_job_id,
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
        file_history.diff_sync_job_id = diff_sync_job_id
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
        diff_sync_job_id: UUID,
        async_session: AsyncSession,
    ):
        """Refresh the denormalized counts / sync metadata."""
        from sqlalchemy import func
        stmt = select(func.count()).select_from(ProjectAffectedFile).where(
            ProjectAffectedFile.project_id == project_id,
            ProjectAffectedFile.data_source_id == repository_data_source_id,
        )
        res = await async_session.execute(stmt)
        file_count = res.scalar_one()

        repo_changes.file_count = file_count
        repo_changes.diff_sync_job_id = diff_sync_job_id
        repo_changes.last_synced_time = datetime.now(timezone.utc)
        async_session.add(repo_changes)
        await async_session.flush()



    async def get_total_repository_code_changes(self, project_id: UUID, data_source_id: UUID | None = None) -> list[dict]:
        """
        Get the accumulation of `Repository Code Changes` that we're introduced as a part of this Project
            - shows all changes across each Repository that are a part of this Project if no DataSourceID supplied 
        
        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID | None): The ID of the Data Source to filter the changes by.
        """


    async def get_project_repo_summary(
        self, 
        project_id: UUID, 
        data_source_id: UUID,
        async_session: AsyncSession | None = None
    ) -> ProjectRepoSummary | None:
        """
        Get the accumulation of `Repository Code Changes` that we're introduced as a part of this Project
            - shows all changes across each Repository that are a part of this Project if no DataSourceID supplied 
        
        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID): The ID of the Data Source to filter the changes by.
            async_session (AsyncSession?): optional AsyncSession to leverage if this is a background job (default to use this if present)
        """
        stmt = select(ProjectRepoSummary).where(ProjectRepoSummary.project_id == project_id, ProjectRepoSummary.data_source_id == data_source_id)
        result = await async_session.execute(stmt) if async_session else await self.async_db.execute(stmt)
        return result.scalar_one_or_none()

    async def adelete_project_repo_summary(self, project_id: UUID, data_source_id: UUID) -> None:
        """
        Delete the ProjectRepoSummary record associated with a given Project and Data Source.
        This cascades down to ProjectAffectedFile and PullRequest records.
        """
        stmt = select(ProjectRepoSummary).where(
            ProjectRepoSummary.project_id == project_id,
            ProjectRepoSummary.data_source_id == data_source_id
        )
        result = await self.async_db.execute(stmt)
        repo_changes = result.scalar_one_or_none()
        if repo_changes:
            await self.async_db.delete(repo_changes)
            await self.async_db.flush()



    async def get_file_diffs(self, project_id: UUID, data_source_id: UUID) -> list[ProjectAffectedFile]:
        """
        Get the `project_affected_file` records that are associated with a given Project and DataSource
        """
        stmt = select(ProjectAffectedFile).where(ProjectAffectedFile.project_id == project_id, ProjectAffectedFile.data_source_id == data_source_id)
        result = await self.async_db.execute(stmt)
        return list(result.scalars().all())

    async def get_project_touched_file_paths(
        self,
        data_source_id: UUID,
        async_session: AsyncSession | None = None,
    ) -> list[str]:
        """
        Return the list of all unique file paths touched by any project on a specific data source.
        """
        stmt = (
            select(ProjectAffectedFile.file_path)
            .where(
                ProjectAffectedFile.data_source_id == data_source_id,
                ProjectAffectedFile.change_type != ChangeType.DELETED,
            )
            .distinct()
        )
        res = await (async_session or self.async_db).execute(stmt)
        return list(res.scalars().all())

    async def build_scoped_repository_file_id_map(self, project_id: UUID) -> dict[str, list[str]]:
        """
        Returns a mapping of data source IDs (as strings) to list of file IDs (as strings)
        
        This mapping only includes:
          a) Data sources configured for the project (via ProjectData), AND
          b) Data sources that are scoped by issues (scope_by_issues is True and type is REPOSITORY).
          
        Other data sources do not have a ProjectAffectedFile record, and are excluded
        from this mapping (rather than returning empty lists/mappings).
        """
        stmt = (
            select(DataSource.id, func.array_agg(File.id))
            .join(ProjectData, ProjectData.data_source_id == DataSource.id)
            .outerjoin(
                ProjectAffectedFile,
                (ProjectAffectedFile.data_source_id == DataSource.id) &
                (ProjectAffectedFile.project_id == project_id)
            )
            .outerjoin(
                File,
                (File.path == ProjectAffectedFile.file_path) &
                (File.data_source_id == ProjectAffectedFile.data_source_id)
            )
            .where(
                ProjectData.project_id == project_id,
                DataSource.type == DataSourceType.REPOSITORY,
                DataSource.scope_by_issues.is_(True)
            )
            .group_by(DataSource.id)
        )
        result = await self.async_db.execute(stmt)
        
        return {
            str(ds_id): [str(fid) for fid in file_ids if fid is not None] if file_ids is not None else []
            for ds_id, file_ids in result.all()
        }

    async def run_diff_sync_pipeline(
        self, project_id: UUID, data_source_id: UUID
    ) -> None:
        """
        Run diff-sync (Refresh Project Changes) for a single scoped repo.
        Opens its own background session lifecycle so failures are isolated.
        """
        try:
            async with get_async_db_session_context() as async_session:
                job = await self.init_diff_sync_job(project_id, data_source_id, async_session=async_session)
                await async_session.commit()

            # execute in its own session (execute_repository_sync_job opens get_async_db_session_context internally)
            await self.execute_repository_sync_job(job.id)

        except Exception as e:
            logger.error(
                f"[SyncProject] Stage 1 failed for DataSource={data_source_id}: {e}",
                exc_info=True,
            )


    async def get_file_diff_string(self, project_id: UUID, data_source_id: UUID, file_path: str) -> str:
        """
        Retrieve the chronological list of per-pull-request diff slices for a file
        introduced by the specified Project.

        Each slice is one merged pull request's change to the file, ordered oldest
        first. The latest slice is NOT a netted composite of all changes — callers
        must reason across the slices to understand the file's net change over time.

        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID): The ID of the Data Source to filter the changes by.
            file_path (str): The path to the file for which to retrieve the changes.
        """
        try:
            stmt = select(ProjectAffectedFile).options(
                selectinload(ProjectAffectedFile.pr_diffs).selectinload(ProjectFileDiff.pull_request)
            ).where(
                ProjectAffectedFile.project_id == project_id,
                ProjectAffectedFile.data_source_id == data_source_id,
                ProjectAffectedFile.file_path == file_path,
            )
            result = await self.async_db.execute(stmt)
            file_history = result.scalar_one_or_none()

            if not file_history or not file_history.pr_diffs:
                return f"No project-scoped changes recorded for the file={file_path} in dataSource={data_source_id} for project_id={project_id}."

            lines: list[str] = [
                f"## Per-PR diff history for `{file_path}` (net change_type: {file_history.change_type.value})",
                "",
                "These are chronological per-pull-request diff slices (oldest first). The latest "
                "entry is NOT the composite of all changes — reason across every slice to determine "
                "the file's net state.",
            ]

            for revision in file_history.pr_diffs:
                pr = revision.pull_request
                issue_key = pr.issue_key if pr and pr.issue_key else "no linked issue"
                merged = pr.merged_at.isoformat() if pr and pr.merged_at else "unknown date"
                pr_number = pr.pr_number if pr else "?"
                lines.append("")
                lines.append(
                    f"### PR #{pr_number} ({issue_key}) merged {merged} — {revision.change_type.value}"
                )
                if revision.diff_truncated:
                    lines.append("WARNING: This diff slice was truncated due to size limits.")
                lines.append("```diff")
                lines.append(revision.unified_diff or "")
                lines.append("```")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Error retrieving file diff for file_path={file_path}, data_source_id={data_source_id}", exc_info=True)
            return f"Error retrieving file diff: {str(e)}"

