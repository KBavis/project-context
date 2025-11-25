from sqlalchemy.orm import Session
from sqlalchemy import select

from uuid import UUID

from app.models import File

class FileService:

    def __init__(self, db: Session):
        self.db = db
    
    
    def get_file_by_hash(self, hash: str) -> File:
        """
        Find File by its hashed content 

        Args:
            hash (str): the hash to search for 
        """
        stmt = (
            select(File)
            .where(File.hash == hash)
        )

        return self.db.execute(stmt).scalars().one_or_none()

    
    def get_file_by_path_and_data_source(self, path: str, data_source_id: UUID) -> File: 
        """
        Get File by path and its data source ID

        Args:
            path (str): relevant path of file 
            data_source_id (UUID): ID of the data source this file belongs to 
        """

        stmt = (
            select(File)
            .where(File.path == path, File.data_source_id == data_source_id)
        )

        return self.db.execute(stmt).scalars().one_or_none()

        

    def update_existing_file():
        """
        Functionality to update an existing File 
        """
    

    def add_new_file():
        """
        Functionality to insert a new File & corresponding FileCollection record
        """
    

    def check_if_file_exists(file_id: str, project_id: UUID):
        """
        Check if file exists in relevant collection 
        """


    def generate_file_hash(file: File):
        """
        Generate file hash based on file content
        """
    

    def check_if_file_changed(file: File):
        """
        Check if the file content has changed since last being ingested 
        """
    