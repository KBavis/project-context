from sqlalchemy import select, or_, and_, update, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import File, DataSource, FileCollection
from app.pydantic import FileProcesingStatus, File as FilePydantic
from app.core import settings
from app.services.chroma import ChromaService
from app.models.docstore_chunk import DocstoreChunk

from typing import List
from uuid import UUID
import logging
from hashlib import sha256
from io import BytesIO
from httpx import Response



logger = logging.getLogger(__name__)

class FileService:

    def __init__(self, db_session: AsyncSession, chroma_svc: ChromaService):
        self.session = db_session
        self.chroma_svc = chroma_svc


    async def process_file(self, file: FilePydantic, data_source: DataSource, job_pk: UUID) -> FileProcesingStatus:
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


        # Step 2: Insert file into relational DB if needed
        if status == FileProcesingStatus.NEW:
                persisted_file = await self.add_new_file(file=file, data_source=data_source, job_pk=job_pk)

        
        # Step 3. Determine if this File is currently not ingested for a particular Project, even if Project Status indicates we can skip further processing
        if status == FileProcesingStatus.UNCHANGED:
            data_source_project_ids = [source.project_id for source in data_source.project_data]
            unlinked_project_ids = await self.get_project_ids_not_linked_to_file(persisted_file, data_source_project_ids)
            if unlinked_project_ids:
                status = FileProcesingStatus.MISSING_PROJECT_LINKS # update status to indicate further processing required 

                # TODO: We need to account for this, we either a) should specify this only needs to be reingested for a
                #       particular project, or b) we should just reingest for all projects. If we go with 
                #       option b, we need to remove the chunks from Chroma / Docstore (maybe just Chroma)
                


        # Step 4. Mark this File's "last_ingestion_job_id" with relevant ingestion_job that is currently being ran (if needed)
        if status != FileProcesingStatus.NEW:
            await self.update_last_seen_job_pk(job_pk, data_source.id, [persisted_file])
        
        # Step 5. If the file has changed since last ingestion, a) update corresponding file record hash, b) remove "stale" chunks from Chroma , c) remove stale chunks from Docstore
        if status == FileProcesingStatus.CHANGED:
            logger.debug(f"File with path={file.path} has changed since last ingestion, updating file record with relevant hash & remove stale chunks from VectorDB")
            await self.update_existing_file(file=file, data_source=data_source)
            await self.chroma_svc.adelete_nodes_associated_with_files([persisted_file.id])
            await self.remove_chunks_from_docstore(persisted_file.id)

            # TODO: Delete these Nodes from Postgres Doc Store as well 


        # Step 6. Return status back to calling function
        return status

    
    async def remove_chunks_from_docstore(self, file_id: UUID):
        """
        Remove chunks from DocStore that are associated with the specified file_id 

        Args:
            file_id (UUID): the ID of the file to remove chunks for 
        """

        stmt = (
            delete(DocstoreChunk)
            .where(DocstoreChunk.value['__data__']['metadata']['file_id'].astext == str(file_id))
        )

        await self.session.execute(stmt)
        await self.session.flush()

    async def get_file_status(self, hashed_content: str, file_path: str, data_source_id: UUID) -> tuple[FileProcesingStatus, File | None]:
        """
        Utility function to determine what the particular status is of the File we are currently processing 

            FileProcessingStatus.UNCHANGED --> file content & path is the same 
            FileProcessingStatus.CHANGED --> file content has changed, but the path is the same 
            FileProcessingStatus.NEW --> no file existing with the specified path OR the specified content 
        
        Args:
            response (Response): response wrapper around file bytes 
            data_source_id (UUID): the ID of the DataSource this file belongs to 
            file_path (str): the complete file path of this particular file 
        """

        # check if file exists based on path & data source
        status, file = await self.process_file_by_path(hashed_content, file_path, data_source_id)
        if status != FileProcesingStatus.NOT_FOUND:
            return status, file

        # if no file exists based on path or data source, treat this is a new file (even though, it technically could have been moved/copied)
        logger.debug(f"No existing file by path={file_path}, insertion required")
        return FileProcesingStatus.NEW, None


    async def process_file_by_path(self, hashed_content, file_path, data_source_id):
        """
        Check if we have an existing file corresponding to this DataSource with the same path. 
        If so, this means that this file has either been CHANGED or UNCHANGED since we last ingested 

        Args:
            hashed_content (str): the hash corresponding to the file content that we are currently ingesting 
            file_path (str): the current file path assocaited with the file we are ingesting 
            data_source_id (UUID): the data source ID this file corresponds to 
        """

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

        stale_file_ids = await self.get_stale_files(data_source_id, job_pk)
        if not stale_file_ids:
            logger.info(f"No stale files found in DB for DataSource={data_source_id} & IngestionJob={job_pk}")
            return

        # remove stale Nodes from Chroma 
        self.chroma_svc.adelete_nodes_associated_with_files(stale_file_ids)

        # remove stale File's from DB 
        await self.delete_stale_files_from_db(data_source_id, job_pk)



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
        associated_project_ids = [collection.chroma_collection.project_id for collection in file.file_collections]

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

        _ = await session.execute(stmt)
        await session.flush()
    

    async def get_stale_files(self, data_source_id: UUID, ingestion_job_id: UUID) -> list[UUID] | None: 
        """
        Retrieve files from database that we did not see/process during IngestionJob (i.e stale files that we should remove)


        Args:
            data_source_id (UUID): PK of the data source this file corresponds to
            ingestion_job_id (UUID): PK of the current ingestion job
        """
        
        select_stmt = (
            select(File)
            .where(File.data_source_id == data_source_id, File.last_ingestion_job_id != ingestion_job_id)
        )
        res = await self.session.execute(select_stmt)
        stale_files = res.scalars().all() 

        return [file.id for file in stale_files] if stale_files else []

    
    async def delete_stale_files_from_db(self, stale_file_ids: list[UUID]) -> list[UUID] | None:
        """
        Remove Files from DB that we did not see/process during current IngestionJob 

        Args:
            stale_file_ids (list(UUID)): IDs of files that are considered stale 
        """

        # remove sale files if need be 
        stmt = (
            delete(File)
            .where(File.id.in_(stale_file_ids))
        )
        _ = await self.session.execute(stmt)

        logger.debug(f"Successfully removed the following 'stale' File's from the Database:\n\t{stale_file_ids}")
    
    
    async def get_files_by_hash_and_data_source(self, hash: str, data_source_id: UUID) -> List[File]:
        """
        Find File(s) by hashed content & data source 
                NOTE: There could be multiple files with same hash existing at data source 

        Args:
            hash (str): the hash to search for 
            data_source_id (UUID): the data source the file should belong to 
        """

        session = self.session

        stmt = (
            select(File)
            .options(
                selectinload(File.file_collections)
                .selectinload(FileCollection.chroma_collection)
            )
            .where(File.hash == hash, File.data_source_id == data_source_id)
        )

        res = await session.execute(stmt)
        return res.scalars().all()

    
    async def get_file_by_path_and_data_source(self, path: str, data_source_id: UUID) -> File | None: 
        """
        Get File by path and its data source ID

        Args:
            path (str): relevant path of file 
            data_source_id (UUID): ID of the data source this file belongs to 
        """
        
        session = self.session


        stmt = (
            select(File)
            .options(
                selectinload(File.file_collections)
                .selectinload(FileCollection.chroma_collection)
            )
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
        stmt = (
            select(File)
            .where(
                and_(
                    or_(
                        File.hash == file.hash,
                        File.path == file.path
                    ),
                    File.data_source_id == data_source.id
                )
            )
        )
        res = await session.execute(stmt)
        files = res.scalars().all() 

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

        logger.info(f"Successfully updated existing File corresponding to path={file.path}")
        
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
            last_ingestion_job_id=job_pk,
            file_url=file.file_url
        )


        session.add(new_file)
        await session.flush()


        # get all relevant project IDs corresponding to data source
        data_source_project_ids = [source.project_id for source in data_source.project_data]

        # get all ChromaCollections corresponding to file type for each relevant project 
        chroma_collections = [await self.chroma_svc.aget_collection_by_project(project_id) for project_id in data_source_project_ids]

        # create FileCollections records 
        collections = [
            FileCollection(
                file_id=new_file.id, 
                chroma_collection_id=chroma_collection.id
            )
            for chroma_collection in chroma_collections
        ]

        session.add_all(collections)
        await session.flush()

        return new_file



    async def get_file_by_id(self, file_id: UUID) -> File | None:
        """
        Utility function to get a File by its ID

        Args:
            file_id (UUID): the ID of the file to retrieve 
        """

        stmt = select(File).where(File.id == file_id)
        result = await self.session.execute(stmt)
        file = result.scalar_one_or_none()
        return file