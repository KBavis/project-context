from __future__ import annotations
import logging
from uuid import UUID
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession



from app.pydantic import DataSourceRequest
from app.models import DataSource, Project, ProjectData
from app.core import settings

logger = logging.getLogger(__name__)


class DataSourceService:
    
    def __init__(self, db: Session, async_db: AsyncSession):
        self.db: Session = db
        self.async_db: AsyncSession = async_db

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
            type=data_source_request.type
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
            found_ids = {(project.id) for project in projects}
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
            "type": data_source.type,
            "branch": data_source.branch,
            "config": {"url": data_source.url},
            "linked_projects": [str(pd.project_id) for pd in data_source.project_data]
        }
    

    async def aget_project_data_sources(self, project_id: UUID) -> list[dict[str, Any]]:
        """
        Functionality to retreive persisted data_sourcs that correspond to particular Project ID
        """

        from sqlalchemy.orm import selectinload

        stmt = (
            select(DataSource)
            .options(
                selectinload(DataSource.project_data),
                selectinload(DataSource.mcp_config)
            )
            .join(DataSource.project_data)
            .where(ProjectData.project_id == project_id)
        )
        data_sources = await self.async_db.execute(stmt)
        unique_ds = data_sources.scalars().unique().all()


        return [
            {
                "id": data_source.id,
                "provider": data_source.provider,
                "name": data_source.name,
                "type": data_source.type,
                "branch": data_source.branch,
                "config": {"url": data_source.url},
                "linked_projects": [str(pd.project_id) for pd in data_source.project_data],
                "mcp_config": {
                    "id": data_source.mcp_config.id,
                    "name": data_source.mcp_config.name,
                    "transport_type": data_source.mcp_config.transport_type.value,
                    "timeout": data_source.mcp_config.timeout,
                    "config": data_source.mcp_config.config
                } if data_source.mcp_config else None
            }
            for data_source in unique_ds
        ]

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
                "config": {"url": data_source.url},
                "linked_projects": [str(pd.project_id) for pd in data_source.project_data],
                "mcp_config": {
                    "id": data_source.mcp_config.id,
                    "name": data_source.mcp_config.name,
                    "transport_type": data_source.mcp_config.transport_type.value,
                    "timeout": data_source.mcp_config.timeout,
                    "config": data_source.mcp_config.config
                } if data_source.mcp_config else None
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
                "config": {"url": data_source.url},
                "linked_projects": [str(pd.project_id) for pd in data_source.project_data],
                "mcp_config": {
                    "id": data_source.mcp_config.id,
                    "name": data_source.mcp_config.name,
                    "transport_type": data_source.mcp_config.transport_type.value,
                    "timeout": data_source.mcp_config.timeout,
                    "config": data_source.mcp_config.config
                } if data_source.mcp_config else None
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
