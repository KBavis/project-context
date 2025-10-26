import chromadb
from app.core import settings


def get_chroma_client():

    try:
        chroma_client = chromadb.HttpClient(host=settings.VECTOR_DB_HOST, port=settings.VECTOR_DB_PORT)
        chroma_client.heartbeat() # check connection 
        return chroma_client

        #TODO: Add logs 
    except Exception as e:
        print("Failed to connect to Chroma DB")
        # raise custom exception 
        raise Exception()

