from __future__ import annotations
import logging
from uuid import UUID
from typing import Any, TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.ext.asyncio import AsyncSession


from app.pydantic import DataSourceRequest
from app.models import DataSource, Project, ProjectData, File
from app.models.data_source import DataSourceType
from app.services.chroma import ChromaService

if TYPE_CHECKING:
    from app.services.record_lock import RecordLockService
from app.core import settings
from app.data_providers.base import DataProvider, Provider
from app.data_providers.ingestible.base import IngestibleDataProvider
from app.models.data_source_mcp import DataSourceMCPConfig
from app.models.mcp_config import MCPConfig

logger = logging.getLogger(__name__)


class DataSourceService:
    
    def __init__(
        self, 
        async_db: AsyncSession, 
        record_lock_svc: 'RecordLockService',
        db: Session | None = None, 
        chroma_svc: ChromaService | None = None
    ):
        self.db: Session | None = db
        self.async_db: AsyncSession = async_db
        self.chroma_svc: ChromaService | None = chroma_svc
        self.record_lock_svc = record_lock_svc

    async def aget_data_source_by_id(self, data_source_id: UUID) -> DataSource:
        """
        Async functionality to retrieve a DataSource by ID
        """

        stmt = select(DataSource).where(DataSource.id == data_source_id)
        result = await self.async_db.execute(stmt)
        data_source = result.scalar_one_or_none()

        if not data_source:
            raise Exception(f"Data Source with ID {data_source_id} not found")

        return data_source

    
    async def get_issue_tracker_data_source(
        self, 
        project_id: UUID, 
        async_session: AsyncSession
    ) -> DataSource:
        """
        Validate that there is only a single issue tracker for a given Project. This is required for 
        sycning a Repository DataSource for a given Project. If more than 1 Data Source 
        configured for the Project that is an IssueTracker, error out

        TODO: Likely some value in making this more generic (i.e specifying 
        a particular ProviderType and then making validations based on provided type) 

        Args:
            project_id (UUID): the project to validate 
        """

        data_sources = await self.aget_project_data_sources(project_id=project_id, async_session=async_session)
        issue_provider_data_sources = [ds for ds in data_sources if ds.type == DataSourceType.ISSUE_TRACKER]
        if not issue_provider_data_sources or len(issue_provider_data_sources) != 1:
            raise Exception(f"Only one IssueProvider expected to be configured for Project={project_id}, but found {len(issue_provider_data_sources)}")
        
        return issue_provider_data_sources[0]


    def get_data_source_by_id(self, data_source_id: UUID) -> DataSource:
        """
        Functionality to retrieve a DataSource by ID
        """
        assert self.db is not None, "Synchronous DB session is required"

        stmt = select(DataSource).where(DataSource.id == data_source_id)
        data_source = self.db.execute(stmt).scalar_one_or_none()

        if not data_source:
            raise Exception(f"Data Source with ID {data_source_id} not found")

        return data_source
        

    def create_data_source(self, data_source_request: DataSourceRequest) -> dict[str, Any]:
        """
        Functionality to persist new DataSource based on specified request
        """
        assert self.db is not None, "Synchronous DB session is required"
        assert self.chroma_svc is not None, "Chroma Service is required"

        self._validate_data_source_request(data_source_request)

        # create data source
        if data_source_request.type == DataSourceType.REPOSITORY and data_source_request.provider == "GitHub" and not data_source_request.branch: #TODO: Make this more Generic (any provider liek Bitbucket same deal)
            data_source_request.branch = "main"



        data_source = DataSource(
            provider=data_source_request.provider, 
            url=data_source_request.url, 
            name=data_source_request.name, 
            branch=data_source_request.branch,
            type=data_source_request.type,
            scope_by_issues=data_source_request.scope_by_issues,
        )

        # Construct the concrete provider and validate the URL is in the
        # provider's expected format (raises if malformed). Validation is done
        # here at creation time rather than on every provider construction.
        data_provider = DataProvider.from_provider(data_source)
        data_provider._validate_url()

        # persist & flush new record
        self.db.add(data_source)
        self.db.flush()

        try:
            self.chroma_svc.create_collection(
                data_source_id=data_source.id,
                data_source_name=data_source.name
            )
        except Exception as e:
            self.db.rollback()
            raise Exception(f"Failed to create Chroma Collection for Data Source: {str(e)}")

        # retrieve Projects corresponding to IDs specified in request
        project_ids = data_source_request.project_ids
        stmt = select(Project).where(Project.id.in_(project_ids))
        projects = self.db.execute(stmt).scalars().all()

        # ensure each project retrieved successfully
        if len(projects) != len(project_ids):
            found_ids = {(project.id) for project in projects}
            missing_ids = set(data_source_request.project_ids) - found_ids
            raise Exception(
                f"Failed to retrieve all Projects corresponding to follwoing Project Ids: {missing_ids}"
            )

        # validate that if scope_by_issues is True, all projects have parent_issues configured
        if data_source_request.scope_by_issues:
            projects_without_parent_issues = [p for p in projects if not p.parent_issues]
            if projects_without_parent_issues:
                project_ids_str = ", ".join(str(p.id) for p in projects_without_parent_issues)
                raise ValueError(
                    f"Cannot link Projects to Data Source with scope_by_issues=True unless they have parent_issues configured. "
                    f"Projects without parent_issues: {project_ids_str}"
                )

            # Bitbucket repositories resolve commits through Jira, so each
            # linked project must have an associated Jira issue tracker.
            self._validate_bitbucket_requires_jira(data_source_request.provider, list(projects))

        # create associations
        for project in projects:
            assocation = ProjectData(
                project_id=project.id, data_source_id=data_source.id
            )
            data_source.project_data.append(assocation)
        
        # flush to ensure relationships are loaded/persisted
        self.db.flush()

        # If this DataSource creation included linked projects AND it's an
        # issue-scoped repository, commit the sync transaction so any
        # background async sessions (e.g. DiffSync jobs) can see the
        # newly-created `project_data` rows. We only commit in this
        # specific case to avoid committing other create flows prematurely.
        if (
            data_source_request.type == DataSourceType.REPOSITORY
            and data_source_request.scope_by_issues
            and data_source_request.project_ids
        ):
            self.db.commit()


        return {
            "id": data_source.id,
            "provider": data_source.provider,
            "name": data_source.name,
            "type": data_source.type,
            "branch": data_source.branch,
            "scope_by_issues": data_source.scope_by_issues,
            "config": {"url": data_source.url},
            "linked_projects": [str(pd.project_id) for pd in data_source.project_data]
        }
    

    async def aget_project_data_sources(self, project_id: UUID, async_session: AsyncSession | None = None) -> list[DataSource]:
        """
        Functionality to retreive persisted data_sourcs that correspond to particular Project ID

        Args:
            project_id (UUID): the unique project ID to retrieve data sources for 
            async_session (AsyncSession?): optional session to leverage when executing this query (used if query is ran via Background Job)
        """

        stmt = (
            select(DataSource)
            .options(
                selectinload(DataSource.project_data),
                selectinload(DataSource.data_source_mcp_configs).selectinload(DataSourceMCPConfig.mcp_config)
            )
            .join(DataSource.project_data)
            .where(ProjectData.project_id == project_id)
        )

        # default to use provided async_session if present, else use service's injected Async DB session
        data_sources = await async_session.execute(stmt) if async_session else await self.async_db.execute(stmt)
        return list(data_sources.scalars().unique().all())

    async def aget_data_source_ids_by_type(
        self, project_id: UUID, source_type: DataSourceType | None = None
    ) -> list[str]:
        """
        Get all data source IDs for a given project, optionally filtered by DataSourceType. When no
        source_type is specified, only data sources that support ingestion (REPOSITORY, DOCUMENTATION)
        are returned — these are the only ones we'll have chunks stored for in Chroma/DocStore.

        This is the primary resolver used by the Tools wrappers to determine which 
        collections to search.

        Args:
            project_id (UUID): The project ID.
            source_type (DataSourceType | None): Optional type filter (REPOSITORY, DOCUMENTATION, etc).
        """
        data_sources = await self.aget_project_data_sources(project_id)
        if source_type:
            data_sources = [ds for ds in data_sources if ds.type == source_type]
        else:
            valid_ds = []
            for ds in data_sources:
                try:
                    IngestibleDataProvider.from_provider(ds)
                    valid_ds.append(ds)
                except Exception:
                    pass
            data_sources = valid_ds

        return [str(ds.id) for ds in data_sources]

    async def get_ingestible_data_sources(
        self, project_id: UUID, async_session: AsyncSession | None = None
    ) -> list[DataSource]:
        """
        Return only the data sources linked to a project that support file ingestion/chunking
        (i.e. REPOSITORY and DOCUMENTATION types). Purely fetchable sources such as ISSUE_TRACKER
        are excluded.

        Args:
            project_id (UUID): The project to query data sources for.
            async_session (AsyncSession | None): Optional session override for background jobs.
        """
        all_sources = await self.aget_project_data_sources(project_id, async_session)
        
        valid_ds = []
        for ds in all_sources:
            try:
                IngestibleDataProvider.from_provider(ds)
                valid_ds.append(ds)
            except Exception:
                pass
        
        return valid_ds

    def get_project_data_sources(self, project_id: UUID) -> list[dict[str, Any]]:
        """
        Functionality to retreive persisted data_sourcs that correspond to particular Project ID
        """
        assert self.db is not None, "Synchronous DB session is required"

        stmt = (
            select(DataSource)
            .join(DataSource.project_data)
            .where(ProjectData.project_id == project_id)
        )
        data_sources = self.db.execute(stmt).scalars().unique().all()

        return [
            {
                "id": data_source.id,
                "provider": data_source.provider,
                "name": data_source.name,
                "type": data_source.type,
                "branch": data_source.branch,
                "scope_by_issues": data_source.scope_by_issues,
                "config": {"url": data_source.url},
                "linked_projects": [str(pd.project_id) for pd in data_source.project_data],
                "mcp_configs": [
                    {
                        "id": link.mcp_config.id,
                        "name": link.mcp_config.name,
                        "transport_type": link.mcp_config.transport_type.value,
                        "timeout": link.mcp_config.timeout,
                        "config": link.mcp_config.config
                    }
                    for link in data_source.data_source_mcp_configs
                ]
            }
            for data_source in data_sources
        ]

    def get_all_data_sources(self) -> list[dict[str, Any]]:
        """
        Functionality to retrieve all persisted data sources
        """
        assert self.db is not None, "Synchronous DB session is required"

        stmt = select(DataSource)
        data_sources = self.db.execute(stmt).scalars().unique().all()

        return [
            {
                "id": data_source.id,
                "provider": data_source.provider,
                "name": data_source.name,
                "type": data_source.type,
                "branch": data_source.branch,
                "scope_by_issues": data_source.scope_by_issues,
                "config": {"url": data_source.url},
                "linked_projects": [str(pd.project_id) for pd in data_source.project_data],
                "mcp_configs": [
                    {
                        "id": link.mcp_config.id,
                        "name": link.mcp_config.name,
                        "transport_type": link.mcp_config.transport_type.value,
                        "timeout": link.mcp_config.timeout,
                        "config": link.mcp_config.config
                    }
                    for link in data_source.data_source_mcp_configs
                ]
            }
            for data_source in data_sources
        ]

    def delete_data_source(self, data_source_id: UUID) -> list[UUID]:
        """
        Delete a DataSource after validating edge cases:
        1. Cannot delete an ISSUE_TRACKER that is the sole issue provider for a project
           with active scope_by_issues REPOSITORY sources.
        2. Cannot delete while IN_PROGRESS ingestion jobs exist.
        3. Cleans up Chroma collection, ProjectData associations, and cascaded relationships.
        """
        from app.models import RecordType
        assert self.db is not None, "Synchronous DB session is required"
        assert self.chroma_svc is not None, "Chroma Service is required"

        stmt = (
            select(DataSource)
            .options(
                selectinload(DataSource.project_data).selectinload(ProjectData.project).selectinload(Project.project_data).selectinload(ProjectData.data_source),
                selectinload(DataSource.embed_tasks),
                selectinload(DataSource.chroma_collection),
            )
            .where(DataSource.id == data_source_id)
        )
        ds = self.db.execute(stmt).scalar_one_or_none()
        if not ds:
            raise ValueError(f"Data Source with ID {data_source_id} not found")

        # Guard: block delete if data source is currently locked
        is_locked = self.record_lock_svc.is_locked_sync(self.db, data_source_id, RecordType.DATA_SOURCE)
        if is_locked:
            raise ValueError(
                "Cannot delete this data source while it is currently locked (e.g., active ingestion job running). "
                "Please wait for it to complete or cancel it first."
            )

        # Guard: if this is an ISSUE_TRACKER, check if any linked project depends on it
        if ds.type == DataSourceType.ISSUE_TRACKER:
            for pd in ds.project_data:
                project = pd.project
                scoped_repos = [
                    other_pd.data_source for other_pd in project.project_data
                    if other_pd.data_source.type == DataSourceType.REPOSITORY
                    and other_pd.data_source.scope_by_issues
                ]
                if scoped_repos:
                    raise ValueError(
                        f"Cannot delete this Issue Tracker because project "
                        f"\"{project.project_name}\" has repository data sources scoped by issues "
                        f"that depend on it. Remove or un-scope those repositories first."
                    )

        # Clean up Chroma collection if it exists
        if ds.chroma_collection:
            try:
                self.chroma_svc.delete_collection(data_source_id)
            except Exception as e:
                logger.warning(f"Failed to delete Chroma collection for DataSource={data_source_id}: {e}")

        # Manually delete ProjectData associations (no cascade on this relationship)
        for pd in list(ds.project_data):
            self.db.delete(pd)

        # Extract file_ids before we drop the records so the background job can scrub them from Chroma/DocStore
        file_ids = list(self.db.execute(select(File.id).where(File.data_source_id == data_source_id)).scalars())

        # Delete the data source (cascades handle embed_tasks, files, mcp_configs, chroma_collection)
        self.db.delete(ds)
        self.db.flush()
        
        return file_ids

    def update_data_source(self, data_source_id: UUID, updates: dict) -> dict[str, Any]:
        """
        Update mutable fields of a DataSource


        Args:
            data_source_id: UUID of the DataSource to update
            updates: dict containing fields to update (e.g. `name`, `branch`, `scope_by_issues`)
        """
        assert self.db is not None, "Synchronous DB session is required"
        # retrieve existing data source
        stmt = select(DataSource).where(DataSource.id == data_source_id)
        ds = self.db.execute(stmt).scalar_one_or_none()
        if not ds:
            raise Exception(f"Data Source with ID {data_source_id} not found")

        # Reject attempts to change `type` or `provider` via update - require recreate.
        if "type" in updates or "provider" in updates:
            raise ValueError(
                "Changing `type` or `provider` of a Data Source is not allowed. "
                "Please delete and recreate the Data Source with the desired type/provider."
            )

        # Determine target type (what the DataSource will be after the update)
        target_type = ds.type

        # Disallow setting branch when resulting type is not REPOSITORY
        if "branch" in updates and target_type != DataSourceType.REPOSITORY:
            raise ValueError("Cannot set 'branch' unless the resulting Data Source type is REPOSITORY")

        # Validate `scope_by_issues` updates using helper to keep logic centralized.
        if "scope_by_issues" in updates:
            val = updates.get("scope_by_issues")
            self._validate_scope_by_issues_update(ds, target_type, val)

        # Apply allowed updates (exclude `type` and `provider` — those require recreate)
        allowed = {"name", "branch", "scope_by_issues", "url"}
        for k, v in updates.items():
            if k in allowed:
                setattr(ds, k, v)

        # If resulting type is not REPOSITORY, normalize repo-only fields
        if ds.type != DataSourceType.REPOSITORY:
            ds.branch = None
            ds.scope_by_issues = False

        # persist
        self.db.add(ds)
        self.db.flush()

        return {
            "id": ds.id,
            "provider": ds.provider,
            "name": ds.name,
            "type": ds.type,
            "branch": ds.branch,
            "scope_by_issues": ds.scope_by_issues,
            "config": {"url": ds.url},
            "linked_projects": [str(pd.project_id) for pd in ds.project_data]
        }

    def _project_has_jira_issue_tracker(self, project_id: UUID) -> bool:
        """
        Return True if the given project has an associated Jira ISSUE_TRACKER
        data source. Used to enforce the Bitbucket<->Jira coupling required
        for issue-scoped Bitbucket repositories.
        """
        assert self.db is not None, "Synchronous DB session is required"

        stmt = (
            select(DataSource)
            .join(ProjectData, ProjectData.data_source_id == DataSource.id)
            .where(
                ProjectData.project_id == project_id,
                DataSource.type == DataSourceType.ISSUE_TRACKER,
                DataSource.provider == Provider.JIRA.value,
            )
        )
        return self.db.execute(stmt).scalars().first() is not None

    def _validate_bitbucket_requires_jira(self, provider: str, projects: list[Project]) -> None:
        """
        Enforce the Bitbucket<->Jira coupling for issue-scoped repositories:
        Bitbucket resolves commits through Jira's dev-status API, so every
        linked project must have an associated Jira issue tracker.

        No-op for non-Bitbucket providers.
        """
        if provider != Provider.BITBUCKET.value:
            return

        projects_without_jira = [p for p in projects if not self._project_has_jira_issue_tracker(p.id)]
        if projects_without_jira:
            names = ", ".join(f"{p.project_name} ({p.id})" for p in projects_without_jira)
            raise ValueError(
                "Cannot enable issue scoping on this Bitbucket Data Source unless each linked "
                "project has an associated Jira issue tracker configured (Bitbucket resolves commits "
                f"through Jira). Projects without a Jira issue tracker: {names}"
            )

    def _validate_data_source_request(self, request: DataSourceRequest):
        """
        Ensure the specified request is valid
        """

        try:
            Provider(request.provider)
        except ValueError:
            valid_providers = [p.value for p in Provider]
            raise Exception(
                f"Invalid provider specified when attempting to create Data Source. Valid Providers: {valid_providers}"
            )

    def _validate_scope_by_issues_update(self, ds: DataSource, target_type: DataSourceType, val: bool | None):
        """
        Centralized validation for updating `scope_by_issues`.

        - Enabling (`True`) requires the resulting `target_type` to be `REPOSITORY`
          and all linked projects must have `parent_issues` configured.
        - Disabling (`False`) is allowed only when the Data Source is linked to
          zero or one project; otherwise require unlinking first.
        - `None` (not provided) is ignored by caller.
        """
        if val is None:
            return

        # Enabling
        if val is True:
            if target_type != DataSourceType.REPOSITORY:
                raise ValueError("`scope_by_issues` can only be enabled for REPOSITORY Data Sources")

            linked_projects = [pd.project for pd in ds.project_data] if ds.project_data else []
            projects_missing = [p for p in linked_projects if not p.parent_issues]
            if projects_missing:
                names = ", ".join([f"{p.project_name} ({p.id})" for p in projects_missing])
                raise ValueError(
                    "Cannot enable `scope_by_issues` on this Data Source because the following linked projects "
                    f"do not have parent_issues configured: {names}. Please update those projects to include parent_issues "
                    "(issue numbers) before enabling scoping, or unlink them from this Data Source."
                )

            # Bitbucket repositories resolve commits through Jira, so each
            # linked project must have an associated Jira issue tracker.
            self._validate_bitbucket_requires_jira(ds.provider, linked_projects)

        # Disabling
        if val is False:
            linked_projects = [pd.project for pd in ds.project_data] if ds.project_data else []
            if len(linked_projects) > 1:
                names = ", ".join([f"{p.project_name} ({p.id})" for p in linked_projects])
                raise ValueError(
                    "Cannot disable `scope_by_issues` while this Data Source is linked to multiple projects: "
                    f"{names}. Unlink other projects from this Data Source before disabling scoping."
                )



    def link_mcp_config_to_data_source(self, data_source_id: UUID, mcp_config_id: UUID) -> dict[str, Any]:
        """
        Link an existing MCP Config to this DataSource
        """

        assert self.db is not None, "Synchronous DB session is required"

        try:
            # check if relationship already exists
            stmt = select(DataSourceMCPConfig).where(
                DataSourceMCPConfig.data_source_id == data_source_id,
                DataSourceMCPConfig.mcp_config_id == mcp_config_id
            )
            existing = self.db.execute(stmt).scalar_one_or_none()
            
            if existing:
                return {"message": "MCP config is already linked to this data source", "status": "already_linked"}

            # verify that both elements exist
            ds_stmt = select(DataSource).where(DataSource.id == data_source_id)
            ds = self.db.execute(ds_stmt).scalar_one_or_none()
            if not ds:
                raise Exception(f"Data source {data_source_id} not found")

            mcp_stmt = select(MCPConfig).where(MCPConfig.id == mcp_config_id)
            mcp = self.db.execute(mcp_stmt).scalar_one_or_none()
            if not mcp:
                raise Exception(f"MCP config {mcp_config_id} not found")

            # create association
            association = DataSourceMCPConfig(
                data_source_id=data_source_id,
                mcp_config_id=mcp_config_id
            )
            self.db.add(association)
            self.db.flush()
            
            return {
                "message": f"Successfully linked MCP config {mcp_config_id} to data source {data_source_id}",
                "status": "success",
                "data_source_id": str(data_source_id),
                "mcp_config_id": str(mcp_config_id)
            }
        except Exception as e:
            logger.exception(f"Failure occurred while linking MCP config to data source: {str(e)}")
            raise e
