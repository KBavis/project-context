from __future__ import annotations
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from app.pydantic import ProjectRequest
from app.services.chroma import ChromaService
from app.models import Project, ProjectData, DataSource
from uuid import UUID

logger = logging.getLogger(__name__)

class ProjectService:
    def __init__(
        self,
        db: Session,
        async_db: AsyncSession,
        chroma_svc: ChromaService
    ):
        self.db = db
        self.async_db = async_db
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
                parent_issues=request.parent_issues,
                meta_data=request.meta_data,
                lob=request.lob,
                description=request.description,
                dependent_projects=request.dependent_projects 
            )

            self.db.add(project)
            self.db.flush()

            # create records for ChromaCollections
            chroma_collection = self.chroma_svc.create_collection(
                project_id=project.id,
                project_name=project.project_name,
                embedding_provider=request.embedding_provider,
                embedding_model=request.embedding_model
            )

            return {
                "id": project.id,
                "name": project.project_name,
                "description": project.description,
                "collection": {
                    "id": chroma_collection.id,
                    "name": chroma_collection.name,
                    "provider": chroma_collection.embedding_provider,
                    "model": chroma_collection.embedding_model
                }
            }
        except Exception as e:
            logger.exception(f"Failure occurred while attempting to create project: {str(e)}")
            raise e
    

    async def get_projects_for_data_source(self, data_source_id: UUID) -> list[dict]:
        """
        Get all Projects that are linked to a given DataSource ID
        """

        stmt = select(Project).join(ProjectData).where(ProjectData.data_source_id == data_source_id)
        projects = self.db.execute(stmt).scalars().all()

        return [
            {"id": project.id, "name": project.project_name, "description": project.description} for project in projects
        ]


    async def aget_project_by_id(self, project_id) -> Project:
        """
        Async functionality to retreive a given Project by a Project Id
        """
        
        stmt = select(Project).where(Project.id == project_id)
        result = await self.async_db.execute(stmt)
        project = result.scalars().first()

        if not project:
            raise Exception(f"No project found corresponding to ID {project_id}")

        return project
        

    def get_project_by_id(self, project_id) -> dict:
        """
        Functionality to retreive a given Project by a Project Id

        TODO: Ensure user can view this Project
        """

        stmt = select(Project).where(Project.id == project_id)
        project = self.db.execute(stmt).scalars().first()

        return (
            {"id": project.id, "name": project.project_name, "description": project.description, "parent_issues": project.parent_issues}
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

    def link_data_source_to_project(self, project_id: UUID, data_source_id: UUID) -> dict:
        """
        Link an existing DataSource to this Project
        """
        try:
            # check if relationship already exists
            stmt = select(ProjectData).where(
                ProjectData.project_id == project_id,
                ProjectData.data_source_id == data_source_id
            )
            existing = self.db.execute(stmt).scalar_one_or_none()
            
            if existing:
                return {"message": "Data source is already linked to this project", "status": "already_linked"}

            # retrieve the project to check parent_issues
            project_stmt = select(Project).where(Project.id == project_id)
            project = self.db.execute(project_stmt).scalar_one_or_none()
            if not project:
                raise Exception(f"Project with ID {project_id} not found")

            # retrieve the data source to check scope_by_issues
            ds_stmt = select(DataSource).where(DataSource.id == data_source_id)
            data_source = self.db.execute(ds_stmt).scalar_one_or_none()
            if not data_source:
                raise Exception(f"Data Source with ID {data_source_id} not found")

            # validate that if data source has scope_by_issues=True, project must have parent_issues
            if data_source.scope_by_issues and not project.parent_issues:
                raise Exception(
                    f"Cannot link Project (ID: {project_id}) to Data Source (ID: {data_source_id}) with scope_by_issues=True "
                    f"unless the Project has parent_issues configured"
                )

            # create association
            association = ProjectData(
                project_id=project_id,
                data_source_id=data_source_id
            )
            self.db.add(association)
            self.db.flush()
            
            return {
                "message": f"Successfully linked data source {data_source_id} to project {project_id}",
                "status": "success",
                "project_id": project_id,
                "data_source_id": data_source_id
            }
        except Exception as e:
            logger.exception(f"Failure occurred while linking data source to project: {str(e)}")
            raise e
