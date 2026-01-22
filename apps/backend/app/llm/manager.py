from app.core.config import settings

import logging

logger = logging.getLogger(__name__)

class LLMManager:


    def __init__(self, provider: str = settings.LL_MODEL_PROVIDER, model_name: str = settings.LL_MODEL):
        self.provider = provider
        self.model_name = model_name
        self.llm = self._initialize_llm()
    

    def _initialize_llm(self):
        """
        Initialize the LLM based on the specified provider and model name.
        """


        match self.provider.lower():
            case "ollama":
                from app.llm.providers.ollama import OllamaLLM
                llm = OllamaLLM(model_name=self.model_name)
                if not llm.is_available(): # TODO: Check if Ollaam from llama index has built in functionality to check this already 
                    raise ValueError(f"Ollama LLM with model '{self.model_name}' is not available. Please ensure Ollama is installed and the model is pulled locally.")
                return llm
            case "openai":
                from app.llm.providers.openai import OpenAIProvider
                llm = OpenAIProvider(model_name=self.model_name)
                return llm
            case _:
                raise ValueError(f"Unsupported LLM provider: {self.provider}")
    


    def get_llm(self):
        """
        Get the currently initalized LLM instance 
        """
        return self.llm
    
    


        
