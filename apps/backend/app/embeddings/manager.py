from app.core import settings
from app.models import ModelConfigs
from transformers import AutoTokenizer
import logging


class EmbeddingManager:

    def __init__(self, model_configs: ModelConfigs):

        # Coding Embedding Specific Values
        self._code_provider = model_configs.code_embedding_provider
        self._code_model = model_configs.code_embedding_model 

        # Docs Embedding Specific Values
        self._docs_provider = model_configs.docs_embedding_provider
        self._docs_model = model_configs.docs_embedding_model

    def get_embedding_model(self, source_type: str):
        """
        Retrieve the relevant embedding model to be utilize
        based on configurations and the specified source type
        """
        return (
            self.get_docs_embedding_model()
            if source_type == "DOCS"
            else self.get_code_embedding_model()
        )
    
    def get_tokenizer(self, source_type):
        """
        Retrieve configured tokenizer based on configured models and provider 
        """

        return (
            self.get_docs_tokenizer()
            if source_type == "DOCS"
            else self.get_code_tokenizer()
        )
    
    def get_code_tokenizer(self):
        """
        Use Docling to retrieve code tokenizer corresponding to 
        configured model and provider 
        """

        match self._code_provider:

            case "HuggingFace":
                from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
                return HuggingFaceTokenizer(
                    tokenizer=AutoTokenizer.from_pretrained(self._code_model)
                )
            case _:
                logging.error(
                    f"The embedidng provider specified, '{self._code_provider}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {self._code_provider}"
                )


    def get_docs_tokenizer(self):
        """
        Use Docling to retrieve docs tokenizer corresponding to 
        configured model and provider 
        """
        
        match self._docs_provider:

            case "HuggingFace":
                from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
                return HuggingFaceTokenizer(
                    tokenizer=AutoTokenizer.from_pretrained(self._docs_model)
                )
            case _:
                logging.error(
                    f"The embedidng provider specified, '{self._docs_provider}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {self._docs_provider}"
                )


    def get_docs_embedding_model(self):

        match self._docs_provider:

            # Local Embedding Providers
            case "HuggingFace":
                from llama_index.embeddings.huggingface import HuggingFaceEmbedding

                return HuggingFaceEmbedding(model_name=settings.DOCS_EMBEDDING_MODEL)
            case _:
                logging.error(
                    f"The embedidng provider specified, '{self._docs_provider}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {self._docs_provider}"
                )

    def get_code_embedding_model(self):

        match self._code_provider:

            # Local Embedding Providers
            case "HuggingFace":
                from llama_index.embeddings.huggingface import HuggingFaceEmbedding

                return HuggingFaceEmbedding(model_name=settings.CODE_EMBEDDING_MODEL)
            case _:
                logging.error(
                    f"The embedidng provider specified, '{self._code_provider}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {self._code_provider}"
                )
