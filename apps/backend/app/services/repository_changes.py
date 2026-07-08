from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_repo_summary import ProjectRepoSummary
from app.models.project_affected_file import ProjectAffectedFile
from app.models.project_file_diff import ProjectFileDiff
from app.models.project_data import ProjectData
from app.models.data_source import DataSource, DataSourceType
from app.models.file import File
from app.pydantic.change_type import ChangeType

logger = logging.getLogger(__name__)


class RepositoryChangesService:
    """
    Standardized data access layer for project repository change tracking.

    Provides query and lifecycle operations for:
      - ProjectRepoSummary (aggregate per-project per-repo)
      - ProjectAffectedFile (per-file change history)
      - ProjectFileDiff (per-PR diff slices)
      - PullRequest (merged PR metadata)
      - GitCommit (commit metadata)

    Consumers: AgentService, Tools, EmbedTaskService, ProjectService,
               JobService, future MCP servers, future API endpoints.
    """

    def __init__(
        self,
        async_db: AsyncSession,
        db: Session | None = None,
    ):
        self.async_db: AsyncSession = async_db
        self.db: Session | None = db

    # ─────────────────────────────────────────────
    # Queries
    # ─────────────────────────────────────────────

    async def get_project_repo_summary(
        self,
        project_id: UUID,
        data_source_id: UUID,
        async_session: AsyncSession | None = None,
    ) -> ProjectRepoSummary | None:
        """
        Get the ProjectRepoSummary for a project + data source pair.

        Args:
            project_id (UUID): The ID of the Project.
            data_source_id (UUID): The ID of the Data Source.
            async_session (AsyncSession?): optional session for background jobs.
        """
        stmt = select(ProjectRepoSummary).where(
            ProjectRepoSummary.project_id == project_id,
            ProjectRepoSummary.data_source_id == data_source_id,
        )
        result = (
            await async_session.execute(stmt)
            if async_session
            else await self.async_db.execute(stmt)
        )
        return result.scalar_one_or_none()

    async def get_file_diffs(
        self, project_id: UUID, data_source_id: UUID
    ) -> list[ProjectAffectedFile]:
        """
        Get the ProjectAffectedFile records for a given Project and DataSource.
        """
        stmt = select(ProjectAffectedFile).where(
            ProjectAffectedFile.project_id == project_id,
            ProjectAffectedFile.data_source_id == data_source_id,
        )
        result = await self.async_db.execute(stmt)
        return list(result.scalars().all())

    async def get_project_touched_file_paths(
        self,
        data_source_id: UUID,
        async_session: AsyncSession | None = None,
    ) -> list[str]:
        """
        Return the list of all unique file paths touched by any project on a specific data source.
        """
        stmt = (
            select(ProjectAffectedFile.file_path)
            .where(
                ProjectAffectedFile.data_source_id == data_source_id,
                ProjectAffectedFile.change_type != ChangeType.DELETED,
            )
            .distinct()
        )
        res = await (async_session or self.async_db).execute(stmt)
        return list(res.scalars().all())

    async def build_scoped_repository_file_id_map(
        self, project_id: UUID
    ) -> dict[str, list[str]]:
        """
        Returns a mapping of data source IDs (as strings) to list of file IDs (as strings).

        This mapping only includes:
          a) Data sources configured for the project (via ProjectData), AND
          b) Data sources that are scoped by issues (scope_by_issues is True and type is REPOSITORY).

        Other data sources do not have a ProjectAffectedFile record, and are excluded
        from this mapping (rather than returning empty lists/mappings).
        """
        stmt = (
            select(DataSource.id, func.array_agg(File.id))
            .join(ProjectData, ProjectData.data_source_id == DataSource.id)
            .outerjoin(
                ProjectAffectedFile,
                (ProjectAffectedFile.data_source_id == DataSource.id)
                & (ProjectAffectedFile.project_id == project_id),
            )
            .outerjoin(
                File,
                (File.path == ProjectAffectedFile.file_path)
                & (File.data_source_id == ProjectAffectedFile.data_source_id),
            )
            .where(
                ProjectData.project_id == project_id,
                DataSource.type == DataSourceType.REPOSITORY,
                DataSource.scope_by_issues.is_(True),
            )
            .group_by(DataSource.id)
        )
        result = await self.async_db.execute(stmt)

        return {
            str(ds_id): (
                [str(fid) for fid in file_ids if fid is not None]
                if file_ids is not None
                else []
            )
            for ds_id, file_ids in result.all()
        }

    async def get_file_diff_string(
        self, project_id: UUID, data_source_id: UUID, file_path: str
    ) -> str:
        """
        Retrieve the chronological list of per-pull-request diff slices for a file
        introduced by the specified Project.

        Each slice is one merged pull request's change to the file, ordered oldest
        first. The latest slice is NOT a netted composite of all changes — callers
        must reason across the slices to understand the file's net change over time.

        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID): The ID of the Data Source to filter the changes by.
            file_path (str): The path to the file for which to retrieve the changes.
        """
        try:
            stmt = (
                select(ProjectAffectedFile)
                .options(
                    selectinload(ProjectAffectedFile.pr_diffs).selectinload(
                        ProjectFileDiff.pull_request
                    )
                )
                .where(
                    ProjectAffectedFile.project_id == project_id,
                    ProjectAffectedFile.data_source_id == data_source_id,
                    ProjectAffectedFile.file_path == file_path,
                )
            )
            result = await self.async_db.execute(stmt)
            file_history = result.scalar_one_or_none()

            if not file_history or not file_history.pr_diffs:
                return (
                    f"No project-scoped changes recorded for the file={file_path} "
                    f"in dataSource={data_source_id} for project_id={project_id}."
                )

            lines: list[str] = [
                f"## Per-PR diff history for `{file_path}` "
                f"(net change_type: {file_history.change_type.value})",
                "",
                "These are chronological per-pull-request diff slices (oldest first). The latest "
                "entry is NOT the composite of all changes — reason across every slice to determine "
                "the file's net state.",
            ]

            for revision in file_history.pr_diffs:
                pr = revision.pull_request
                issue_key = pr.issue_key if pr and pr.issue_key else "no linked issue"
                merged = (
                    pr.merged_at.isoformat() if pr and pr.merged_at else "unknown date"
                )
                pr_number = pr.pr_number if pr else "?"
                lines.append("")
                lines.append(
                    f"### PR #{pr_number} ({issue_key}) merged {merged} — {revision.change_type.value}"
                )
                if revision.diff_truncated:
                    lines.append(
                        "WARNING: This diff slice was truncated due to size limits."
                    )
                lines.append("```diff")
                lines.append(revision.unified_diff or "")
                lines.append("```")

            return "\n".join(lines)

        except Exception as e:
            logger.error(
                f"Error retrieving file diff for file_path={file_path}, data_source_id={data_source_id}",
                exc_info=True,
            )
            return f"Error retrieving file diff: {str(e)}"

    async def get_total_repository_code_changes(
        self, project_id: UUID, data_source_id: UUID | None = None
    ) -> list[dict[str, str]]:
        """
        Get the accumulation of Repository Code Changes introduced as a part of this Project.
        Shows all changes across each Repository that are a part of this Project if no DataSourceID supplied.

        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID | None): The ID of the Data Source to filter the changes by.
        """
        return []

    # ─────────────────────────────────────────────
    # Deletion
    # ─────────────────────────────────────────────

    def delete_project_repo_summary_sync(
        self, project_id: UUID, data_source_id: UUID
    ) -> None:
        """
        Delete the ProjectRepoSummary record using the sync session.
        Used by ProjectService.aunlink_data_source_from_project to ensure
        the deletion happens on the same session as the ProjectData delete.
        """
        assert self.db is not None, "Synchronous DB session is required"

        stmt = select(ProjectRepoSummary).where(
            ProjectRepoSummary.project_id == project_id,
            ProjectRepoSummary.data_source_id == data_source_id,
        )
        repo_summary = self.db.execute(stmt).scalar_one_or_none()
        if repo_summary:
            self.db.delete(repo_summary)
            self.db.flush()

    async def adelete_project_repo_summary(
        self, project_id: UUID, data_source_id: UUID
    ) -> None:
        """
        Delete the ProjectRepoSummary record associated with a given Project and Data Source.
        This cascades down to ProjectAffectedFile and PullRequest records.
        """
        stmt = select(ProjectRepoSummary).where(
            ProjectRepoSummary.project_id == project_id,
            ProjectRepoSummary.data_source_id == data_source_id,
        )
        result = await self.async_db.execute(stmt)
        repo_changes = result.scalar_one_or_none()
        if repo_changes:
            await self.async_db.delete(repo_changes)
            await self.async_db.flush()
