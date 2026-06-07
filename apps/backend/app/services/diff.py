from __future__ import annotations

import logging
from uuid import UUID 
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.data_source import DataSourceService
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
    ):
        self.async_db: AsyncSession = async_db
        self.project_svc = project_svc
        self.data_source_svc = data_source_svc



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

            # fetch new commits details
            new_commits = await self.get_new_repository_commits(
                issue_tracker_ds,
                repository_ds,
                project
            )
            if not new_commits:
                logger.info(f"No new commits found when syncing Project={project_id} for DataSource={repository_ds.id} -- skipping Git operations")
                continue 

            # TODO: Invoke git operations
            # 1. Checkout or create a temporary ProjectBranch on the Repository.
            # 2. Cherry-pick the new_commits onto this branch in chronological order.
            # 3. Push the branch up to origin.
            logger.info("TODO: Invoke git operations (checkout/create branch, cherry-pick new commits, push up)")

            # persist changes
            await self.persist_repository_diff_changes(
                project_id=project_id,
                repository_data_source_id=repository_data_source_id,
                ingestion_job_id=ingestion_job_id,
                new_commits=new_commits
            )


    async def persist_repository_diff_changes(
        self,
        project_id: UUID,
        repository_data_source_id: UUID,
        ingestion_job_id: UUID,
        new_commits: list[GitCommitDetail]
    ):
        """
        Orchestrate the persistence of all repository diff changes across GitCommit, FileDiff, 
        and ProjectRepositoryChanges models.
        """
        logger.info(f"Persisting changes for Project={project_id} and DataSource={repository_data_source_id}")

        # 1. persist the new GitCommit records
        persisted_commits = await self._persist_git_commits(
            project_id=project_id,
            repository_data_source_id=repository_data_source_id,
            commits=new_commits
        )

        # 2. persist the FileDiff records associated with those commits
        await self._persist_file_diffs(
            project_id=project_id,
            repository_data_source_id=repository_data_source_id,
            ingestion_job_id=ingestion_job_id,
            commits=persisted_commits
        )

        # 3. update the ProjectRepositoryChanges metadata
        await self._persist_project_repository_changes(
            project_id=project_id,
            repository_data_source_id=repository_data_source_id,
            ingestion_job_id=ingestion_job_id
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
        commits: list[GitCommit]
    ):
        """
        Update/create FileDiff records and link them to the GitCommit records.
        """
        for commit in commits:
            for file_path in commit.files_modified:
                # check if file_diff already exists
                stmt = select(FileDiff).where(
                    FileDiff.project_id == project_id,
                    FileDiff.data_source_id == repository_data_source_id,
                    FileDiff.file_path == file_path
                )
                res = await self.async_db.execute(stmt)
                file_diff_record = res.scalar_one_or_none()

                if not file_diff_record:
                    # TODO: extract composite file diffs (i.e get the hunks/unified diff for this file)
                    # from the ProjectBranch and set unified_diff, diff_hash, etc.
                    # TODO: dynamically determine the net ChangeType of the file (e.g. ADDED if the file is
                    # new, DELETED if removed, MODIFIED if updated) during composite diff extraction.
                    file_diff_record = FileDiff(
                        project_id=project_id,
                        data_source_id=repository_data_source_id,
                        file_path=file_path,
                        change_type=ChangeType.MODIFIED, 
                        unified_diff=None,  # placeholder until git extraction is implemented
                        diff_hash="",       # placeholder until git extraction is implemented
                        diff_truncated=False,
                        ingestion_job_id=ingestion_job_id
                    )
                    self.async_db.add(file_diff_record)
                    await self.async_db.flush()
                else:
                    # TODO: Update composite file diffs (unified diff and diff hash)
                    # after cherry-picking the new commits.
                    file_diff_record.ingestion_job_id = ingestion_job_id

                if commit not in file_diff_record.commits:
                    file_diff_record.commits.append(commit)

        await self.async_db.flush()


    async def _persist_project_repository_changes(
        self,
        project_id: UUID,
        repository_data_source_id: UUID,
        ingestion_job_id: UUID
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


    async def sync_repository_branch_git(self):
        """
        Perform necessary Git operations to a) create / checkout relevant Project's repository branch, b) cherry
        pick relevant commits onto this branch, c) push up to origin
        """
