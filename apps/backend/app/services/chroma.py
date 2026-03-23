import logging
from uuid import UUID
import asyncio

from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, update

from app.models.file_collection import FileCollection
from app.services.util import get_normalized_project_name
from app.core import ChromaClientManager
from app.pydantic import DeleteCollectionDocsRequest, CollectionFilesResponse, MessageResponse
from app.models import ChromaCollection
from app.core import DOCS, CODE
from app.embeddings import EmbeddingManager



logger = logging.getLogger(__name__)


class ChromaService:

    def __init__(
            self, 
            db: Session, 
            async_db: AsyncSession,
            chroma_manager: ChromaClientManager,
    ):
        self.db: Session = db
        self.async_db: AsyncSession = async_db
        self.client: ClientAPI = chroma_manager.get_sync_client() # NOTE: LlamaIndex doesn't support working with Async Client when creating VectorStore/Index
        self.chroma_manager = chroma_manager
    

    async def download_and_cache_collection_embeddings(self, project_id):
        """
        Download and cache embeddings for a specified project.
        
        This preloads embedding models into memory cache to improve 
        response time for subsequent queries on this project.
        
        Args:
            project_id (UUID): The project ID to cache embeddings for
        """

        try:
            # retreive relevant Chroma Collections corresponding to Project 
            collection = self.get_collection_by_project(project_id)
            if not collection:
                logger.warning(f"No ingested data found for Project ID: {project_id}")
                return
            
            # Create embedding manager with project_id for caching
            embedding_manager = EmbeddingManager(collection, project_id=project_id)

            # Pre-load and cache both embedding models in parallel
            logger.info(f"Pre-loading and caching embeddings for project {project_id}...")
            await asyncio.to_thread(
                embedding_manager.aget_embedding_model_cached
            )
            logger.info(f"Successfully cached embeddings for project {project_id}")
            
        except Exception as e:
            logger.error(f"Error caching embeddings for project {project_id}: {str(e)}")
            # Don't raise - caching is a performance optimization, not critical


    
    def get_real_chroma_collection(self, collection_name: str) -> Collection: 
        """
        Functionality to retreive the "real" ChromaCollection by its name (i.e not our relational DB record)

        Args:
            collection_name (str): the name of the collection
        """    
        try:
            return self.client.get_collection(collection_name)
        except Exception as e: 
            logger.error(f"Failure occurred while attempting to retrieve real Chroma DB collection acocrding to name={collection_name}", exc_info=True)
            raise e


    def get_collection_by_project(self, project_id: UUID) -> ChromaCollection:
        """
        Get the ChromaCollection corresponding to a particular Project 

        Args:
            project_id (UUID): the project ID to fetch collections for 
        """
        stmt = (
            select(ChromaCollection)
            .options(selectinload(ChromaCollection.project))
            .where(ChromaCollection.project_id == project_id)
        )
        
        res = self.db.execute(stmt)
        collection = res.scalars().one_or_none()

        if not collection:
            raise Exception(f"No ChromaCollection found for Project ID: {project_id}")

        return collection
    
    async def aget_collection_by_project(self, project_id: UUID) -> ChromaCollection:
        """
        Get ChromaCollection by Project 

        Args:
            project_id (UUID): the project ID to fetch collections for 
        """
        stmt = (
            select(ChromaCollection)
            .options(selectinload(ChromaCollection.project))
            .where(ChromaCollection.project_id == project_id)
        )

        result = await self.async_db.execute(stmt)
        collection = result.scalars().one_or_none()
        if not collection:
            raise Exception(f"No ChromaCollection found for Project ID: {project_id}")
        return collection

    def update_collection_counts(self, collection: Collection):
        """
        Update the document count and chunk counts for a Chroma Collection

        Args:
            collection (Collection): the Chroma Collection to update
        """
        try:
            # determine Chunk (total embedded pieces of information) count
            total_chunks = collection.count()

            # determine Document (File) count
            docs = collection.get()
            total_documents = len(docs['ids'])

            # update counts in ChromaCollection record
            stmt = (
                update(ChromaCollection)
                .where(ChromaCollection.name == collection.name)
                .values(total_chunks=total_chunks, total_documents=total_documents)
            )
            self.db.execute(stmt)
            self.db.commit()
            logger.debug(f"Successfully updated document and chunk counts for collection={collection.name}")
        except Exception as e:
            logger.error(f"Failure occurred while attempting to update document and chunk counts for collection={collection.name}", exc_info=True)
            raise e
        

    async def adelete_nodes_associated_with_files(self, file_ids: list[UUID]):
        """
        Asynchronously delete nodes associated with a particular file

        Args:
            file_ids (list[UUID]): file IDs that were removed
        """

        # retrieve FileCollection records associated with file
        try:
            # retrieve ChromaCollections assocaited with the "stale" files
            stmt = (
                select(ChromaCollection)
                .join(FileCollection, ChromaCollection.id == FileCollection.chroma_collection_id)
                .where(FileCollection.file_id.in_(file_ids))
            )
            result = await self.async_db.execute(stmt)
            chroma_collections = result.scalars().all()

            # remove Chunks from Chroma that are assocaited with stale file ID
            async_client = await self.chroma_manager.get_async_client()
            for chroma_collection in chroma_collections:
                curr_chroma_collection = await async_client.get_collection(chroma_collection.name)

                for file_id in file_ids:
                    await curr_chroma_collection.delete(where={"file_id": str(file_id)})
            
            logger.debug(f"Successfully removed Chunks from ChromaDB associated with FileIds={file_ids}")

        except Exception as e:
            logger.error(f"Failure occurred while attempting to delete nodes associated with file_ids={file_ids}", exc_info=True)
            raise e


    def get_total_number_of_collections(self) -> dict[str, int]:
        """
        Get the total number of collections in Chroma DB
        """

        return {"total": len(self.client.list_collections())}
    

    def create_collection(
        self, 
        project_id: UUID, 
        project_name: str, 
        embedding_provider: str, 
        embedding_model: str, 
    ):
        """
        Create collection for a particular project

        Args:
            project_id (UUID): specific project id to create collections for 
            project_name (str): project name 
            embedding_provider (str): embedding provider for documents 
            embedding_model (str): embedding model for documents 
        """

        PROJECT = get_normalized_project_name(project_name)

        self._verify_project_collections_dne(PROJECT, original_name=project_name)

        try:
            # create collections in ChromaDB
            _ = self.client.create_collection(name=PROJECT)

            # create relational DB records 
            collection = ChromaCollection(
                project_id=project_id,
                name=PROJECT,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model
            )

            self.db.add(collection)
            self.db.flush()

            return collection      

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
            _ = self.client.get_collection(f"{project_name}")
            project_dne = False
        except Exception as e:
            pass

        # error out if either one exists (as this indicates a project with this name is in use)
        if project_dne == False:
            raise Exception(f"Project with the name {original_name} already exists")


    def delete_collection(self, project_id: UUID):
        """
        Delete collection(s) associated with particular project

        Args:
            project_id (UUID): specific project id to retrieve files for 
        """

        # fetch all ChromaCollections corresponding to ProjectID 
        collection = self.get_collection_by_project(project_id)
        if not collection:
            logger.warning(f"No ChromaCollections found corresponding to ProjectId={project_id}")
            return
    
        project = collection.project
        project_name = get_normalized_project_name(project_name=project.project_name)

        self._delete_collection(project_name)
    

    def delete_collection_documents(
            self, 
            delete_collections: DeleteCollectionDocsRequest,
            project_id: UUID 
        ):
        """
        Delete documents from a particular collection 

        Args:
            project_id (UUID): specific project id to retrieve files for 
            document_ids (List): list of document ids to delete 
        """

        # fetch all ChromaCollections corresponding to ProjectID 
        collection = self.get_collection_by_project(project_id)
        if not collection:
            logger.warning(f"No ChromaCollection found corresponding to ProjectId={project_id}")
            return
    
        project = collection.project
        project_name = get_normalized_project_name(project_name=project.project_name)

        self._delete_documents(project_name, delete_collections.doc_ids)

        return {"message": f"Successfully deleted documents from collections for Project={project_id}"}

    def get_all_files(self, project_id: UUID) -> CollectionFilesResponse | MessageResponse | dict[str, CollectionFilesResponse] | None:
        """
        Retrieve all files stored within collections corresponding to a particular Project

        Args:
            project_id (UUID): specific project id to retrieve files for 
        """
        
        # fetch all ChromaCollections corresponding to ProjectID 
        collection = self.get_collection_by_project(project_id)
        if not collection:
            logger.warning(f"No ChromaCollection found corresponding to ProjectId={project_id}")
            return
    
        project = collection.project
        project_name = get_normalized_project_name(project_name=project.project_name)

        return self._get_files_from_collection(project_name)


    def _delete_documents(self, project_name: str, doc_ids: list[str]):
        """
        Delete Documents from ChromaDB collection

        Args:
            project_name (str): normalized project name corresponding to collection
            doc_ids (list[str]): list of document ids to delete from DB
        """

        collection = self.client.get_collection(f"{project_name}")
        collection.delete(ids=doc_ids)
        logger.info(f"Successfully deleted documents with ids={doc_ids} from collection={project_name}")


        
    
    def _get_files_from_collection(self, project_name: str) -> CollectionFilesResponse | MessageResponse | None:
        """
        Get Documents ffrom ChromaDB collection

        Args:
            project_name (str): normalized project name corresponding to collection
        """

        try:
            collection = self.client.get_collection(f"{project_name}")
        except Exception as e:
            logger.debug(f"Collection {project_name} does not exist: {e}")
            return None

        if collection.count() == 0:
            logger.debug(f"No Documents currently ingested for Project={project_name}")
            return {"message": "No documents found"}

        docs = collection.get()
        document_ids = docs['ids']  
        documents = docs['documents']  
        metadatas = docs['metadatas']  
        embeddings = docs.get('embeddings')  

        logger.info(f"Successfully retrieved {len(document_ids)} documents from collection {project_name}")

        # Explicitly construct the response to match our TypedDict
        response: CollectionFilesResponse = {
            "doc_ids": document_ids,
            "documents": documents,
            "meta_datas": metadatas,
            "embeddings": embeddings
        }
        return response 


    def _delete_collection(self, project_name: str):
        """
        Delete collection from ChromaDB

        Args:
            project_name (str): normalized project name corresponding to collection
        """

        self.client.delete_collection(name=f"{project_name}")
        logger.info(f"Successfully deleted the collection {project_name}")
    

    def delete_collection_by_names(self, collection_names: list[str]):
        """
        Delete collection from ChromaDB by name

        Args:
            collection_names (list[str]): list of collection names to delete 
        """

        for collection_name in collection_names:
            self.client.delete_collection(name=collection_name)
            logger.info(f"Successfully deleted the collection {collection_name}")


    def delete_all_collections(self):
        """
        Delete all collections from ChromaDB
        """

        for collection in self.client.list_collections():
            self.client.delete_collection(name=collection.name)
            logger.info(f"Successfully deleted the collection {collection.name}")
        

