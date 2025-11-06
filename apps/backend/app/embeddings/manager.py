from app.core import settings
import logging

class EmbeddingManager():

    def __init__(self):

        # Coding Embedding Specific Values 
        self._code_provider = settings.CODE_EMBEDDING_PROVIDER
        self._code_model = settings.CODE_EMBEDDING_MODEL

        # Docs Embedding Specific Values 
        self._docs_provider = settings.DOCS_EMBEDDING_PROVIDER
        self._docs_model = settings.DOCS_EMBEDDING_MODEL
    

    def get_embedding_model(self, source_type: str):
        """
        Retrieve the relevant embedding model to be utilize 
        based on configurations and the specified source type
        """
        return self.get_docs_embedding_model() if source_type == "DOCS" else self.get_code_embedding_model()


    def get_docs_embedding_model(self):

        match self._docs_provider:
            
            # Local Embedding Providers 
            case 'HuggingFace':
                from llama_index.embeddings.huggingface import HuggingFaceEmbedding
                return HuggingFaceEmbedding(model_name=settings.DOCS_EMBEDDING_MODEL)
            case _:
                logging.error(f"The embedidng provider specified, '{self._code_provider}', is not curretly set up for this application")
                raise Exception(f'Invalid embedding provider specified: {self._docs_provider}')
    

    def get_code_embedding_model(self):

        match self._code_provider:
            
            # Local Embedding Providers 
            case 'HuggingFace':
                from llama_index.embeddings.huggingface import HuggingFaceEmbedding
                return HuggingFaceEmbedding(model_name=settings.CODE_EMBEDDING_MODEL)
            case _:
                logging.error(f"The embedidng provider specified, '{self._code_provider}', is not curretly set up for this application")
                raise Exception(f'Invalid embedding provider specified: {self._code_provider}')






        