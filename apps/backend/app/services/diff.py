from __future__ import annotations

import logging
from uuid import UUID 
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from fastapi import HTTPException
from sqlalchemy.orm import selectinload

from app.services.data_source import DataSourceService
from app.services.git_ops import GitOperationsService
from app.pydantic.file_diff_result import FileDiffResult
from app.services.project import ProjectService
from app.models.data_source import DataSourceType, DataSource
from app.models.project import Project
from app.models.project_repository_changes import ProjectRepositoryChanges
from app.models.file_diff import FileDiff, ChangeType
from app.models.git_commit import GitCommit
from app.models.diff_sync_job import DiffSyncJob
from app.models.ingestion_job import ProcessingStatus
from app.models.record_lock import RecordType
from app.services.record_lock import RecordLockService
from app.models.project_data import ProjectData
from app.data_providers.fetchable.issue_tracker import IssueTrackerDataProvider
from app.data_providers.ingestible.repository import RepositoryDataProvider
from app.pydantic.git_commit import GitCommitDetail
from app.models.project_data import ProjectData
from app.core import get_async_session_maker
import uuid

logger = logging.getLogger(__name__)


class DiffService:
    """
    Service responsible for handling all operations related 
    to `Repository Code Changes` for a particular Project 
    """

    def __init__(
        self, 
        async_db: AsyncSession, 
        project_svc: ProjectService, 
        data_source_svc: DataSourceService,
        git_ops_svc: GitOperationsService,
        record_lock_svc: RecordLockService,
    ):
        self.async_db: AsyncSession = async_db
        self.project_svc = project_svc
        self.data_source_svc = data_source_svc
        self.git_ops_svc = git_ops_svc
        self.record_lock_svc = record_lock_svc
    

    async def validate_project_sync_complete(self, project_id: UUID) -> None:
        """
        Validates that all repository data sources associated with this project 
        have completed their initial sync.
        """
        # Fetch data sources linked to the project
        linked_data_sources = await self.data_source_svc.aget_project_data_sources(project_id)
        
        # Filter for repository data sources that are issue scoped
        repo_data_sources = [ds for ds in linked_data_sources if ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues]
        
        for ds in repo_data_sources:
            stmt = select(ProjectRepositoryChanges).where(
                ProjectRepositoryChanges.project_id == project_id,
                ProjectRepositoryChanges.data_source_id == ds.id
            )
            res = await self.async_db.execute(stmt)
            record = res.scalars().first()
            
            if not record:
                raise HTTPException(
                    status_code=412,
                    detail="The repository code changes for this project are performing their first time synchronization. Please wait for this to complete."
                )

    async def get_project_sync_state(self, project_id: UUID) -> str:
        """
        Determines the overall synchronization state of a project's repository data sources.
        Returns: 'success', 'in_progress', or 'failed'
        """
        linked_data_sources = await self.data_source_svc.aget_project_data_sources(project_id)
        repo_data_sources = [ds for ds in linked_data_sources if ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues]
        
        logger.info(f"[SyncState] project_id={project_id}: found {len(linked_data_sources)} linked data sources, {len(repo_data_sources)} are issue-scoped repositories")
        
        if not repo_data_sources:
            logger.info(f"[SyncState] project_id={project_id}: no issue-scoped repos → success")
            return ProcessingStatus.SUCCESS.value
            
        states = []
        for ds in repo_data_sources:
            # Check if sync is already complete for this ds
            stmt = select(ProjectRepositoryChanges).where(
                ProjectRepositoryChanges.project_id == project_id,
                ProjectRepositoryChanges.data_source_id == ds.id
            )
            res = await self.async_db.execute(stmt)
            if res.scalars().first():
                logger.info(f"[SyncState] project_id={project_id}, ds={ds.id} ({ds.name}): ProjectRepositoryChanges record exists → success")
                states.append(ProcessingStatus.SUCCESS.value)
                continue
                
            # If not complete, check the latest DiffSyncJob
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
            else:
                logger.info(f"[SyncState] project_id={project_id}, ds={ds.id} ({ds.name}): no DiffSyncJob found → failed")
                states.append(ProcessingStatus.FAILED.value)
        
        logger.info(f"[SyncState] project_id={project_id}: all states={states}")
        
        if ProcessingStatus.IN_PROGRESS.value in states:
            return ProcessingStatus.IN_PROGRESS.value
        if ProcessingStatus.FAILED.value in states:
            return ProcessingStatus.FAILED.value
            
        return ProcessingStatus.SUCCESS.value


    async def init_diff_sync_job(self, project_id: UUID, data_source_id: UUID) -> DiffSyncJob:
        """
        Validate ProjectData and create initial diff sync job with IN_PROGRESS status
        """
        
        # validate ProjectData exists
        stmt = select(ProjectData).where(ProjectData.project_id == project_id, ProjectData.data_source_id == data_source_id)
        res = await self.async_db.execute(stmt)
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
        self.async_db.add(job)
        await self.async_db.flush()
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

    async def execute_repository_sync_job(self, job_id: UUID):

        # retrieve the initalized DiffSyncJob
        stmt = select(DiffSyncJob).where(DiffSyncJob.id == job_id)
        res = await self.async_db.execute(stmt)
        job = res.scalar_one_or_none()
        
        if not job:
            logger.error(f"No DiffSyncJob found for ID: {job_id}")
            raise Exception(f"No DiffSyncJob found for ID: {job_id}")

        pair_lock_key = f"sync:{job.project_id}:{job.data_source_id}"
        lock_uuid = uuid.uuid5(uuid.NAMESPACE_OID, pair_lock_key)
        job_start_time = job.start_time

        try:
            repository_ds = await self.data_source_svc.aget_data_source_by_id(data_source_id=job.data_source_id)
            project = await self.project_svc.aget_project_by_id(project_id=job.project_id)
            
            issue_tracker_ds = await self.data_source_svc.get_issue_tracker_data_source(job.project_id)

            new_commits = await self.get_new_repository_commits(
                issue_tracker_ds,
                repository_ds,
                project
            )

            if new_commits:
                persisted_commits = await self._persist_git_commits(
                    project_id=job.project_id,
                    repository_data_source_id=job.data_source_id,
                    commits=new_commits
                )

                project_repo_changes = await self.get_project_repository_changes(job.project_id, job.data_source_id)
                base_sha = project_repo_changes.base_commit_sha if project_repo_changes else None

                all_commits = await self.get_project_git_commits(job.project_id, job.data_source_id)

                file_diff_results, resolved_base_sha = await self.sync_repository_branch_git(
                    repository_ds=repository_ds,
                    all_commits=all_commits,
                    base_sha=base_sha
                )

                await self.persist_repository_diff_changes(
                    project_id=job.project_id,
                    repository_data_source_id=job.data_source_id,
                    diff_sync_job_id=job_id,
                    persisted_commits=persisted_commits,
                    file_diff_results=file_diff_results,
                    resolved_base_sha=resolved_base_sha
                )
            else:
                logger.info(f"No new GitCommits found for DataSource={job.data_source_id} and Project={job.project_id}. Marking DiffSyncJob as successful and updating the ProjectRepositoryChanges object to reflect succesful completion")

                project_repo_changes = await self.get_project_repository_changes(job.project_id, job.data_source_id)
                if not project_repo_changes:
                    # create blank ProjectRepositoryChanges record in the case that this is first sync AND no commits found
                    project_repo_changes = ProjectRepositoryChanges(
                        project_id=job.project_id,
                        data_source_id=job.data_source_id,
                        diff_sync_job_id=job_id,
                        files_touched=[],
                        file_count=0
                    )
                    self.async_db.add(project_repo_changes)
                else:
                    # update existing ProjectReposiotryChanges record to indicate last processed by this DiffSyncJob
                    project_repo_changes.diff_sync_job_id = job_id
                    project_repo_changes.last_synced_time = datetime.now(timezone.utc)
                await self.async_db.flush()

            # update DiffSyncJob status as successful
            end_time = datetime.now(timezone.utc)
            duration = int((end_time - job_start_time).total_seconds())
            await self.update_diff_sync_job(
                job_id=job_id,
                status=ProcessingStatus.SUCCESS,
                end_time=end_time,
                duration=duration,
                session=self.async_db,
                commit=False
            )

        except Exception as e:
            logger.error(f"Error during execute_repository_sync_job for job {job_id}: {e}", exc_info=True)
            
            # update the DiffSyncJob with appropaite status and error message when failing
            session_maker = get_async_session_maker()
            async with session_maker() as session:
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
        finally:
            # always unlock ProjectData record after job completes
            await self.record_lock_svc.unlock(lock_uuid, record_type=RecordType.PROJECT_DATA)


    async def persist_repository_diff_changes(
        self,
        project_id: UUID,
        repository_data_source_id: UUID,
        diff_sync_job_id: UUID,
        persisted_commits: list[GitCommit],
        file_diff_results: list[FileDiffResult],
        resolved_base_sha: str,
    ):
        """
        Orchestrate the persistence of all repository diff changes across FileDiff, 
        and ProjectRepositoryChanges models.
        """
        logger.info(f"Persisting changes for Project={project_id} and DataSource={repository_data_source_id}")

        # 1. persist the FileDiff records associated with those commits
        await self._persist_file_diffs(
            project_id=project_id,
            repository_data_source_id=repository_data_source_id,
            diff_sync_job_id=diff_sync_job_id,
            commits=persisted_commits,
            file_diff_results=file_diff_results,
        )

        # 2. update the ProjectRepositoryChanges metadata
        await self._persist_project_repository_changes(
            project_id=project_id,
            repository_data_source_id=repository_data_source_id,
            diff_sync_job_id=diff_sync_job_id,
            resolved_base_sha=resolved_base_sha
        )


    async def _persist_git_commits(
        self,
        project_id: UUID,
        repository_data_source_id: UUID,
        commits: list[GitCommitDetail]
    ) -> list[GitCommit]:
        """
        Save the new GitCommit records. Raise exception if we see a commit we thought was new
        but it already exists in the database (corrupt state).
        """
        persisted_commits = []
        for commit in commits:
            # check if commit already exists
            stmt = select(GitCommit).where(GitCommit.commit_hash == commit.sha)
            res = await self.async_db.execute(stmt)
            existing_commit = res.scalar_one_or_none()

            if existing_commit:
                raise Exception(
                    f"Corrupt state detected: Commit {commit.sha} is reported as a new commit "
                    f"to sync, but it already exists in the database."
                )

            commit_record = GitCommit(
                commit_hash=commit.sha,
                project_id=project_id,
                data_source_id=repository_data_source_id,
                author_name=commit.author_name,
                author_email=commit.author_email,
                commit_datetime=commit.commit_datetime,
                message=commit.message,
                files_modified=commit.files_modified
            )
            self.async_db.add(commit_record)
            persisted_commits.append(commit_record)

        await self.async_db.flush()
        return persisted_commits


    async def _persist_file_diffs(
        self,
        project_id: UUID,
        repository_data_source_id: UUID,
        diff_sync_job_id: UUID,
        commits: list[GitCommit],
        file_diff_results: list[FileDiffResult],
    ):
        """
        Update/create FileDiff records from the composite diff results produced
        by GitOperationsService, then link them to the relevant GitCommit records.

        The FileDiffResult objects are keyed by file_path. For each file:
          - If no existing FileDiff row exists, a new one is created with the
            full composite diff data (unified_diff, diff_hash, change_type, etc.).
          - If a row already exists (i.e. this is a subsequent sync for the same
            file), the diff content and conflict metadata are updated in place.

        Change type is inferred from the unified diff header:
          - Lines starting with "new file mode" → ADDED
          - Lines starting with "deleted file mode" → DELETED
          - All other diffs → MODIFIED
        """
        # build a lookup from file_path → FileDiffResult for O(1) access
        diff_by_path: dict[str, FileDiffResult] = {
            r.file_path: r for r in file_diff_results
        }

        # build a lookup from file_path → list[GitCommit] so we can link commits
        # that touched a given path regardless of whether we have a diff for it
        commits_by_path: dict[str, list[GitCommit]] = {}
        for commit in commits:
            for file_path in commit.files_modified:
                commits_by_path.setdefault(file_path, []).append(commit)

        # union of all paths: those with diff results + any touched by commits
        all_paths = set(diff_by_path) | set(commits_by_path)

        for file_path in all_paths:
            diff_result = diff_by_path.get(file_path)

            # determine change type from the diff header when available
            change_type = self._infer_change_type(diff_result)

            stmt = select(FileDiff).options(
                selectinload(FileDiff.commits)
            ).where(
                FileDiff.project_id == project_id,
                FileDiff.data_source_id == repository_data_source_id,
                FileDiff.file_path == file_path,
            )
            res = await self.async_db.execute(stmt)
            file_diff_record = res.scalar_one_or_none()

            if not file_diff_record:
                file_diff_record = FileDiff(
                    project_id=project_id,
                    data_source_id=repository_data_source_id,
                    file_path=file_path,
                    change_type=change_type,
                    unified_diff=diff_result.unified_diff if diff_result else None,
                    diff_hash=diff_result.diff_hash if diff_result else "",
                    diff_truncated=diff_result.diff_truncated if diff_result else False,
                    conflict_detected=diff_result.conflict_detected if diff_result else False,
                    failed_commit_shas=diff_result.failed_commit_shas if diff_result else [],
                    diff_sync_job_id=diff_sync_job_id,
                )
                self.async_db.add(file_diff_record)
                await self.async_db.flush()
            else:
                # update composite diff to reflect newly cherry-picked commits
                if diff_result:
                    file_diff_record.unified_diff = diff_result.unified_diff
                    file_diff_record.diff_hash = diff_result.diff_hash
                    file_diff_record.diff_truncated = diff_result.diff_truncated
                    file_diff_record.conflict_detected = diff_result.conflict_detected
                    file_diff_record.failed_commit_shas = diff_result.failed_commit_shas
                    file_diff_record.change_type = change_type
                file_diff_record.diff_sync_job_id = diff_sync_job_id

            # link commits that touched this file
            for commit in commits_by_path.get(file_path, []):
                if commit not in file_diff_record.commits:
                    file_diff_record.commits.append(commit)

        # Delete any stale FileDiff records that are no longer part of the project's net changes
        # (e.g. if a file's changes were completely reverted by a new commit)
        if all_paths:
            stmt = delete(FileDiff).where(
                FileDiff.project_id == project_id,
                FileDiff.data_source_id == repository_data_source_id,
                FileDiff.file_path.notin_(all_paths)
            )
        else:
            stmt = delete(FileDiff).where(
                FileDiff.project_id == project_id,
                FileDiff.data_source_id == repository_data_source_id
            )
        await self.async_db.execute(stmt)

        await self.async_db.flush()


    def _infer_change_type(self, diff_result: FileDiffResult | None) -> ChangeType:
        """
        Determine the net ChangeType from the unified diff header lines.

        Git diff headers contain:
          "new file mode ..."      → file was created by the project
          "deleted file mode ..."  → file was removed by the project
          anything else            → file was modified

        Falls back to UNKNOWN when no diff result is available (e.g. a file
        appeared in files_modified but the cherry-pick failed entirely).
        """
        if not diff_result or not diff_result.unified_diff:
            return ChangeType.UNKNOWN
        header = diff_result.unified_diff[:500]  # only need the first few lines
        if "new file mode" in header:
            return ChangeType.ADDED
        if "deleted file mode" in header:
            return ChangeType.DELETED
        return ChangeType.MODIFIED


    async def _persist_project_repository_changes(
        self,
        project_id: UUID,
        repository_data_source_id: UUID,
        diff_sync_job_id: UUID,
        resolved_base_sha: str
    ):
        """
        Update or create the ProjectRepositoryChanges record and update its files_touched list.
        """
        project_repository_changes = await self.get_project_repository_changes(
            project_id=project_id, 
            data_source_id=repository_data_source_id
        )

        if not project_repository_changes:
            project_repository_changes = ProjectRepositoryChanges(
                project_id=project_id,
                data_source_id=repository_data_source_id,
                diff_sync_job_id=diff_sync_job_id,
                base_commit_sha=resolved_base_sha,
                files_touched=[],
                file_count=0
            )
            self.async_db.add(project_repository_changes)
            await self.async_db.flush()
        else:
            project_repository_changes.diff_sync_job_id = diff_sync_job_id


        # Update files_touched
        stmt = select(FileDiff.file_path).where(
            FileDiff.project_id == project_id,
            FileDiff.data_source_id == repository_data_source_id
        )
        res = await self.async_db.execute(stmt)
        touched_paths = res.scalars().all()

        project_repository_changes.files_touched = list(set(touched_paths))
        project_repository_changes.file_count = len(project_repository_changes.files_touched)
        project_repository_changes.last_synced_time = datetime.now(timezone.utc)

        self.async_db.add(project_repository_changes)
        await self.async_db.flush()


    async def get_new_repository_commits(
            self, 
            issue_tracker_ds: DataSource, 
            repository_ds: DataSource,
            project: Project
    ) -> list[GitCommitDetail]:
        """
        Process new repository commits that have been added as a result of specified Project.
        """
        # determine the latest commit datetime dynamically
        stmt = (
            select(GitCommit)
            .where(GitCommit.project_id == project.id, GitCommit.data_source_id == repository_ds.id)
            .order_by(GitCommit.commit_datetime.desc())
            .limit(1)
        )
        res = await self.async_db.execute(stmt)
        latest_commit = res.scalar_one_or_none()
        last_sync_time = latest_commit.commit_datetime if latest_commit else None

        # get the child issues from Project.parent_issues 
        issue_data_provider = IssueTrackerDataProvider.from_provider(issue_tracker_ds)
        child_issues = await issue_data_provider.get_issues(project.parent_issues)
        if not child_issues:
            logger.warning("No child issues found -- skipping processing repository changes")
            return []

        repository_data_provider = RepositoryDataProvider.from_provider(repository_ds)
        
        # determine if latest state is up-to-date with state in Repository (skip if first time sync)
        if latest_commit:
            logger.info(f"Existing GitCommits found for Project={project.id} and DataSource={repository_ds.id}. Checking for new commits since last sync.")
            latest_repository_hash = await repository_data_provider.get_latest_commit_sha(child_issues)
            if not latest_repository_hash:
                raise Exception(
                    f"Inconsistent state detected: Local DB has active commits for Project {project.id}, "
                    f"but remote repository search returned no matching commits. This may be caused by a "
                    f"change in configured parent issues or a remote history change."
                )

            # determine if the repository is synced or not based on commit retrieved
            if latest_commit.commit_hash == latest_repository_hash:
                logger.info(f"The previously sycned state of Repository with DataSource={repository_ds.id} and Project={project.id} is up-to-date -- skipping re-syncing")
                return []

        # At this point, new commits have been made regarding this Project/DataSource -- resyncing is necessary
        logger.warning(f"Repository DataSource={repository_ds.id} code changes from Project={project.id} aren't synced: accounting for new commits")
        new_commits = await repository_data_provider.get_all_commits_info(child_issues, last_sync_time)
        logger.info(f"Found {len(new_commits)} new commits for Project={project.id} and DataSource={repository_ds.id}")
        return new_commits


    async def get_total_repository_code_changes(self, project_id: UUID, data_source_id: UUID | None = None) -> list[dict]:
        """
        Get the accumulation of `Repository Code Changes` that we're introduced as a part of this Project
            - shows all changes across each Repository that are a part of this Project if no DataSourceID supplied 
        
        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID | None): The ID of the Data Source to filter the changes by.
        """


    async def get_project_repository_changes(self, project_id: UUID, data_source_id: UUID) -> ProjectRepositoryChanges | None:
        """
        Get the accumulation of `Repository Code Changes` that we're introduced as a part of this Project
            - shows all changes across each Repository that are a part of this Project if no DataSourceID supplied 
        
        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID): The ID of the Data Source to filter the changes by.
        """
        stmt = select(ProjectRepositoryChanges).where(ProjectRepositoryChanges.project_id == project_id, ProjectRepositoryChanges.data_source_id == data_source_id)
        result = await self.async_db.execute(stmt)
        return result.scalar_one_or_none()


    async def get_file_diffs(self, project_id: UUID, data_source_id: UUID) -> list[FileDiff]:
        """
        Get the `file_diff` records that are associated with a given Project and DataSource
        """
        stmt = select(FileDiff).where(FileDiff.project_id == project_id, FileDiff.data_source_id == data_source_id)
        result = await self.async_db.execute(stmt)
        return list(result.scalars().all())

    async def get_file_diff_string(self, project_id: UUID, data_source_id: UUID, file_path: str) -> str:
        """
        Retrieve the resulting unfiied Diff for a specific File in a Repository Data Source as a
        result of the changes introduced by the specified Project. Format the diff with relevant 
        context including a) if there were conflicts in processing diff due to commit failures, b)
        the diff was truncated, and c) what change type correspnd to the file 

        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID): The ID of the Data Source to filter the changes by.
            file_path (str): The path to the file for which to retrieve the changes.
        """
        try:
            stmt = select(FileDiff).where(
                FileDiff.project_id == project_id,
                FileDiff.data_source_id == data_source_id,
                FileDiff.file_path == file_path,
            )
            result = await self.async_db.execute(stmt)
            file_diff = result.scalar_one_or_none()

            if not file_diff or not file_diff.unified_diff:
                return f"No project-scoped changes recorded for the file={file_path} in dataSource={data_source_id} for project_id={project_id}."

            header = f"## Diff for `{file_path}` (change_type: {file_diff.change_type.value})\n"
            if file_diff.conflict_detected:
                header += f"WARNING: Conflict detected — some commits could not be cleanly applied: {file_diff.failed_commit_shas}\n"
            if file_diff.diff_truncated:
                header += "WARNING: Diff was truncated due to size limits.\n"

            return header + "\n```diff\n" + file_diff.unified_diff + "\n```"

        except Exception as e:
            logger.error(f"Error retrieving file diff for file_path={file_path}, data_source_id={data_source_id}", exc_info=True)
            return f"Error retrieving file diff: {str(e)}"


    async def get_project_git_commits(self, project_id: UUID, data_source_id: UUID) -> list[GitCommit]:
        """
        Get all GitCommits persisted in the database for a specific Project and DataSource in chronological order
        """
        stmt = (
            select(GitCommit)
            .where(
                GitCommit.project_id == project_id, 
                GitCommit.data_source_id == data_source_id
            )
            .order_by(GitCommit.commit_datetime.asc())
        )
        result = await self.async_db.execute(stmt)
        return list(result.scalars().all())


    async def sync_repository_branch_git(
        self,
        repository_ds: DataSource,
        all_commits: list[GitCommit],
        base_sha: str | None = None
    ) -> tuple[list[FileDiffResult], str]:
        """
        Perform an ephemeral blobless shallow clone of the repository, cherry-pick
        the project's commits onto an isolated temp branch, extract the composite
        per-file unified diffs, and clean up.  Nothing is ever pushed to origin.

        Args:
            repository_ds:  The repository DataSource (provides the clone URL).
            all_commits:    List of GitCommitDetail or GitCommit in **chronological (ascending)
                            order** — all project commits to be cherry picked.
            base_sha:       Optional base SHA to root the temp branch on.

        Returns:
            A tuple of (file_diff_results, resolved_base_sha).
        """
        if not all_commits:
            return [], ""

        commit_shas = [c.commit_hash for c in all_commits]
        logger.info(
            f"Starting ephemeral git ops for DataSource={repository_ds.id}: "
            f"{len(commit_shas)} commit(s) to cherry-pick"
        )

        file_diff_results, resolved_base_sha = await self.git_ops_svc.build_composite_diffs(
            clone_url=repository_ds.url,
            commit_shas=commit_shas,
            base_sha=base_sha
        )

        failed_count = sum(1 for r in file_diff_results if r.conflict_detected)
        logger.info(
            f"Git ops complete for DataSource={repository_ds.id}: "
            f"{len(file_diff_results)} file(s) diffed, "
            f"{failed_count} with unresolved conflict(s)"
        )
        return file_diff_results, resolved_base_sha
