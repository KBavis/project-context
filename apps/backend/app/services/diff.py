from __future__ import annotations

import logging
from uuid import UUID 
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.services.data_source import DataSourceService
from app.services.git_ops import GitOperationsService
from app.pydantic.file_diff_result import FileDiffResult
from app.services.project import ProjectService
from app.models.data_source import DataSourceType, DataSource
from app.models.project import Project
from app.models.project_repository_changes import ProjectRepositoryChanges
from app.models.file_diff import FileDiff, ChangeType
from app.models.git_commit import GitCommit
from app.data_providers.fetchable.issue_tracker import IssueTrackerDataProvider
from app.data_providers.ingestible.repository import RepositoryDataProvider
from app.pydantic.git_commit import GitCommitDetail

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
    ):
        self.async_db: AsyncSession = async_db
        self.project_svc = project_svc
        self.data_source_svc = data_source_svc
        self.git_ops_svc = git_ops_svc



    async def repository_sync(
            self, 
            repository_data_source_id: UUID, 
            ingestion_job_id: UUID,
            project_ids: list[UUID] | None = None
    ):
        """
        Sync the updates made to a `Repository DataSource`
            - Optionally specify a Project ID to limit the scope of the sync to a particular Project
        
        TODO: Handle failures gracefully (this should likely be a Transactional process, sort of hard to do with Chroma & git though)
              Ensuring that this doesn't get into a corurpt state is vital since the Agent will hallucinate other wise and 
              have bad data to operate from
        
        Args:
            repository_data_source_id (UUID): The ID of the Data Source to sync.
            ingestion_job_id (UUID): The ID of the IngestionJob updating this record.
            project_ids (list[UUID] | None): The IDs of the Projects to limit the sync to.
        """
        # validate that the provided DataSource is of type `REPOSITORY` and configured properly for syncing 
        repository_ds = await self.data_source_svc.aget_data_source_by_id(data_source_id=repository_data_source_id)
        if repository_ds.type != DataSourceType.REPOSITORY or not repository_ds.scope_by_issues:
            logger.warning(f"DataSource with ID {repository_data_source_id} is not configured for repository syncing. Skipping sync.")
            return

        # if no projects are provided, sync the repository for ALL projects 
        if not project_ids:
            projects = await self.project_svc.get_projects_for_data_source(data_source_id=repository_data_source_id)
            project_ids_to_sync = [project["id"] for project in projects]
        else:
            project_ids_to_sync = project_ids

        # ensure that there are Projects to sync before proceeding with the repository sync
        if not project_ids_to_sync:
            logger.warning(f"No Projects found for DataSource={repository_data_source_id}. Skipping repository sync.")
            return
        
        # perform repository sync for each project
        for project_id in project_ids_to_sync:
            logger.info(f"Syncing repository for Project={project_id} and DataSource={repository_data_source_id}")

            # validate that the configured Project has relevant ParentIssues that are required for scoping 
            project = await self.project_svc.aget_project_by_id(project_id=project_id)
            if not project.parent_issues:
                logger.error(f"Project with ID {project_id} does not have any Parent Issues configured. This is invalid as any configured Project for DataSource of type REPOSITORY and scope_by_issues=True requires this information")
                raise Exception(f"Project with ID {project_id} does not have any Parent Issues configured, which is required for Repository syncing")

            # validate IssueTracker DataSource configured for this Project (if != 1 for Project, this will error out)
            issue_tracker_ds = await self.data_source_svc.get_issue_tracker_data_source(project_id)

            # fetch new commits details to know what's changed
            new_commits = await self.get_new_repository_commits(
                issue_tracker_ds,
                repository_ds,
                project
            )
            if not new_commits:
                logger.info(f"No new commits found when syncing Project={project_id} for DataSource={repository_ds.id} -- skipping Git operations")
                continue 
            
            # TODO: We'll need to account for scenario where fatal exception happens downstream 
            # by likely rolling this back (or subsequent Ingesiton Jobs we'll deem know updates needed)
            # persist git commits immediately
            persisted_commits = await self._persist_git_commits(
                project_id=project_id,
                repository_data_source_id=repository_data_source_id,
                commits=new_commits
            )

            # get base sha (parent commit of first Project commit on repository)
            project_repo_changes = await self.get_project_repository_changes(project_id, repository_data_source_id)
            base_sha = project_repo_changes.base_commit_sha if project_repo_changes else None

            # get all commits (including new commits being synced)
            all_commits = await self.get_project_git_commits(project_id, repository_data_source_id)

            # derive per-file composite diffs via ephemeral local git operations
            file_diff_results, resolved_base_sha = await self.sync_repository_branch_git(
                repository_ds=repository_ds,
                all_commits=all_commits,
                base_sha=base_sha
            )

            # persist changes
            await self.persist_repository_diff_changes(
                project_id=project_id,
                repository_data_source_id=repository_data_source_id,
                ingestion_job_id=ingestion_job_id,
                persisted_commits=persisted_commits,
                file_diff_results=file_diff_results,
                resolved_base_sha=resolved_base_sha
            )


    async def persist_repository_diff_changes(
        self,
        project_id: UUID,
        repository_data_source_id: UUID,
        ingestion_job_id: UUID,
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
            ingestion_job_id=ingestion_job_id,
            commits=persisted_commits,
            file_diff_results=file_diff_results,
        )

        # 2. update the ProjectRepositoryChanges metadata
        await self._persist_project_repository_changes(
            project_id=project_id,
            repository_data_source_id=repository_data_source_id,
            ingestion_job_id=ingestion_job_id,
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
        ingestion_job_id: UUID,
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

            stmt = select(FileDiff).where(
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
                    ingestion_job_id=ingestion_job_id,
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
                file_diff_record.ingestion_job_id = ingestion_job_id

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
        ingestion_job_id: UUID,
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
                ingestion_job_id=ingestion_job_id,
                base_commit_sha=resolved_base_sha,
                files_touched=[],
                file_count=0
            )
            self.async_db.add(project_repository_changes)
            await self.async_db.flush()
        else:
            project_repository_changes.ingestion_job_id = ingestion_job_id

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
