from sqlalchemy import select, or_, and_, update, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import File, DataSource, FileCollection
from app.pydantic import FileProcesingStatus, File as FilePydantic

from typing import List
from uuid import UUID
import logging
from hashlib import sha256
from io import BytesIO
from httpx import Response



logger = logging.getLogger(__name__)

class FileService:

    def __init__(self, db_session: AsyncSession):
        self.session = db_session


    async def process_file(self, file: File, data_source: DataSource, job_pk: UUID) -> FileProcesingStatus:
        """
        Main function for processing a particular file that we are looking to download from a particular DataSource,
        by determining what status a particular file has & then performing the relevant actions based on that status 
        
        Args:
            file (File): in-memory model of the File we are attemptign to process
            data_source_id (UUID): the ID of the DataSource this file belongs to 
            job_pk (UUID): the ingestion job PK
        """

        # Step 1. Determine if this File has been previously ingested based on file_path, hashed file content, and relevant data source 
        status, persisted_file = await self.get_file_status(file.hash, file.path, data_source.id)


        # Step 2. Perform necessary procesisng based on File Status
        match status:
            case FileProcesingStatus.MOVED:
                """
                TODO: 
                    1. Update existing TextNodes associated with this File (retrieve TextNodes by metadatas hash)
                    2. Update File record in DB with new file path 
                    3. Verify that all projects corresponding to this file have correctly ingested it (FileCollections)
                    4. Indicate to calling function we should continue processing 
                """
            case FileProcesingStatus.CHANGED:
                """
                TODO:
                    1. Delete text nodes assocaited with this File from all relevant Project Collections
                    2. Update File record in DB with relevant hashed content 
                    3. Verify that all projects corresponding to this file have correctly ingested it (FileCollections)
                    4. Indicate to calling function we should continue processing 
                """
            case FileProcesingStatus.NEW | FileProcesingStatus.COPIED:
                
                # insert new file into DB in the case its new or copied
                persisted_file = await self.add_new_file(file=file, data_source=data_source, job_pk=job_pk)

        
        # Step 3. Determine if this File is currently not ingested for a particular Project, even if Project Status indicates we can skip further processing
        if status == FileProcesingStatus.UNCHANGED or status == FileProcesingStatus.MOVED:
            data_source_project_ids = [source.project_id for source in data_source.project_data]
            unlinked_project_ids = await self.get_project_ids_not_linked_to_file(persisted_file, data_source_project_ids)
            if unlinked_project_ids:
                status = FileProcesingStatus.MISSING_PROJECT_LINKS


        # Step 4. Mark this File's "last_ingestion_job_id" with relevant ingestion_job that is currently being ran (if needed)
        if status not in [FileProcesingStatus.NEW, FileProcesingStatus.COPIED]:
            await self.update_last_seen_job_pk(job_pk, data_source.id, [persisted_file])

        # Step 5. Return status back to calling function
        return status


    async def get_file_status(self, hashed_content: str, file_path: str, data_source_id: UUID) -> FileProcesingStatus:
        """
        Utility function to determine what the particular status is of the File we are currently processing 

            FileProcessingStatus.UNCHANGED --> file content & path is the same 
            FileProcessingStatus.CHANGED --> file content has changed, but the path is the same 
            FileProcessingStatus.NEW --> no file existing with the specified path OR the specified content 
            FileProcessingStatus.MOVED --> files content is the same, but now has a different path 
            FileProcessingStatus.COPIED --> file content is the same, but file exists at new path AND the old path 
        
        Args:
            response (Response): response wrapper around file bytes 
            data_source_id (UUID): the ID of the DataSource this file belongs to 
            file_path (str): the complete file path of this particular file 
        """

        # check if file exists based on path 
        status, file = await self.process_file_by_path(hashed_content, file_path, data_source_id)
        if status != FileProcesingStatus.NOT_FOUND:
            return status, file

        # check if file exists based on hash
        status, file = await self.process_file_by_hash(hashed_content)
        if status != FileProcesingStatus.NOT_FOUND:
            return status, file

        # if no file exists based on hash or path, this is a new file
        logger.debug(f"No existing file found by hash={hashed_content} or path={file_path}, insertion required")
        return FileProcesingStatus.NEW, None
    

    async def process_file_by_hash(self, hashed_content):
        """
        Check if we have an existing File in the database corresponding to this particular file hash. If we do, this 
        implies that the file has either been a) COPIED, or b) MOVED

        Args:
            hashed_content (str): the hash corresponding to the file content we are currently ingesting 
        """
        file_by_hash = await self.get_file_by_hash(hashed_content) 
        if file_by_hash:
            # if file exists by hash, BUT NOT by path, it either was moved or copied

            old_file_path = await self.get_file_by_path_and_data_source(file_by_hash.path, file_by_hash.data_source_id)
            if old_file_path:
                # if old file exists, this was a copy 
                logger.debug(f"Existing file found corresponding to hashed content, file copied from old location")
                return FileProcesingStatus.COPIED, file_by_hash
            else:
                # old file DNE, this was moved
                logger.debug(f"Existing file found corresponding to hashed content, file moved from old location")
                return FileProcesingStatus.MOVED, file_by_hash
        
        # indicate to invoking function that we did not find a file based on the provided hash 
        return FileProcesingStatus.NOT_FOUND, None


    async def process_file_by_path(self, hashed_content, file_path, data_source_id):
        """
        Check if we have an existing file corresponding to this DataSource with the same path. 
        If so, this means that this file has either been CHANGED or UNCHANGED since we last ingested 

        Args:
            hashed_content (str): the hash corresponding to the file content that we are currently ingesting 
            file_path (str): the current file path assocaited with the file we are ingesting 
            data_source_id (UUID): the data source ID this file corresponds to 
        """

        logger.debug(f"Testing if we still see failures!")
        
        # try to get file by full path & data source ID 
        file_by_path = await self.get_file_by_path_and_data_source(file_path, data_source_id)
        if file_by_path:
            
            if file_by_path.hash == hashed_content: 
                # if file exists by path and has same hash --> UNCHANGED
                logger.debug(f"Existing file found with no changes at path={file_path} for dataSource={data_source_id}")
                return FileProcesingStatus.UNCHANGED, file_by_path
            else:
                # file exists by path, but has different hashed --> CHANGED
                logger.debug(f"Existing file found, but changes have been made, at path={file_path} for dataSource={data_source_id}")
                return FileProcesingStatus.CHANGED, file_by_path

        # indicate to invoking function that we did not find a file based on the provider path & data source  
        return FileProcesingStatus.NOT_FOUND, None
            

    async def cleanup(self, data_source_id: UUID, job_pk: UUID):
        """
        Functionaltiy to go through and remove any stale files assocaited with a particular DataSource 

        Args:
            data_source_id (UUID): the ID corresponding to the data source these files belong to 
            job_pk (UUID): the ID corresponding to current IngestionJob
        """

        await self.delete_stale_files(data_source_id, job_pk)


    def hash_file_content(self, response: Response, buffer: BytesIO):
        """
        Helper function to hash a file based on strictly its content (i.e no meta data, file name, etc)

        TODO: Storing file bytes in buffer can be expensive if we start dealing with larger files,
        think of a nicer way of handling this 
        
        response (httpx.Response) - response containing relevant file bytes 
        buffer (BytesIO) - buffer to write file to 
        """

        sha256_hash = sha256()

        # process response synchronously (write bytes to buffer and hash)
        try:
            for chunk in response.iter_bytes():
                    if chunk:
                        sha256_hash.update(chunk)
                        buffer.write(chunk)

            return sha256_hash.hexdigest()
        except Exception as e:
            logger.error(f"Failure occurred while attempting to hash file content: {str(e)}")
            raise e



    async def get_project_ids_not_linked_to_file(self, file: File, project_ids: List[UUID]):
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

        session = self.session

    
        file_ids = [file.id for file in files]
        
        stmt = (
            update(File)
            .where(
                File.data_source_id == data_source_id,
                File.id.in_(file_ids)
            )
            .values(last_ingestion_job_id = ingestion_job_id)
        )

        await session.execute(stmt)
        await session.flush()

    
    async def delete_stale_files(self, data_source_id: UUID, ingestion_job_id: UUID):
        """
        Remove Files from DB that we did not see/process during current IngestionJob 

        Args:
            data_source_id (UUID): PK of the data source this file corresponds to
            ingestion_job_id (UUID): PK of the current ingestion job
        """

        session = self.session

        stmt = (
            delete(File)
            .where(File.data_source_id == data_source_id, File.last_ingestion_job_id != ingestion_job_id)
        )

        await session.execute(stmt)

        logger.debug(f"Successfully removed files associated with DataSource={data_source_id}, but were not processed by IngestionJob={ingestion_job_id}")
    
    
    async def get_file_by_hash(self, hash: str) -> File:
        """
        Find File by its hashed content 

        Args:
            hash (str): the hash to search for 
        """

        session = self.session

        stmt = (
            select(File)
            .options(selectinload(File.file_collections)) # eagely load file collections 
            .where(File.hash == hash)
        )

        res = await session.execute(stmt)
        return res.scalars().one_or_none()

    
    async def get_file_by_path_and_data_source(self, path: str, data_source_id: UUID) -> File: 
        """
        Get File by path and its data source ID

        Args:
            path (str): relevant path of file 
            data_source_id (UUID): ID of the data source this file belongs to 
        """
        
        session = self.session


        stmt = (
            select(File)
            .options(selectinload(File.file_collections)) # eagely load file collections 
            .where(File.path == path, File.data_source_id == data_source_id)
        )

        res = await session.execute(stmt)
        return res.scalars().one_or_none()

        

    async def update_existing_file(self, file: FilePydantic, data_source: DataSource):
        """
        Functionality to update an existing File 

        Args:
            file (FilePydantic): file with relevant updates 
        """

        session = self.session


        # attempt to find file by either path OR hash, and the respective DataSource ID
        files = await session.query(File).filter(
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
        
        await session.flush()
            
        
    

    async def add_new_file(self, file: FilePydantic, data_source: DataSource, job_pk: UUID):
        """
        Functionality to insert a new File & corresponding FileCollection record
        """

        session = self.session
        
        # create the File record 
        new_file = File(
            hash=file.hash,
            size=file.size,
            file_extension=file.file_type,
            name=file.file_name,
            path=file.path,
            data_source_id=data_source.id,
            last_ingestion_job_id=job_pk
        )


        session.add(new_file)
        await session.flush()
        await session.commit()

        # create FileCollections records 
        data_source_project_ids = [source.project_id for source in data_source.project_data]

        collections = [
            FileCollection(
                file_id=file.id, 
                project_id=project_id
            )
            for project_id in data_source_project_ids
        ]

        session.add_all(collections)
        await session.flush()

        return new_file

