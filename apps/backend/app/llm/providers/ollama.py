from .base import LLMBase
from llama_index.llms.ollama import Ollama

import requests
import os
import logging

from app.core import settings

logger = logging.getLogger(__name__)

class OllamaLLM(LLMBase):

    def __init__(self, model_name: str):
        self.model_name = model_name
    

    def get_max_context_length(self) -> int:
        """
        Return the maximum context length for the Ollama LLM.
        """

        """
        TODO: 
            1) Hit Ollama http://localhost:11434/api/tags endpoint to get model context length 
                    - Detemrine if any other relevant information is needed 
            2) Calculate available VRAM on host machine 
                    - consider caching somewhere to avoid repeated calls (i.e db)
            3) Restrict max context length accoridngly 
        """

        return 2048  # TODO: Implement me and remove place holder value 
    
    def tokenize(self, text: str) -> list[str]:
        """
        Tokenize the input text using the Ollama tokenizer and return list of tokens.
        """

        # TODO: Implement me
    

    def decompose_query(self, query: str) -> list[str]:
        """
        Decompose a complex query into simpler sub-queries that can be answered individually.
        """
        # TODO: Implement me


    def is_available(self) -> bool:
        """
        Check if a) ollama is installed and b) the specified model is available.
        """

        try:
            # check ollama server is running and get pulled model info
            response = requests.get(os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") + "/api/tags")
            response.raise_for_status()

            # validate model is available 
            response_data = response.json()
            available_models = response_data.get('models', [])
            model_is_pulled = self.model_name in [model['name'] for model in available_models] # TODO: consider removing the EXACT name check and just defaulting to latest version if not found

            if not model_is_pulled:
                logger.error(f"Ollama model '{self.model_name}' is not pulled locally. Please pull the model using the command `ollama pull {self.model_name}`.")
                return False
            
            return True
        except requests.RequestException as e:
            logger.error(f"Failure checking Ollama availability, ensure Ollama is running locally via the command `ollama serve`: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error when checking Ollama availability: {e}")
            return False
        

    def get_llama_idx_instance(self) -> Ollama:
        """
        Get the underlying LlamaIndex Ollama instance.

        TODO: In long run, we should have Ollama running in Docker container via compose.yaml 
        """

        return Ollama(
            model=self.model_name, 
            base_url=os.getenv("OLLAMA_BASE_URL", settings.OLLAMA_LOCAL_HOST_URL)
        ) # TODO: Add additional configuration options as needed and move URL to configs 