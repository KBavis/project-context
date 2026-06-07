import logging
from uuid import UUID 

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.data_source import DataSourceService
from app.services.project import ProjectService
from app.models.data_source import DataSourceType, DataSource
from app.models.project import Project
from app.models.project_repository_changes import ProjectRepositoryChanges
from app.models.file_diff import FileDiff
from app.models.ingestion_job import IngestionJob
from app.data_providers.fetchable.issue_tracker import IssueTrackerDataProvider
from app.data_providers.ingestible.repository import RepositoryDataProvider


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
            data_source_id (UUID): The ID of the Data Source to sync.
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

            # determine if there are any existing ProjectRepositoryChanges for this Project/DataSource 
            project_repository_changes = await self.get_project_repository_changes(project_id=project_id, data_source_id=repository_data_source_id)
            commit_hashes = await self.process_diffs(
                issue_tracker_ds,
                repository_ds,
                project,
                project_repository_changes
            )

            if not commit_hashes:
                logger.info(f"No new commit hashes found when syncing Project={project_id} for DataSource={repository_ds.id} -- skipping Git operations")
                return 


            # perform neceesary git operations to sync newly processed commits 


            # update / create `file_diff` and `project_repository_changes`



    async def process_diffs(
            self, 
            issue_tracker_ds: DataSource, 
            repository_ds: DataSource,
            project: Project, 
            project_repository_changes: ProjectRepositoryChanges | None = None
    ):
        """
        TODO: Determine output of this step. I think it would make sense to just simply have this be the step 
        that "updates/creates" the PROJECT_DATASOURCE branch and pushes this up to origin. Then, we can have a
        follow on step that will actually a) download the diffs from GitHub / Bitbucket, b) chunk, 
        c) store these in Chroma. 

        Steps:
            1. Get child issues from the Project parent issues 
            2. Determine latest commit from the Bitbucket / GitHub (if available)
            3. Check if the latest commit from Bitbucket matches the commit from last time we synced 
            4. If not, resync 
        """

        # extract prior commit hash from last time syncing Repository & Project changes 
        prior_commit_hash = project_repository_changes.last_seen_commit if project_repository_changes else None

        # get the child issues from Project.parent_issues 
        issue_data_provider = IssueTrackerDataProvider.from_provider(issue_tracker_ds)
        child_issues = await issue_data_provider.get_issues(project.parent_issues)
        if not child_issues:
            logger.warning("No child issues found -- skipping processing repository changes")
            return None

        
        repository_data_provider = RepositoryDataProvider.from_provider(repository_ds)
        
        # determine if latest state of ProjectRepositoryChanges is up-to-date with state in Repository (skip if first time sync)
        if prior_commit_hash:
            logger.info(f"Existing ProjectRepositoryChanges found for Project={project.id} and DataSource={repository_ds.id}. Checking for new commits since last sync.")
            latest_repository_hash = await repository_data_provider.get_latest_commit_sha(child_issues)
            if not latest_repository_hash:
                logger.info(f"No commits found for Repository={repository_ds.id}: skipping syncing")
                return None

            # determine if the repository is synced or not based on commit retreived
            if prior_commit_hash == latest_repository_hash:
                logger.info(f"The previously sycned state of Repository with DataSource={repository_ds.id} and Project={project.id} is up-to-date -- skipping re-syncing")
                return None

        # NOTE: At this point, we've determined new commits have been made regarding this Project/DataSource -- resyncing is necessary
        logger.warning(f"Repository DataSource={repository_ds.id} code changes from Project={project.id} aren't synced: accounting for new commits")

        last_sync_time = project_repository_changes.last_synced_time if project_repository_changes else None
        commit_hashes = await repository_data_provider.get_all_commit_sha(child_issues, last_sync_time)

        logger.info(f"Found {len(commit_hashes)} for Project={project.id} and DataSource={repository_ds.id}")
        return commit_hashes



    async def get_total_repository_code_changes(self, project_id: UUID, data_source_id: UUID | None = None) -> list[dict]:
        """
        Get the accumulation of `Repository Code Changes` that we're introduced as a part of this Project
            - shows all changes across each Repository that are a part of this Project if no DataSourceID supplied 
        
        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID | None): The ID of the Data Source to filter the changes by.
        """


    async def get_project_repository_changes(self, project_id: UUID, data_source_id: UUID) -> ProjectRepositoryChanges:
        """
        Get the accumulation of `Repository Code Changes` that we're introduced as a part of this Project
            - shows all changes across each Repository that are a part of this Project if no DataSourceID supplied 
        
        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID): The ID of the Data Source to filter the changes by.
        """
        stmt = select(ProjectRepositoryChanges).where(ProjectRepositoryChanges.project_id == project_id, ProjectRepositoryChanges.data_source_id == data_source_id)
        result = await self.async_db.execute(stmt)
        return result.scalar_one()


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
    
