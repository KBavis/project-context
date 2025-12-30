import logging
from uuid import UUID

from typing import Dict, Optional, List

from sqlalchemy.orm import Session

from app.services.util import get_normalized_project_name
from app.core import ChromaClientManager
from app.pydantic import DeleteCollectionDocsRequest
from app.models import ChromaCollection


logger = logging.getLogger(__name__)


class ChromaService:

    def __init__(
            self, 
            db: Session, 
            chroma_manager: ChromaClientManager, 
            project_svc
    ):
        self.db = db
        self.project_svc = project_svc
        self.client = chroma_manager.get_sync_client()


    def get_total_number_of_collections(self) -> Dict:
        """
        Get the total number of collections in Chroma DB
        """

        return {"total": len(self.client.list_collections())}
    

    def create_collections(
        self, 
        project_id: UUID, 
        project_name: str, 
        docs_embedding_provider: str, 
        docs_embedding_model: str, 
        code_embedding_provider: str, 
        code_embedding_model: str
    ):
        """
        Create collections for a particular project

        Args:
            project_id (UUID): specific project id to create collections for 
            project_name (str): project name 
            docs_embedding_provider (str): embedding provider for documents 
            docs_embedding_model (str): embedding model for documents 
            code_embedding_provider (str): embedding provider for code 
            code_embedding_model (str): embedding model for code 
        """

        PROJECT = get_normalized_project_name(project_name)

        self._verify_project_collections_dne(PROJECT, original_name=project_name)

        try:
            # create collections in ChromaDB
            self.client.create_collection(
                name=f"{PROJECT}_CODE",
            )
            self.client.create_collection(
                name=f"{PROJECT}_DOCS"
            )

            # create relational DB records 
            docs_collection = ChromaCollection(
                project_id=project_id,
                name=f"{PROJECT}_DOCS",
                embedding_provider=docs_embedding_provider,
                embedding_model=docs_embedding_model,
                content_type="DOCS"
            )

            code_collection = ChromaCollection(
                project_id=project_id,
                name=f"{PROJECT}_CODE",
                embedding_provider=code_embedding_provider,
                embedding_model=code_embedding_model,
                content_type="CODE"
            )

            self.db.add(docs_collection)
            self.db.add(code_collection)
            self.db.flush()

            return docs_collection, code_collection          

        except Exception as e:
            logger.error(f"Failure occurred while attempting to create ChromaDB Collections for Project={project_name}: {str(e)}")
            raise e

    
    def _verify_project_collections_dne(
        self, project_name: str, original_name: str
    ) -> None:
        """
        Helper function for verifying relevant collections for specified project do not exist already

        NOTE: ChromaDB will raise exception in the case the collction does not exist by name
        """

        project_dne = True

        # attempt to retrieve docs chroma db collection
        try:
            self.client.get_collection(f"{project_name}_DOCS")
            project_dne = False
        except Exception as e:
            pass

        # attempt to retrieve code chromadb collection
        try:
            self.client.get_collection(f"{project_name}_CODE")
            project_dne = False
        except Exception as e:
            pass

        # error out if either one exists (as this indicates a project with this name is in use)
        if project_dne == False:
            raise Exception(f"Project with the name {original_name} already exists")


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
    

    def delete_collection_documents(
            self, 
            delete_collections: DeleteCollectionDocsRequest,
            project_id: UUID, 
            source_type: Optional[str] = "N/A"
        ):
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
                self._delete_documents(project_name, "DOCS", delete_collections.doc_ids)
            case "CODE":
                return self._delete_documents(project_name, "CODE", delete_collections.doc_ids)
            case "N/A":
                collections = ["CODE", "DOCS"]
                for c in collections:
                    self._delete_documents(project_name, c, delete_collections.doc_ids)
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
                    return {"message": f"No Documents found in CODE or DOCS collection for Project={project_name}"}

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
            logger.debug(f"No Documents currently ingested for Project={project_name} and SourceType={source_type}")
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


