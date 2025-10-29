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

        # create new ChromaDB collections for new project
        self.create_new_collections(request.name)

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



    def create_new_collections(self, project_name: str) -> None:
        """
        Create a new ChromaDB collection corresponding to the new Project 

        TODO: Consider moving this functionality out of Project Service into its own ChromaDbService or soemthing 
        """

        PROJECT = project_name.upper()
        chroma_client = self.chroma_manager.get_sync_client() #TODO: Make this configurable for async vs sync

        def verify_collection_dne(postifx: str) -> None:
            """
            Helper function for verifying relevant collections for specified project do not exist already
            """
            collection = chroma_client.get_collection(f"{PROJECT}_{postifx}")
            if collection is not None:
                raise Exception(f"Project with the name {PROJECT}_{postifx} already exists")


        # verify docs collection is not existent
        verify_collection_dne("DOCS") 
        verify_collection_dne("CODE")
        

        # create new CODE and DOCS collections for project
        """
        TODO: Use configured embedding functions for Code & Docs instead of default embeddings when creating collections. In the long run, 
        this should be transitioned to only create a CODE collection in the case that this relates to SWE project (indicated via Project request)

        To account for two collections per project, a sophisitcated way of using RAG will need to be implemented. Either some sort of routing functionality
        based on the posed question or a conveint way to query information from both collecitons if the the posed question corresponds to both.
        """
        chroma_client.create_collection(name=f"{PROJECT}_CODE") 
        chroma_client.create_collection(name=f"{PROJECT}_DOCS")
    
