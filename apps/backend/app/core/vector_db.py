import chromadb
from app.core import settings
from chromadb.api import ClientAPI
from chromadb.api import AsyncClientAPI
from typing import Optional, cast


class ChromaClientManager():

    def __init__(self) -> None:
        self.sync_client: Optional[ClientAPI] = None 
        self.async_client: Optional[AsyncClientAPI] = None
    

    def get_sync_client(self) -> ClientAPI:
        """
        Retrieve sync client for handling Chroma Db collection manipulation
        """
        if not self.sync_client:
            self.setup_sync_client() 
        
        return cast(ClientAPI, self.sync_client) 
    
    async def get_async_client(self) -> AsyncClientAPI:
        """
        Retrieve async client for handling Chroma DB collection manipulation
        """
        if not self.async_client:
            await self.setup_async_client()
        
        return cast(AsyncClientAPI, self.async_client)


    async def setup_async_client(self):
        """
        Setup async client
        """
        try:
            chroma_client = await chromadb.AsyncHttpClient(host=settings.VECTOR_DB_HOST, port=settings.VECTOR_DB_PORT)
            await chroma_client.heartbeat()
            self.async_client = chroma_client
        except Exception as e:
            print(f"Failed to connect to Chroma DB: {e}")
            # TODO: raise custom exception 
            raise e 


    def setup_sync_client(self):
        """
        Setup sync client
        """
        try:
            chroma_client = chromadb.HttpClient(host=settings.VECTOR_DB_HOST, port=settings.VECTOR_DB_PORT)
            chroma_client.heartbeat() # check connection 

            self.sync_client = chroma_client
        except Exception as e:
            print(f"Failed to connect to Chroma DB: {e}")
            # TODO: raise custom exception 
            raise Exception()



