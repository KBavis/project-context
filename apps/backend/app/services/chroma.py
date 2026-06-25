from __future__ import annotations
import logging
from typing import Optional
from uuid import UUID
import asyncio

from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, update

from app.models.file import File
from app.core import ChromaClientManager
from app.pydantic import DeleteCollectionDocsRequest, CollectionFilesResponse, MessageResponse
from app.models import ChromaCollection
from app.core import DOCS, CODE, settings
from app.embeddings import EmbeddingManager



logger = logging.getLogger(__name__)


class ChromaService:

    def __init__(
            self, 
            async_db: AsyncSession,
            chroma_manager: ChromaClientManager,
            db: Optional[Session] = None,
    ):
        self.db: Optional[Session] = db
        self.async_db: AsyncSession = async_db
        self.client: ClientAPI = chroma_manager.get_sync_client() # NOTE: LlamaIndex doesn't support working with Async Client when creating VectorStore/Index
        self.chroma_manager = chroma_manager
    

    async def download_and_cache_collection_embeddings(self, data_source_id: UUID):
        """
        Download and cache embeddings for a specified data source.
        
        This preloads embedding models into memory cache to improve 
        response time for subsequent queries on this data source.
        
        Args:
            data_source_id (UUID): The data source ID to cache embeddings for
        """

        try:
            # retreive relevant Chroma Collections corresponding to Data Source
            collection = self.get_collection_by_data_source(data_source_id)
            if not collection:
                logger.warning(f"No ingested data found for Data Source ID: {data_source_id}")
                return
            
            # Pre-load and cache both embedding models in parallel
            logger.info(f"Pre-loading and caching embeddings for data source {data_source_id}...")
            await EmbeddingManager.aget_embedding_model_cached()
            logger.info(f"Successfully cached embeddings for data source {data_source_id}")
            
        except Exception as e:
            logger.error(f"Error caching embeddings for data source {data_source_id}: {str(e)}")
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


    def get_collection_by_data_source(self, data_source_id: UUID) -> ChromaCollection:
        """
        Get the ChromaCollection corresponding to a particular DataSource 

        Args:
            data_source_id (UUID): the data source ID to fetch collections for 
        """
        assert self.db is not None, "Sync DB session is required for this operation"

        stmt = (
            select(ChromaCollection)
            .options(selectinload(ChromaCollection.data_source))
            .where(ChromaCollection.data_source_id == data_source_id)
        )
        
        res = self.db.execute(stmt)
        collection = res.scalars().one_or_none()

        if not collection:
            raise Exception(f"No ChromaCollection found for Data Source ID: {data_source_id}")

        return collection
    
    async def aget_collection_by_data_source(self, data_source_id: UUID) -> ChromaCollection:
        """
        Get ChromaCollection by DataSource 

        Args:
            data_source_id (UUID): the data source ID to fetch collections for 
        """
        stmt = (
            select(ChromaCollection)
            .options(selectinload(ChromaCollection.data_source))
            .where(ChromaCollection.data_source_id == data_source_id)
        )

        result = await self.async_db.execute(stmt)
        collection = result.scalars().one_or_none()
        if not collection:
            raise Exception(f"No ChromaCollection found for Data Source ID: {data_source_id}")
        return collection

    def compute_collection_counts(self, collection: Collection) -> tuple[int, int]:
        """
        Compute the total chunk count and distinct document (file) count for a
        Chroma collection.  This method only talks to the Chroma HTTP client
        (no DB), so it is safe to call from a worker thread.

        Returns:
            (total_chunks, total_documents)
        """
        total_chunks = collection.count()

        file_ids: set[str] = set()
        offset = 0
        while True:
            page = collection.get(
                limit=settings.CHROMA_GET_PAGE_SIZE,
                offset=offset,
                include=["metadatas"],
            )
            ids = page["ids"]
            if not ids:
                break
            for metadata in page["metadatas"] or []:
                file_id = metadata.get("file_id") if metadata else None
                if file_id is not None:
                    file_ids.add(str(file_id))
            offset += len(ids)

        return total_chunks, len(file_ids)

    def update_collection_counts(self, collection: Collection):
        """
        Update the document count and chunk counts for a Chroma Collection.
        Requires a sync DB session (self.db).

        Args:
            collection (Collection): the Chroma Collection to update
        """
        assert self.db is not None, "Sync DB session is required for this operation"

        try:
            total_chunks, total_documents = self.compute_collection_counts(collection)

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

    async def aupdate_collection_counts(self, collection_name: str, total_chunks: int, total_documents: int):
        """
        Async variant of update_collection_counts.
        Persists pre-computed counts via the async DB session. Use this from
        background tasks that don't have a sync DB session.

        Args:
            collection_name (str): Chroma collection name
            total_chunks (int): pre-computed total chunk count
            total_documents (int): pre-computed total document (file) count
        """
        try:
            stmt = (
                update(ChromaCollection)
                .where(ChromaCollection.name == collection_name)
                .values(total_chunks=total_chunks, total_documents=total_documents)
            )
            await self.async_db.execute(stmt)
            await self.async_db.flush()
            logger.debug(f"Successfully updated document and chunk counts for collection={collection_name}")
        except Exception as e:
            logger.error(f"Failure occurred while attempting to async-update counts for collection={collection_name}", exc_info=True)
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
                .join(File, ChromaCollection.data_source_id == File.data_source_id)
                .where(File.id.in_(file_ids))
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
        data_source_id: UUID, 
        data_source_name: str, 
    ):
        """
        Create a Chroma collection for a particular data source.

        The collection is named after the data source's UUID, ensuring a stable,
        unique identifier that does not depend on the human-readable name.

        Args:
            data_source_id (UUID): data source ID — used as the collection name
            data_source_name (str): data source name (used only for log messages)
        """
        assert self.db is not None, "Sync DB session is required for this operation"

        collection_name = str(data_source_id)

        try:
            # create collection in ChromaDB
            _ = self.client.create_collection(name=collection_name)

            # persist relational DB record
            collection = ChromaCollection(
                data_source_id=data_source_id,
                name=collection_name
            )

            self.db.add(collection)
            self.db.flush()

            return collection      

        except Exception as e:
            logger.error(f"Failure occurred while attempting to create ChromaDB collection for DataSource={data_source_name} (id={data_source_id}): {str(e)}")
            raise e


    def delete_collection(self, data_source_id: UUID):
        """
        Delete the Chroma collection associated with a particular data source.

        Args:
            data_source_id (UUID): data source whose collection should be removed
        """

        collection = self.get_collection_by_data_source(data_source_id)
        if not collection:
            logger.warning(f"No ChromaCollection found for DataSource={data_source_id}")
            return

        self._delete_collection(collection.name)
    

    def delete_collection_documents(
            self, 
            delete_collections: DeleteCollectionDocsRequest,
            data_source_id: UUID 
        ):
        """
        Delete documents from the Chroma collection tied to a particular data source.

        Args:
            data_source_id (UUID): data source whose collection documents should be removed
            delete_collections (DeleteCollectionDocsRequest): request body containing doc IDs
        """

        collection = self.get_collection_by_data_source(data_source_id)
        if not collection:
            logger.warning(f"No ChromaCollection found for DataSource={data_source_id}")
            return

        self._delete_documents(collection.name, delete_collections.doc_ids)

        return {"message": f"Successfully deleted documents from collection for DataSource={data_source_id}"}

    def get_all_files(self, data_source_id: UUID) -> CollectionFilesResponse | MessageResponse | dict[str, CollectionFilesResponse] | None:
        """
        Retrieve all files stored within the Chroma collection for a particular data source.

        Args:
            data_source_id (UUID): data source to retrieve collection files for
        """

        collection = self.get_collection_by_data_source(data_source_id)
        if not collection:
            logger.warning(f"No ChromaCollection found for DataSource={data_source_id}")
            return

        return self._get_files_from_collection(collection.name)


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
        

