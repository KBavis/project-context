import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session



from app.pydantic import DataSourceRequest
from app.models import DataSource, Project, ProjectData
from app.core import settings

logger = logging.getLogger(__name__)


class DataSourceService:
    
    def __init__(self, db: Session):
        self.db: Session = db

    def create_data_source(self, request: DataSourceRequest) -> dict[str, object]:
        """
        Functionality to persist new DataSource based on specified request
        """

        self._validate_data_source_request(request)

        # create data source
        data_source = DataSource(provider=request.provider, url=request.url, name=request.name)

        # persist & flush new record
        self.db.add(data_source)
        self.db.flush()

        # retrieve Projects corresponding to IDs specified in request
        project_ids = request.project_ids
        stmt = select(Project).where(Project.id.in_(project_ids))
        projects = self.db.execute(stmt).scalars().all()

        # ensure each project retrieved successfully
        if len(projects) != len(project_ids):
            found_ids = {str(project.id) for project in projects}
            missing_ids = set(request.project_ids) - found_ids
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
            "config": {"url": data_source.url},
            "linked_projects": [str(pd.project_id) for pd in data_source.project_data],
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
