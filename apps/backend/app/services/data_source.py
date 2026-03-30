from __future__ import annotations
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session



from app.pydantic import DataSourceRequest, CreateDataSourceRequest
from app.models import DataSource, Project, ProjectData
from app.core import settings
from app.services.mcp import MCPService

logger = logging.getLogger(__name__)


class DataSourceService:
    
    def __init__(self, db: Session, mcp_service: MCPService):
        self.db: Session = db
        self.mcp_service: MCPService = mcp_service

    def get_data_source_by_id(self, data_source_id: UUID) -> DataSource:
        """
        Functionality to retrieve a DataSource by ID
        """

        stmt = select(DataSource).where(DataSource.id == data_source_id)
        data_source = self.db.execute(stmt).scalar_one_or_none()

        if not data_source:
            raise Exception(f"Data Source with ID {data_source_id} not found")

        return data_source
        

    def create_data_source(self, request: CreateDataSourceRequest) -> dict[str, object]:
        """
        Functionality to persist new DataSource based on specified request
        """

        # extract data source and MCP config (if any) from request
        data_source_request = request.data_source
        mcp_config = request.mcp_config

        self._validate_data_source_request(data_source_request)

        # configure MCP Config if provided 
        if mcp_config:
            mcp_config = self.mcp_service.find_or_create_mcp_config(mcp_config)

        # create data source
        if data_source_request.provider == "GitHub" and not data_source_request.branch: #TODO: Make this more Generic (any provider liek Bitbucket same deal)
            data_source_request.branch = "main"
        data_source = DataSource(
            provider=data_source_request.provider, 
            url=data_source_request.url, 
            name=data_source_request.name, 
            branch=data_source_request.branch, 
            mcp_config_id=mcp_config.id if mcp_config else None
        )

        # persist & flush new record
        self.db.add(data_source)
        self.db.flush()

        # retrieve Projects corresponding to IDs specified in request
        project_ids = data_source_request.project_ids
        stmt = select(Project).where(Project.id.in_(project_ids))
        projects = self.db.execute(stmt).scalars().all()

        # ensure each project retrieved successfully
        if len(projects) != len(project_ids):
            found_ids = {str(project.id) for project in projects}
            missing_ids = set(data_source_request.project_ids) - found_ids
            raise Exception(
                f"Failed to retrieve all Projects corresponding to follwoing Project Ids: {missing_ids}"
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
            "branch": data_source.branch,
            "config": {"url": data_source.url},
            "linked_projects": [str(pd.project_id) for pd in data_source.project_data],
            "mcp_config": mcp_config if mcp_config else None
        }

    def get_project_data_sources(self, project_id: UUID) -> list[dict[str, object]]:
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
                "branch": data_source.branch,
                "config": {"url": data_source.url},
                "linked_projects": [str(pd.project_id) for pd in data_source.project_data]
            }
            for data_source in data_sources
        ]

    def get_all_data_sources(self) -> list[dict[str, object]]:
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
                "branch": data_source.branch,
                "config": {"url": data_source.url},
                "linked_projects": [str(pd.project_id) for pd in data_source.project_data]
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
