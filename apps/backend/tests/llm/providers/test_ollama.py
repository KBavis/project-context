from app.llm.providers.ollama import OllamaLLM

import pytest

class TestOllamaLLM:
    
    @pytest.mark.unit
    def test_get_max_context_length(self):

        ollama_llm = OllamaLLM(model_name="llama2")
        max_length = ollama_llm.get_max_context_length()

        assert max_length == 2048 #TODO: Change this 

        

