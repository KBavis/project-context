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
from app.core import get_async_db_session_context

if TYPE_CHECKING:
    from app.services.diff import DiffService
    from app.services.data_source import DataSourceService
    from app.services.ingestion_job import IngestionJobService

logger = logging.getLogger(__name__)

class ProjectService:
    def __init__(
        self,
        db: Session,
        async_db: AsyncSession,
        diff_svc: DiffService,
        ingestion_job_svc: IngestionJobService,
        data_source_svc: DataSourceService | None = None,
    ):
        self.db = db
        self.async_db = async_db
        self.diff_svc = diff_svc
        self.data_source_svc = data_source_svc
        self.ingestion_job_svc = ingestion_job_svc

    # ─────────────────────────────────────────────
    # Project Readiness
    # ─────────────────────────────────────────────

    async def validate_project_ready(self, project_id: UUID) -> None:
        """
        Gate for conversation message sending. Raises HTTP 412 if:
          - Any ingestible data source (REPOSITORY, DOCUMENTATION) has not completed
            a successful IngestionJob, OR
          - Any issue-scoped Repository data source has not completed a successful
            DiffSyncJob (i.e. ProjectRepoSummary record not yet created).

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

        Returns a dict with:
            is_ready (bool): True only when both ingestion and diff-sync are successful.
            ingestion_status (str): ProcessingStatus value for ingestion.
            sync_status (str): ProcessingStatus value for diff-sync.
            overall_status (str): worst-case aggregate of the two.
            reasons (list[str]): detailed string reasons for any pending or failed data sources.
        """
        ingestion_state, ingestion_reasons = await self.ingestion_job_svc.get_project_ingestion_state(project_id)
        diff_state, diff_reasons = await self.diff_svc.get_project_sync_state(project_id)

        if ProcessingStatus.IN_PROGRESS.value in (ingestion_state, diff_state):
            overall = ProcessingStatus.IN_PROGRESS.value
        elif ProcessingStatus.FAILED.value in (ingestion_state, diff_state):
            overall = ProcessingStatus.FAILED.value
        elif ProcessingStatus.NOT_YET_SYNCED.value in (ingestion_state, diff_state):
            overall = ProcessingStatus.NOT_YET_SYNCED.value
        else:
            overall = ProcessingStatus.SUCCESS.value

        all_reasons = ingestion_reasons + diff_reasons

        return {
            "is_ready": overall == ProcessingStatus.SUCCESS.value,
            "overall_status": overall,
            "ingestion_status": ingestion_state,
            "sync_status": diff_state,
            "reasons": all_reasons
        }


    async def sync_project(self, project_id: UUID) -> None:
        """
        Orchestrator: fan out across all configured data sources for the project,
        run the appropriate pipeline for each, in the correct order.

        Classification:
          - scoped_repos:  REPOSITORY + scope_by_issues → Stage 1 (diff-sync) then Stage 2 (ingestion)
          - direct_ingest: non-scoped REPOSITORY + DOCUMENTATION → Stage 2 only (ingestion)
          - skip:          ISSUE_TRACKER and anything non-ingestible

        Execution:
          Wave 1: asyncio.gather(direct_ingest Stage 2, scoped_repos Stage 1)
          Barrier: wait for Wave 1
          Wave 2: scoped_repos Stage 2 (consumes touched-file allowlist from Stage 1)

        Each per-source pipeline opens its own background-scoped AsyncSession (via
        IngestionJobService._build_ingestion_services) so one source's failure cannot
        poison the rest.  Already-locked resources are caught and skipped.
        """
        # Resolve all data sources linked to this project
        assert self.data_source_svc is not None
        
        async with get_async_db_session_context() as async_session:
            linked_data_sources = await self.data_source_svc.aget_project_data_sources(
                project_id, async_session=async_session
            )

        scoped_repos: list[DataSource] = []
        direct_ingest: list[DataSource] = []

        for ds in linked_data_sources:
            if ds.type == DataSourceType.ISSUE_TRACKER:
                continue  # skip — not ingestible, not diff-syncable
            if ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues:
                scoped_repos.append(ds)
            else:
                # REPOSITORY (non-scoped) and DOCUMENTATION → direct ingestion
                try:
                    IngestibleDataProvider.from_provider(ds)
                    direct_ingest.append(ds)
                except Exception:
                    logger.info(f"[SyncProject] Skipping non-ingestible DataSource={ds.id} ({ds.name})")

        logger.info(
            f"[SyncProject] project_id={project_id}: "
            f"{len(scoped_repos)} scoped repo(s), "
            f"{len(direct_ingest)} direct ingest source(s), "
            f"{len(linked_data_sources) - len(scoped_repos) - len(direct_ingest)} skipped"
        )

        # ── Wave 1: direct ingestion (no Stage 1) + scoped repo Stage 1 ──
        wave1_tasks: list[asyncio.Task] = []

        # Direct ingestion sources → Stage 2 immediately
        for ds in direct_ingest:
            wave1_tasks.append(
                asyncio.create_task(
                    self.ingestion_job_svc.run_ingestion_pipeline(ds),
                    name=f"direct-ingest-{ds.id}",
                )
            )

        # Scoped repos → Stage 1 (diff-sync) only
        for ds in scoped_repos:
            wave1_tasks.append(
                asyncio.create_task(
                    self.diff_svc.run_diff_sync_pipeline(project_id, ds.id),
                    name=f"stage1-diffsync-{ds.id}",
                )
            )

        if wave1_tasks:
            # validate Wave 1 tasks (non-scoped Repository ingestion & Diff Sync Job) completed successfully
            results = await asyncio.gather(*wave1_tasks, return_exceptions=True)
            for task, result in zip(wave1_tasks, results):
                if isinstance(result, Exception):
                    logger.error(
                        f"[SyncProject] Wave 1 task {task.get_name()} failed: {result}",
                        exc_info=result,
                    )

        # ── Barrier: Wave 1 complete ──
        logger.info(f"[SyncProject] project_id={project_id}: Wave 1 complete, starting Wave 2")

        # ── Wave 2: scoped repos Stage 2 (ingestion, consumes touched-file set) ──
        wave2_tasks: list[asyncio.Task] = []
        for ds in scoped_repos:
            wave2_tasks.append(
                asyncio.create_task(
                    self.ingestion_job_svc.run_ingestion_pipeline(ds, project_id=project_id),
                    name=f"stage2-ingest-{ds.id}",
                )
            )

        if wave2_tasks:
            results = await asyncio.gather(*wave2_tasks, return_exceptions=True)
            for task, result in zip(wave2_tasks, results):
                if isinstance(result, Exception):
                    logger.error(
                        f"[SyncProject] Wave 2 task {task.get_name()} failed: {result}",
                        exc_info=result,
                    )

        logger.info(f"[SyncProject] project_id={project_id}: Sync Project complete")

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
            self.db.commit() # NOTE: We commit here so that the downstream DiffSyncJob can successfully leverage the PROJECT_DATA record
            
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

