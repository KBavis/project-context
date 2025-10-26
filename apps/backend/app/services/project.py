from sqlalchemy.orm import Session
from app.pydantic import ProjectRequest
from app.models import Project
from app.core import ChromaClientManager
from sqlalchemy import select


class ProjectService:
    def __init__(self, db: Session, chroma_manager: ChromaClientManager):
        self.db = db 
        self.chroma_manager = chroma_manager
    

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

        # create new ChromaDB collection fro new project
        self.create_new_collection(request.name)

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



    def create_new_collection(self, project_name: str) -> None:
        """
        Create a new ChromaDB collection corresponding to the new Project 
        """
        
        # check if project with this name already exists 
        chroma_client = self.chroma_manager.get_sync_client() #TODO: Make this configurable for async vs sync

        collection = chroma_client.get_collection(project_name)
        if collection is not None:
            raise Exception(f"Project with the name {project_name} already exists")
        
        # create new collection 
        chroma_client.create_collection(name=project_name) #TODO: Use embedding manager for configurable embeddings and pass in embedding function 