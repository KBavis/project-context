from sqlalchemy.orm import Session
from app.pydantic import ProjectRequest
from app.models import Project
from uuid import UUID
from sqlalchemy import select


class ProjectService:
    def __init__(self, db: Session):
        self.db = db 
    

    def create_project(self, request: ProjectRequest) -> dict:
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

        return {
            "id": project.id,
            "name": project.project_name
        }
    

    def get_project_by_id(self, project_id) -> dict:
        """
        Functionality to retreive a given Project by a Project Id

        TODO: Ensure user can view this Project
        """

        stmt = select(Project).where(Project.id == project_id)
        project = self.db.execute(stmt).scalars().first()

        return {
            "id": project.id,
            "name": project.project_name 
        }  if project else {
            "message": f"No project found corresponding to ID {project_id}"
        }


    def get_all_projects(self):
        """
        Get all persisted projects 

        TODO: Only fetch projects that requesting user is authenticated to see 
        """

        stmt = select(Project)
        projects = self.db.execute(stmt).scalars().all()

        return [{
            "id": project.id, 
            "name": project.project_name
        } for project in projects]