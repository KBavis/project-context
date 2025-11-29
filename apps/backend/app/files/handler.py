from requests import Response
import logging

from app.models import DataSource
from app.pydantic import File

from enum import Enum 

from hashlib import sha256
from uuid import UUID

from io import BytesIO

logger = logging.getLogger(__name__)

class FileProcesingStatus(Enum):
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    NEW = "new"
    MOVED = "moved"
    COPIED = "copied"
    NOT_FOUND = "not_found"


class FileHandler():
    """
    Utility class to help process files that we have donwloaded from a particular app.data_providers.DataProvider 
    """

    def __init__(self, file_service):
        self._file_service = file_service
           

    def process_file(self, file: File, data_source: DataSource) -> FileProcesingStatus:
        """
        Main function for processing a particular file that we are looking to download from a particular DataSource,
        by determining what status a particular file has & then performing the relevant actions based on that status 

        TODO: When we are processing a particular file, we should account for the fact that we may have some files stored in 
        the Database that are currently "stale". This can best be done by flagging files we either a) see (i.e unchanged, changed, moved, copied), 
        or b) add (i.e no existing file in DB). We can flag these files by having a "last_processed_by" attribute assocaited with a particular File
        in our database. This column can be an FK to the UUID assocaited with the current IngestionJob. That way, once we are done "ingesting" from a 
        DataSource, we can easily check if we just processed this File during last Ingestion Job. If we didn't, then we should remove it as its stale (i.e no
        longer available from DataSource because it was moved/deleted/etc)
        
        Args:
            file_name (str): the name of this particular file being ingested 
            response (Response): response wrapper around file bytes 
            data_source_id (UUID): the ID of the DataSource this file belongs to 
            file_path (str): the complete file path of this particular file 
        """

        # Step 2. Determine if this File has been previously ingested based on file_path, hashed file content, and relevant data source 
        status = self.get_file_status(file.hash, file.path, data_source.id)
        match status:
            case FileProcesingStatus.MOVED:
                """
                TODO: 
                    1. Update existing TextNodes associated with this File (retrieve TextNodes by metadatas hash)
                    2. Update File record in DB with new file path 
                    3. Verify that all projects corresponding to this file have correctly ingested it (FileCollections)
                    4. Indicate to calling function we should continue processing 
                """
            case FileProcesingStatus.COPIED:
                """
                TODO: 
                    1. Insert new File record into our Database 
                    2. Indicate to calling function we should continue processing 
                """
            case FileProcesingStatus.CHANGED:
                """
                TODO:
                    1. Delete text nodes assocaited with this File from all relevant Project Collections
                    2. Update File record in DB with relevant hashed content 
                    3. Verify that all projects corresponding to this file have correctly ingested it (FileCollections)
                    4. Indicate to calling function we should continue processing 
                """
            case FileProcesingStatus.UNCHANGED:
                """
                TODO:
                    1. Verify that all projects corresponding to this file have correctly ingested it (FileCollections)
                    2. Indicate to calling function that we can skip prcoessing 
                """
            case FileProcesingStatus.NEW:
                """
                TODO: 
                    1. Insert new File record into our Database 
                    2. Indicate to calling function we should continue processing 
                    
                    NOTE: New & Copied have same logic, so could be combined into one
                """


        

        # Step 3. Determine if this File is currently not ingested for a particular Project Collection 


        # Step 4. Mark this File's "last_processed_by" with relevant ingestion_job that is currently being ran 

        logger.debug(f"File status for file={file.path}: {status}")
        return status
        



    def get_file_status(self, hashed_content: str, file_path: str, data_source_id: UUID) -> FileProcesingStatus:
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
        status = self.process_file_by_path(hashed_content, file_path, data_source_id)
        if status != FileProcesingStatus.NOT_FOUND:
            return status

        # check if file exists based on hash
        status = self.process_file_by_hash(hashed_content)
        if status != FileProcesingStatus.NOT_FOUND:
            return status

        # if no file exists based on hash or path, this is a new file
        logger.debug(f"No existing file found by hash={hashed_content} or path={file_path}, insertion required")
        return FileProcesingStatus.NEW
    

    def process_file_by_hash(self, hashed_content):
        """
        Check if we have an existing File in the database corresponding to this particular file hash. If we do, this 
        implies that the file has either been a) COPIED, or b) MOVED

        Args:
            hashed_content (str): the hash corresponding to the file content we are currently ingesting 
        """
        file_by_hash = self._file_service.get_file_by_hash(hashed_content) 
        if file_by_hash:
            # if file exists by hash, BUT NOT by path, it either was moved or copied

            old_file_path = self._file_service.get_file_by_path_and_data_source(file_by_hash.path, file_by_hash.data_source_id)
            if old_file_path:
                # if old file exists, this was a copy 
                logger.debug(f"Existing file found corresponding to hashed content, file copied from old location")
                #TODO: Use FileService to create new File 
                return FileProcesingStatus.COPIED
            else:
                # old file DNE, this was moved
                logger.debug(f"Existing file found corresponding to hashed content, file moved from old location")
                return FileProcesingStatus.MOVED
        
        # indicate to invoking function that we did not find a file based on the provided hash 
        return FileProcesingStatus.NOT_FOUND


    def process_file_by_path(self, hashed_content, file_path, data_source_id):
        """
        Check if we have an existing file corresponding to this DataSource with the same path. 
        If so, this means that this file has either been CHANGED or UNCHANGED since we last ingested 

        Args:
            hashed_content (str): the hash corresponding to the file content that we are currently ingesting 
            file_path (str): the current file path assocaited with the file we are ingesting 
            data_source_id (UUID): the data source ID this file corresponds to 
        """
        
        # try to get file by full path & data source ID 
        file_by_path = self._file_service.get_file_by_path_and_data_source(file_path, data_source_id)
        if file_by_path:
            
            if file_by_path['hash'] == hashed_content: 
                # if file exists by path and has same hash --> UNCHANGED
                logger.debug(f"Existing file found with no changed at path={file_path} for dataSource={data_source_id}")
                return FileProcesingStatus.UNCHANGED
            else:
                # file exists by path, but has different hashed --> CHANGED
                logger.debug(f"Existing file found, but changes have been made, at path={file_path} for dataSource={data_source_id}")
                return FileProcesingStatus.CHANGED

        # indicate to invoking function that we did not find a file based on the provider path & data source  
        return FileProcesingStatus.NOT_FOUND
            

    def cleanup(self, data_source_id: UUID):
        """
        Functionaltiy to go through and remove any stale files assocaited with a particular DataSource 

        Args:
            data_source_id (UUID): the ID corresponding to the data source these files belong to 
        """


    def hash_file_content(self, response: Response, buffer: BytesIO):
        """
        Helper function to hash a file based on strictly its content (i.e no meta data, file name, etc)

        TODO: Storing file bytes in buffer can be expensive if we start dealing with larger files,
        think of a nicer way of handling this 
        
        response (Response) - response containing relevant file bytes 
        buffer (BytesIO) - buffer to write file to 
        """

        sha256_hash = sha256()

        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                sha256_hash.update(chunk)
                buffer.write(chunk)
        
        return sha256_hash.hexdigest()
