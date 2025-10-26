from sqlalchemy.orm import Session
from app.pydantic import DataSourceRequest
from app.models import DataSource, Project
from uuid import UUID
from sqlalchemy import select


class DataSourceService:
    def __init__(self, db: Session):
        self.db = db 
    

    def create_data_source(self, request: DataSourceRequest) -> DataSource:
        """
        Functionality to persist new DataSource based on specified request
        """
        
        # create data source
        data_source = DataSource(
            provider=request.provider, 
            source_type=request.source_type, 
            token=request.token,
            api_key=request.api_key,
            url=request.url
        )

        # persist & flush new record 
        self.db.add(data_source)
        self.db.flush() 

        # retrieve Projects corresponding to IDs specified in request
        project_ids = request.project_ids
        stmt = select(Project).where(Project.id in project_ids)
        projects = self.db.execute(stmt).scalars().all()

        # ensure each project retrieved successfully 
        if len(projects) != len(project_ids):
            raise Exception(f"Failed to retrieve all Projects specified by the Project IDs {project_ids}")

        # TODO: Create assocation        

        return data_source
    


    def get_project_data_sources(self, project_id: UUID):
        """
        Functionality to retreive persisted data_sourcs that correspond to particular Project ID
        """

        stmt = select(DataSource).join(DataSource.project_data).where(Project.id == project_id)
        return self.db.execute(stmt).scalars().all()



    

