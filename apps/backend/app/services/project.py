import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pydantic import ProjectRequest
from app.services.chroma import ChromaService
from app.models import Project

logger = logging.getLogger(__name__)

class ProjectService:
    def __init__(
        self,
        db: Session,
        chroma_svc: ChromaService
    ):
        self.db = db
        self.chroma_svc = chroma_svc

    def create_project(self, request: ProjectRequest) -> dict:
        """
        Functionality to persist new Project based on specified request

        TODO: Validate dependent projects exist, lob is valid, etc
        """

        try:
            # create Project record & flush to DB
            project = Project(
                project_name=request.name,
                epics=request.epics,
                meta_data=request.meta_data,
                lob=request.lob,
                description=request.description,
                dependent_projects=request.dependent_projects 
            )

            self.db.add(project)
            self.db.flush()

            # create records for ChromaCollections
            docs_collection, code_collection = self.chroma_svc.create_collections(
                project_id=project.id,
                project_name=project.project_name,
                docs_embedding_provider=request.docs_embedding_provider,
                docs_embedding_model=request.docs_embedding_model,
                code_embedding_provider=request.code_embedding_provider,
                code_embedding_model=request.code_embedding_model
            )

            return {
                "id": project.id,
                "name": project.project_name,
                "description": project.description,
                "collections": [
                    {
                        "id": code_collection.id,
                        "name": code_collection.name,
                        "type": code_collection.content_type,
                        "provider": code_collection.embedding_provider,
                        "model": code_collection.embedding_model
                    },
                    {
                        "id": docs_collection.id,
                        "name": docs_collection.name,
                        "type": docs_collection.content_type,
                        "provider": docs_collection.embedding_provider,
                        "model": docs_collection.embedding_model
                    },
                ],
            }
        except Exception as e:
            logger.exception(f"Failure occurred while attempting to create project: {str(e)}")
            raise e

    def get_project_by_id(self, project_id) -> dict:
        """
        Functionality to retreive a given Project by a Project Id

        TODO: Ensure user can view this Project
        """

        stmt = select(Project).where(Project.id == project_id)
        project = self.db.execute(stmt).scalars().first()

        return (
            {"id": project.id, "name": project.project_name, "description": project.description}
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
            {"id": project.id, "name": project.project_name, "description": project.description} for project in projects
        ]
