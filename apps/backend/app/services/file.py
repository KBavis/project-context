from sqlalchemy.orm import Session

from uuid import UUID

from app.pydantic import File



class FileService:

    def __init__(self, db: Session):
        self.db = db
    

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
    