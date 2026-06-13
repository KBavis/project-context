from __future__ import annotations
import logging
from uuid import UUID
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession



from app.pydantic import DataSourceRequest
from app.models import DataSource, Project, ProjectData
from app.models.data_source import DataSourceType
from app.services.chroma import ChromaService
from app.core import settings
from app.data_providers.ingestible.base import IngestibleDataProvider

logger = logging.getLogger(__name__)


class DataSourceService:
    
    def __init__(self, db: Session, async_db: AsyncSession, chroma_svc: ChromaService):
        self.db: Session = db
        self.async_db: AsyncSession = async_db
        self.chroma_svc = chroma_svc

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

    
    async def get_issue_tracker_data_source(self, project_id: UUID) -> DataSource:
        """
        Validate that there is only a single issue tracker for a given Project. This is required for 
        sycning a Repository DataSource for a given Project. If more than 1 Data Source 
        configured for the Project that is an IssueTracker, error out

        TODO: Likely some value in making this more generic (i.e specifying 
        a particular ProviderType and then making validations based on provided type) 

        Args:
            project_id (UUID): the project to validate 
        """

        data_sources = await self.aget_project_data_sources(project_id=project_id)
        issue_provider_data_sources = [ds for ds in data_sources if ds.type == DataSourceType.ISSUE_TRACKER]
        if not issue_provider_data_sources or len(issue_provider_data_sources) != 1:
            raise Exception(f"Only one IssueProvider expected to be configured for Project={project_id}, but found {len(issue_provider_data_sources)}")
        
        return issue_provider_data_sources[0]


    def get_data_source_by_id(self, data_source_id: UUID) -> DataSource:
        """
        Functionality to retrieve a DataSource by ID
        """

        stmt = select(DataSource).where(DataSource.id == data_source_id)
        data_source = self.db.execute(stmt).scalar_one_or_none()

        if not data_source:
            raise Exception(f"Data Source with ID {data_source_id} not found")

        return data_source
        

    def create_data_source(self, data_source_request: DataSourceRequest) -> dict[str, Any]:
        """
        Functionality to persist new DataSource based on specified request
        """

        self._validate_data_source_request(data_source_request)

        # create data source
        if data_source_request.provider == "GitHub" and not data_source_request.branch: #TODO: Make this more Generic (any provider liek Bitbucket same deal)
            data_source_request.branch = "main"
        data_source = DataSource(
            provider=data_source_request.provider, 
            url=data_source_request.url, 
            name=data_source_request.name, 
            branch=data_source_request.branch,
            type=data_source_request.type,
            scope_by_issues=data_source_request.scope_by_issues
        )

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

        # create associations
        for project in projects:
            assocation = ProjectData(
                project_id=project.id, data_source_id=data_source.id
            )
            data_source.project_data.append(assocation)
        
        # flush to ensure relationships are loaded/persisted
        self.db.flush()


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
    

    async def aget_project_data_sources(self, project_id: UUID) -> list[DataSource]:
        """
        Functionality to retreive persisted data_sourcs that correspond to particular Project ID
        """

        from sqlalchemy.orm import selectinload
        from app.models.data_source_mcp import DataSourceMCPConfig

        stmt = (
            select(DataSource)
            .options(
                selectinload(DataSource.project_data),
                selectinload(DataSource.data_source_mcp_configs).selectinload(DataSourceMCPConfig.mcp_config)
            )
            .join(DataSource.project_data)
            .where(ProjectData.project_id == project_id)
        )
        data_sources = await self.async_db.execute(stmt)
        return list(data_sources.scalars().unique().all())

    async def aget_data_source_ids_by_type(
        self, project_id: UUID, source_type: DataSourceType | None = None
    ) -> list[str]:
        """
        Get all data source IDs for a given project, optionally filtered by DataSourceType. In the case 
        that no source_type was specified, we will ONLY get the Data Sources that we have ingested
        data for (assocaited IngestibleDataProvider) as these are the only Data Sources 
        that we'll be able to leverage via grep_search and semantic_search 

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

    def get_project_data_sources(self, project_id: UUID) -> list[dict[str, Any]]:
        """
        Functionality to retreive persisted data_sourcs that correspond to particular Project ID
        """

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

    def _validate_data_source_request(self, request: DataSourceRequest):
        """
        Ensure the specified request is valid
        """

        if request.provider not in settings.VALID_DATA_PROVIDERS:
            raise Exception(
                f"Invalid provider specified when attempting to create Data Source. Valid Providers: {settings.VALID_DATA_PROVIDERS}"
            )

    def link_mcp_config_to_data_source(self, data_source_id: UUID, mcp_config_id: UUID) -> dict[str, Any]:
        """
        Link an existing MCP Config to this DataSource
        """
        from app.models.data_source_mcp import DataSourceMCPConfig
        from app.models.mcp_config import MCPConfig

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
