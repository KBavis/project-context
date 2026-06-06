from uuid import UUID 
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.data_source import DataSourceService


class DiffService:
    """
    Service responsible for handling all operations related 
    to `Repository Code Changes` for a particular Project 
    """


    def __init__(self, async_db: AsyncSession, data_source_svc: DataSourceService):
        self.async_db: AsyncSession = async_db
        self.data_source_svc = data_source_svc


    def get_total_repository_code_changes(self, project_id: UUID, data_source_id: UUID | None = None) -> list[dict]:
        """
        Get the accumulation of `Repository Code Changes` that we're introduced as a part of this Project
            - shows all changes across each Repository that are a part of this Project if no DataSourceID supplied 
        
        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID | None): The ID of the Data Source to filter the changes by.
        """


    def get_project_repository_changes(self, project_id: UUID, data_source_id: UUID) -> list[dict]:
        """
        Get the accumulation of `Repository Code Changes` that we're introduced as a part of this Project
            - shows all changes across each Repository that are a part of this Project if no DataSourceID supplied 
        
        Args:
            project_id (UUID): The ID of the Project for which to retrieve the changes.
            data_source_id (UUID): The ID of the Data Source to filter the changes by.
        """


    def get_file_diffs(self, project_id: UUID, data_source_id: UUID) -> list[dict]:
        """
        Get the `file_diff` records that are associated with a given Project and DataSource
        """



    def perform_git_operations(self):
        """
        Perform necessary Git operations
        """
    
