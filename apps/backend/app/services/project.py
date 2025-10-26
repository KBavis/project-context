from sqlalchemy.orm import Session
from app.pydantic import ProjectRequest
from app.models import Project
from uuid import UUID
from sqlalchemy import select


class ProjectService:
    def __init__(self, db: Session):
        self.db = db 
    

    def create_project(self, request: ProjectRequest) -> Project:
        """
        Functionality to persist new Project based on specified request

        TODO: Creeate new ChromaDB Collection when Project created 
        """
        project = Project(
            project_name=request.name,
            epics=request.epics,
        )

        # persist & flush new record 
        self.db.add(project)
        self.db.flush() 

        return project 
    

    def get_project_by_id(self, project_id):
        """
        Functionality to retreive a given Project by a Project Id

        TODO: Ensure user can view this Project
        """

        stmt = select(Project).where(Project.id == project_id)
        return self.db.execute(stmt).scalars().first()


    def get_all_projects(self):
        """
        Get all persisted projects 

        TODO: Only fetch projects that requesting user is authenticated to see 
        """

        stmt = select(Project)
        return self.db.execute(stmt).scalars().all()