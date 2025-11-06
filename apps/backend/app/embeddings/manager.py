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
    

    def get_embedding_function(self, source_type):

        match self._code_provider:
            
            case 'OpenAI':
                import chromadb.utils.embedding_functions as embedding_functions
                return embedding_functions.OpenAIEmbeddingFunction(
                    api_key = settings.OPEN_AI_API_KEY,
                    model_name = self._code_model if source_type == "CODE" else self._docs_model
                )
            case 'HuggingFace':
                import chromadb.utils.embedding_functions as embedding_functions
                return embedding_functions.HuggingFaceEmbeddingFunction(
                    api_key = settings.HUGGING_FACE_API_KEY,
                    model_name = self._code_model
                )
            case _:
                logging.error(f"The embedidng provider specified, '{self._code_provider}', is not curretly set up for this application")
                raise Exception(f'Invalid embedding provider specified: {self._code_provider}')





        