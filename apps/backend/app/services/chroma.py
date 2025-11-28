import logging
from uuid import UUID

from typing import Dict, Optional, List

from app.core import ChromaClientManager
from app.services import ProjectService
from app.services.util import get_normalized_project_name


logger = logging.getLogger(__name__)


class ChromaService:

    def __init__(self, db, chroma_manager, project_svc):
        self.db = db
        self.project_svc = project_svc
        self.client = chroma_manager.get_sync_client()


    def get_total_number_of_collections(self) -> Dict:
        """
        Get the total number of collections in Chroma DB
        """

        return {"total": len(self.client.list_collections())}


    def delete_collection(self, project_id: UUID, source_type: Optional[str] = "N/A"):
        """
        Delete collection(s) associated with particular project

        Args:
            project_id (UUID): specific project id to retrieve files for 
            source_type (str): optional source type speciifc to get files for 
        """

        # retrieve Project by ID or return message to user indicating not found
        project = self.project_svc.get_project_by_id(project_id)
        if "id" not in project: 
            return project
        
        project_name = get_normalized_project_name(project_name=project["name"])


        match source_type:
            case "DOCS":
                self._delete_collection(project_name, "DOCS")
            case "CODE":
                return self._delete_collection(project_name, "CODE")
            case "N/A":
                collections = ["CODE", "DOCS"]
                for c in collections:
                    self._delete_collection(project_name, c)
            case _:
                raise Exception("Unknown source_type specified")
    

    def delete_collection_documents(self, project_id: UUID, document_ids: List, source_type: Optional[str] = "N/A"):
        """
        Delete documents from a particular collection 

        Args:
            project_id (UUID): specific project id to retrieve files for 
            source_type (str): optional source type speciifc to get files for 
            document_ids (List): list of document ids to delete 
        """

        # retrieve Project by ID or return message to user indicating not found
        project = self.project_svc.get_project_by_id(project_id)
        if "id" not in project: 
            return project
        
        project_name = get_normalized_project_name(project_name=project["name"])

        match source_type:
            case "DOCS":
                self._delete_documents(project_name, "DOCS")
            case "CODE":
                return self._delete_documents(project_name, "CODE")
            case "N/A":
                collections = ["CODE", "DOCS"]
                for c in collections:
                    self._delete_documents(project_name, c)
            case _:
                raise Exception("Unknown source_type specified")


        return {"message": f"Successfully deleted documents from collections for Project={project_id}"}

    def get_all_files(self, project_id: UUID, source_type: Optional[str] = "N/A"):
        """
        Retrieve all files stored within collections corresponding to a particular Project

        Args:
            project_id (UUID): specific project id to retrieve files for 
            source_type (str): optional source type speciifc to get files for 
        """
        
        # retrieve Project by ID or return message to user indicating not found
        project = self.project_svc.get_project_by_id(project_id)
        if "id" not in project: 
            return project
        
        project_name = get_normalized_project_name(project_name=project["name"])
        
        match source_type:
            case "DOCS":
                res = self._get_files_from_collection(project_name, "DOCS")
                return res if res else {"message": f"No Documents found in collection {project_name}_DOCS"}
            case "CODE":
                res = self._get_files_from_collection(project_name, "CODE")
                return res if res else {"message": f"No Documents found in collection {project_name}_CODE"}
            case "N/A":
                collections = ["CODE", "DOCS"]
                all_files = {} 

                for c in collections:
                    files = self._get_files_from_collection(project_name, c)
                    if files:
                        all_files[c] = files
                    
                if not all_files:
                    return {f"message": "No Documents found in CODE or DOCS collection for Project={project_name}"}

            case _:
                raise Exception("Unknown source_type specified")
        

        return all_files
            
    

    def _delete_documents(self, project_name: str, source_type: str, doc_ids: List):
        """
        Delete Documents from ChromaDB collection

        Args:
            project_name (str): normalized project name corresponding to collection
            source_type (str): relevant source type to delete documents for 
            doc_ids (list): list of document ids to delete from DB
        """

        collection = self.client.get_collection(f"{project_name}_{source_type}")
        collection.delete(ids=doc_ids)
        logger.info(f"Successfully deleted documents with ids={doc_ids} from collection={project_name}_{source_type}")


        
    
    def _get_files_from_collection(self, project_name: str, source_type: str):
        """
        Get Documents ffrom ChromaDB collection

        Args:
            project_name (str): normalized project name corresponding to collection
            source_type (str): relevant source type to get documents for 
        """

        try:
            collection = self.client.get_collection(f"{project_name}_{source_type}")
        except Exception as e:
            logger.debug(f"Collection {project_name}_{source_type} does not exist: {e}")
            return None

        if collection.count() == 0:
            logger.debug(f"No Documents currently ingested for Project={project_name}")
            return {"message": "No documents found"}

        docs = collection.get()
        document_ids = docs['ids']  
        documents = docs['documents']  
        metadatas = docs['metadatas']  
        embeddings = docs.get('embeddings')  

        logger.info(f"Successfully retrieved {len(document_ids)} documents from collection {project_name}_{source_type}")

        return {
            "doc_ids": document_ids,
            "documents": documents,
            "meta_datas": metadatas,
            "embeddings": embeddings
        } 


    def _delete_collection(self, project_name: str, source_type: str):
        """
        Delete collection from ChromaDB

        Args:
            project_name (str): normalized project name corresponding to collection
            source_type (str): relevant source type corresponding to collection to remove 
        """

        self.client.delete_collection(name=f"{project_name}_{source_type}")
        logger.info(f"Successfully deleted the collection {project_name}_{source_type}")


