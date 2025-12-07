from sqlalchemy import select, or_, and_, update, delete
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from uuid import UUID
import logging

from app.models import File, DataSource, FileCollection
from app.pydantic import File as FilePydantic

from typing import List



logger = logging.getLogger(__name__)

class FileService:

    def __init__(self, db: AsyncSession):
        self.db = db


    def get_project_ids_not_linked_to_file(self, file: File, project_ids: List[UUID]):
        """
        Determine if a particular file has been ingested for all relevant Projects 

        Args:
            file (File): relevant file
            project_ids (List[UUID]): list of project IDs associated with project_ids 
        """

        # get all project IDs this file is currently associated with 
        associated_project_ids = [collection.project_id for collection in file.file_collections]

        # get list of project_ids assocaited with data source, but not file 
        not_linked_project_ids = [
            project_id 
            for project_id in project_ids
            if project_id not in associated_project_ids
        ]

        if not_linked_project_ids:
            logger.debug(f"File with PK={file.id} not linked to Projects={not_linked_project_ids}; ingestion is required")
            return not_linked_project_ids
        else:
            return []

    
    async def update_last_seen_job_pk(self, ingestion_job_id: UUID, data_source_id: UUID, files: List["File"]):
        """
        Update all processed files during IngestionJob "last_seen_by" column to reference current IngestionJob PK 

        Args:
            ingestion_job_id (UUID): PK of the current ingestion job 
            files (List["File"]): list of files we processed 
        """
        
        file_ids = [file.id for file in files]
        
        stmt = (
            update(File)
            .where(
                File.data_source_id == data_source_id,
                File.id.in_(file_ids)
            )
            .values(last_ingestion_job_id = ingestion_job_id)
        )

        await self.db.execute(stmt)
        await self.db.flush()

    
    async def delete_stale_files(self, data_source_id: UUID, ingestion_job_id: UUID):
        """
        Remove Files from DB that we did not see/process during current IngestionJob 

        Args:
            data_source_id (UUID): PK of the data source this file corresponds to
            ingestion_job_id (UUID): PK of the current ingestion job
        """

        stmt = (
            delete(File)
            .where(File.data_source_id == data_source_id, File.last_ingestion_job_id != ingestion_job_id)
        )

        await self.db.execute(stmt)

        logger.debug(f"Successfully removed files associated with DataSource={data_source_id}, but were not processed by IngestionJob={ingestion_job_id}")
    
    
    async def get_file_by_hash(self, hash: str) -> File:
        """
        Find File by its hashed content 

        Args:
            hash (str): the hash to search for 
        """
        stmt = (
            select(File)
            .where(File.hash == hash)
        )

        res = await self.db.execute(stmt)
        return res.scalars().one_or_none()

    
    async def get_file_by_path_and_data_source(self, path: str, data_source_id: UUID) -> File: 
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

        res = await self.db.execute(stmt)
        return res.scalars().one_or_none()

        

    async def update_existing_file(self, file: FilePydantic, data_source: DataSource):
        """
        Functionality to update an existing File 

        Args:
            file (FilePydantic): file with relevant updates 
        """

        # attempt to find file by either path OR hash, and the respective DataSource ID
        files = await self.db.query(File).filter(
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
        
        await self.db.flush()
            
        
    

    async def add_new_file(self, file: FilePydantic, data_source: DataSource, job_pk: UUID):
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
            last_ingestion_job_id=job_pk
        )


        self.db.add(new_file)
        await self.db.flush()

        await self.add_file_to_collections(new_file, data_source)

        return new_file
    

    async def add_file_to_collections(self, file: File, data_source: DataSource):
        """
        Add a newly created file to project collections

        Args:   
            file (File): newly created file 
            data_source (DataSource): data source this file corresponds to 
        """

        data_source_project_ids = [source.project_id for source in data_source.project_data]

        collections = [
            FileCollection(
                file_id=file.id, 
                project_id=project_id
            )
            for project_id in data_source_project_ids
        ]

        self.db.add_all(collections)
        await self.db.flush()
