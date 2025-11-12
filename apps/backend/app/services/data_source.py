import logging
from uuid import UUID
from typing import List

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.pydantic import DataSourceRequest
from app.models import DataSource, Project, ProjectData
from app.core import settings

logger = logging.getLogger(__name__)

class DataSourceService:
    def __init__(self, db: Session):
        self.db = db 
    

    def create_data_source(self, request: DataSourceRequest) -> dict:
        """
        Functionality to persist new DataSource based on specified request
        """

        self._validate_data_source_request(request)
        
        # create data source
        data_source = DataSource(
            provider=request.provider, 
            url=request.url
        )

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
            raise Exception(f"Failed to retrieve all Projects corresponding to follwoing Project Ids: {missing_ids}")

        # create associations 
        for project in projects:     
            assocation = ProjectData(
                project_id=project.id, 
                data_source_id=data_source.id
            )
            data_source.project_data.append(assocation)

        return {
            "id": data_source.id, 
            "provider": data_source.provider, 
            "linked_projects": project_ids
        }
    


    def get_project_data_sources(self, project_id: UUID) -> List[dict]:
        """
        Functionality to retreive persisted data_sourcs that correspond to particular Project ID
        """

        stmt = select(DataSource).join(DataSource.project_data).where(Project.id == project_id)
        data_sources = self.db.execute(stmt).scalars().all()

        return [{
            "id": data_source.id, 
            "provider" : data_source.provider,
        } for data_source in data_sources]



    

    def _validate_data_source_request(self, request):
        """
        Ensure the specified request is valid
        """

        if request.provider not in settings.VALID_DATA_PROVIDERS:
            raise Exception(f'Invalid provider specified when attempting to create Data Source. Valid Providers: {settings.VALID_PROIVDERS}')

