from sqlalchemy.orm import Session

from app.services import FileService

from hashlib import sha256
import logging

from abc import abstractmethod, ABC
from requests import Response
from uuid import UUID
from enum import Enum

class FileProcessStatus(Enum):

    UNCHANGED = "unchanged"
    UPDATED = "updated"
    CREATED = "created"
    MOVED = "moved"
    COPIED = "copied"


logger = logging.getLogger(__name__)

class DataProvider(ABC):

    def __init__(self, db: Session, url: str = ""):
        self.url = url
        self.request_headers = self._get_request_headers()
        self._file_service = FileService(db)


    def _hash_file_content(self, response: Response):

        sha256_hash = sha256()

        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                sha256_hash.update(chunk)
        
        return sha256_hash.hexdigest()

    

    def process_file(self, response: Response, file_name: str, file_path: str, data_source_id: UUID):
        """
        Process a particular file that was downloaded in order to accurately determine 
        what processing is required for this particular file 

        TODO: Even if a file is unchanged, a new project may have connected with this data source, which may 
        require the "initial ingestion" of this particular file for ONLY that project

        Scenarios:
            1) File existing with the same file_path, file_name, data_source_id, & content hash?
                    - file already exists, skip ingesting 
            2) File exists with the same file_path, but has different content hash 
                    - content changed, re-ingest file content 
            3) File exists with the same content-hash, but different file path 
                    - 3a) No file exists at old path
                            - this is a move 
                    - 3b) File exists at old path
                            - this is a copy 
            4) File is completely new 
        """

        # TODO: Perform actual updates / insertions of these Files 


        # get file hash 
        hashed_content = self._hash_file_content(response)


        # try to get file by full path & data source ID 
        file_by_path = self._file_service.get_file_by_path_and_data_source(file_path, data_source_id)
        if file_by_path:
            
            if file_by_path['hash'] == hashed_content: 
                # if file exists by path and has same hash --> UNCHANGED
                logger.debug(f"Existing file found with no changed at path={file_path} for dataSource={data_source_id}")
                return FileProcessStatus.UNCHANGED
            else:
                # file exists by path, but has different hashed --> CHANGED
                logger.debug(f"Existing file found, but changes have been made, at path={file_path} for dataSource={data_source_id}")
                return FileProcessStatus.UPDATED

        # try to get file by hash
        file_by_hash = self._file_service.get_file_by_hash(hashed_content) 
        if file_by_hash:
            # if file exists by hash, BUT NOT by path, it either was moved or copied

            old_file_path = self._file_service.get_file_by_path_and_data_source(file_by_hash.path, file_by_hash.data_source_id)
            if old_file_path:
                # if old file exists, this was a copy 
                logger.debug(f"Existing file found corresponding to hashed content, file copied from old location")
                return FileProcessStatus.COPIED
            else:
                # old file DNE, this was moved
                logger.debug(f"Existing file found corresponding to hashed content, file moved from old location")
                return FileProcessStatus.MOVED
        

        # new file completely
        logger.debug(f"No existing file found by hash={hashed_content} or path={file_path}, insertion required")
        return FileProcessStatus.CREATED


        

    @abstractmethod
    def ingest_data():
        pass

    @abstractmethod
    def _download_file(url: str, headers: dict = {}):
        pass

    @abstractmethod
    def _validate_url(url: str):
        pass

    @abstractmethod
    def _get_request_headers(self):
        pass
