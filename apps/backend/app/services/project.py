from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.pydantic import ProjectRequest
from app.pydantic.status import ProcessingStatus
from app.models import Project, ProjectData, DataSource 
from app.models.data_source import DataSourceType
from app.data_providers.ingestible.base import IngestibleDataProvider

from uuid import UUID

if TYPE_CHECKING:
    from app.services.diff_task import DiffTaskService
    from app.services.data_source import DataSourceService
    from app.services.job import JobService

logger = logging.getLogger(__name__)

class ProjectService:
    def __init__(
        self,
        db: Session,
        async_db: AsyncSession,
        diff_svc: DiffTaskService,
        job_svc: JobService,
        data_source_svc: DataSourceService | None = None,
    ):
        self.db = db
        self.async_db = async_db
        self.diff_svc = diff_svc
        self.data_source_svc = data_source_svc
        self.job_svc = job_svc

    # ─────────────────────────────────────────────
    # Project Readiness
    # ─────────────────────────────────────────────

    async def validate_project_ready(self, project_id: UUID) -> None:
        """
        Gate for conversation message sending. Raises HTTP 412 if:
          - Any ingestible data source (REPOSITORY, DOCUMENTATION) has not completed
            a successful EmbedTask, OR
          - Any issue-scoped Repository data source has not completed a successful
            DiffTask (i.e. ProjectRepoSummary record not yet created).

        Fetchable-only sources (ISSUE_TRACKER) are ignored for both checks.
        """
        readiness = await self.get_project_readiness_state(project_id)

        if readiness["is_ready"]:
            return

        reasons = readiness.get("reasons", [])
        reasons_str = " ".join(reasons) if reasons else "Project data sources are not fully synced."

        if readiness["overall_status"] == ProcessingStatus.IN_PROGRESS.value:
            raise HTTPException(
                status_code=412,
                detail=f"Project synchronization is in progress. {reasons_str}"
            )
        if readiness["overall_status"] == ProcessingStatus.NOT_YET_SYNCED.value:
            raise HTTPException(
                status_code=412,
                detail=f"Project has not yet been synced. {reasons_str}"
            )
        raise HTTPException(
            status_code=412,
            detail=f"Project synchronization failed or is incomplete. {reasons_str}"
        )

    async def get_project_readiness_state(self, project_id: UUID) -> dict:
        """
        Return a combined readiness snapshot used by the /sync-status endpoint.
        """
        overall_state, reasons = await self.job_svc.get_project_sync_state(project_id)

        return {
            "is_ready": overall_state == ProcessingStatus.SUCCESS.value,
            "overall_status": overall_state,
            "reasons": reasons
        }




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

            return {
                "id": project.id,
                "name": project.project_name,
                "description": project.description
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

            # If the DataSource is already linked to other projects, enforce repository scoping rules
            stmt_existing_links = select(ProjectData).where(ProjectData.data_source_id == data_source_id)
            existing_links = self.db.execute(stmt_existing_links).scalars().all()
            other_linked_projects = [l for l in existing_links if l.project_id != project_id]
            if other_linked_projects:
                # Data source already associated with at least one other project
                if data_source.type == DataSourceType.REPOSITORY and not data_source.scope_by_issues:
                    # Disallow linking a repository that is not scoped by issues to multiple projects
                    raise ValueError(
                        "Cannot link this Repository Data Source to multiple projects unless it is configured with "
                        "scope_by_issues=True. To fix: set `scope_by_issues` to true on the Data Source and ensure "
                        "the target Project has parent_issues configured (issue numbers), or unlink the Data Source from "
                        "other projects before linking."
                    )

            # validate that if data source has scope_by_issues=True, project must have parent_issues
            if data_source.scope_by_issues and not project.parent_issues:
                raise ValueError(
                    f"Cannot link Project (ID: {project_id}) to Data Source (ID: {data_source_id}) with scope_by_issues=True "
                    f"unless the Project has parent_issues configured"
                )

            # create association
            association = ProjectData(
                project_id=project_id,
                data_source_id=data_source_id
            )
            self.db.add(association)
            self.db.commit() # NOTE: We commit here so that the downstream DiffTask can successfully leverage the PROJECT_DATA record
            
            return {
                "message": f"Successfully linked data source {data_source_id} to project {project_id}",
                "status": "success",
                "project_id": project_id,
                "data_source_id": data_source_id
            }
        except Exception as e:
            logger.exception(f"Failure occurred while linking data source to project: {str(e)}")
            raise e

    async def aunlink_data_source_from_project(self, project_id: UUID, data_source_id: UUID) -> dict:
        """
        Unlink a DataSource from a Project.
        Includes validations to prevent removing Issue Tracker if issue-scoped repos rely on it.
        Also explicitly handles removal of associated project repository changes.
        """
        try:
            # check if relationship exists
            stmt = select(ProjectData).where(
                ProjectData.project_id == project_id,
                ProjectData.data_source_id == data_source_id
            )
            association = self.db.execute(stmt).scalar_one_or_none()
            
            if not association:
                return {"message": "Data source is not linked to this project", "status": "not_linked"}

            # retrieve the data source
            ds_stmt = select(DataSource).where(DataSource.id == data_source_id)
            data_source = self.db.execute(ds_stmt).scalar_one_or_none()
            if not data_source:
                raise Exception(f"Data Source with ID {data_source_id} not found")

            # Validation: If it's an ISSUE_TRACKER, check if any remaining linked repositories rely on it
            if data_source.type == DataSourceType.ISSUE_TRACKER:
                stmt_project_ds = select(ProjectData).where(ProjectData.project_id == project_id)
                linked_ds = self.db.execute(stmt_project_ds).scalars().all()
                for lds in linked_ds:
                    if lds.data_source_id == data_source_id:
                        continue
                    ds_check = self.db.execute(select(DataSource).where(DataSource.id == lds.data_source_id)).scalar_one_or_none()
                    if ds_check and ds_check.type == DataSourceType.REPOSITORY and ds_check.scope_by_issues:
                        raise ValueError(
                            "Cannot unlink Issue Tracker because the project has one or more issue-scoped repositories linked. "
                            "Unlink those repositories first."
                        )

            # Delete the ProjectRepoSummary explicitly to cascade its children using diff_svc
            await self.diff_svc.adelete_project_repo_summary(project_id, data_source_id)

            # Finally, delete the association
            self.db.delete(association)
            self.db.flush()
            
            return {
                "message": f"Successfully unlinked data source {data_source_id} from project {project_id}",
                "status": "success",
                "project_id": project_id,
                "data_source_id": data_source_id
            }
        except Exception as e:
            logger.exception(f"Failure occurred while unlinking data source from project: {str(e)}")
            raise e

