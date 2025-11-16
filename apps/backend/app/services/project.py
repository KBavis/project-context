import logging

from chromadb.api import ClientAPI

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pydantic import ProjectRequest
from app.models import Project, ModelConfigs
from app.core import ChromaClientManager
from app.services.util import get_normalized_project_name

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(
        self,
        db: Session,
        chroma_manager: ChromaClientManager
    ):
        self.db = db
        self.chroma_manager = chroma_manager

    def create_project(self, request: ProjectRequest) -> dict:
        """
        Functionality to persist new Project based on specified request

        """
        project = Project(
            project_name=request.name,
            epics=request.epics,
            # TODO: Add logic to validate specified provider/model pairs
            model_configs=ModelConfigs(
                docs_embedding_provider=request.docs_embedding_provider,
                docs_embedding_model=request.docs_embedding_model,
                code_embedding_provider=request.code_embedding_provider,
                code_embedding_model=request.code_embedding_model,
            ),
        )

        # persist & flush new Projectrecord
        self.db.add(project)
        self.db.flush()

        # create new ChromaDB collections for new project
        self.create_new_collections(request.name)

        return {
            "id": project.id,
            "name": project.project_name,
            "model_configs_id": project.model_configs.id,
        }

    def get_project_by_id(self, project_id) -> dict:
        """
        Functionality to retreive a given Project by a Project Id

        TODO: Ensure user can view this Project
        """

        stmt = select(Project).where(Project.id == project_id)
        project = self.db.execute(stmt).scalars().first()

        return (
            {"id": project.id, "name": project.project_name}
            if project
            else {"message": f"No project found corresponding to ID {project_id}"}
        )

    def get_all_projects(self):
        """
        Get all persisted projects

        TODO: Only fetch projects that requesting user is authenticated to see
        """

        stmt = select(Project)
        projects = self.db.execute(stmt).scalars().all()

        return [
            {"id": project.id, "name": project.project_name} for project in projects
        ]


    def create_new_collections(self, project_name: str) -> None:
        """
        Create a new ChromaDB collection corresponding to the new Project

        TODO: Consider moving this functionality out of Project Service into its own ChromaDbService or soemthing
        """

        PROJECT = get_normalized_project_name(project_name)
        chroma_client = (
            self.chroma_manager.get_sync_client()
        )  # TODO: Make this configurable for async vs sync

        # verify docs collection do not exist
        self._verify_project_collections_dne(
            chroma_client, PROJECT, original_name=project_name
        )

        # create new CODE and DOCS collections for project
        """
        To account for two collections per project, a sophisitcated way of using RAG will need to be implemented. Either some sort of routing functionality
        based on the posed question or a conveint way to query information from both collecitons if the the posed question corresponds to both.
        """
        chroma_client.create_collection(
            name=f"{PROJECT}_CODE",
        )
        chroma_client.create_collection(name=f"{PROJECT}_DOCS")

    def _verify_project_collections_dne(
        self, chroma_client: ClientAPI, project_name: str, original_name: str
    ) -> None:
        """
        Helper function for verifying relevant collections for specified project do not exist already

        NOTE: ChromaDB will raise exception in the case the collction does not exist by name
        """

        project_dne = True

        # attempt to retrieve docs chroma db collection
        try:
            chroma_client.get_collection(f"{project_name}_DOCS")
            project_dne = False
        except Exception as e:
            pass

        # attempt to retrieve code chromadb collection
        try:
            chroma_client.get_collection(f"{project_name}_CODE")
            project_dne = False
        except Exception as e:
            pass

        # error out if either one exists (as this indicates a project with this name is in use)
        if project_dne == False:
            raise Exception(f"Project with the name {original_name} already exists")
