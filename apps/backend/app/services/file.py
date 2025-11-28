from sqlalchemy import select, or_, and_

from uuid import UUID
import logging

from app.models import File
from app.pydantic import File as FilePydantic

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import DataSource
    from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)

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

        

    def update_existing_file(self, file: FilePydantic, data_source: DataSource):
        """
        Functionality to update an existing File 

        Args:
            file (FilePydantic): file with relevant updates 
        """

        # attempt to find file by either path OR hash, and the respective DataSource ID
        files = self.db.query(File).filter(
            and_(
                or_(
                    File.hash == file.hash,
                    File.path == file.path
                ),
                File.data_source_id == data_source.id
            )
        ).all() 

        if not files:
            logger.debug(f"No files found corresponding to file_hash={file.hash} or file_path={file.path} in DB")
            return 


        if len(files) > 1:
            logger.error(f"Two seperate files found corresponding to file_hash={file.hash} and file_path={file.path} in DB for dataSource={data_source.id}")
            raise Exception(f"Multiple files found by corresponding to hash={file.hash} and/or path={file.path}")
        
        existing_file = files[0]
        existing_file.hash = file.hash
        existing_file.name = file.file_name
        existing_file.size = file.size 
        existing_file.path = file.path
        existing_file.file_extension = file.file_type
        
        self.db.flush()
            
        
    

    def add_new_file(self, file: FilePydantic, data_source: DataSource):
        """
        Functionality to insert a new File & corresponding FileCollection record
        """

        new_file = File(
            hash=file.hash,
            size=file.size,
            file_extension=file.file_type,
            name=file.file_name,
            path=file.path,
            data_source_id=data_source.id,
        )


        self.db.add(new_file)
        self.db.flush()
    

    def add_file_to_collections(self, file: FilePydantic, data_source: DataSource):
        """
        TODO: Complete  me 

        Add a newly created file to project collections
        """