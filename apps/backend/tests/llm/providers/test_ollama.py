from app.llm.providers.ollama import OllamaLLM

import pytest
from unittest.mock import patch, MagicMock

class TestOllamaLLM:
    
    @pytest.mark.unit
    def test_get_max_context_length(self):
        with patch('app.llm.providers.ollama.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {
                "model_info": {"general.architecture": "llama"},
                "details": {"quantization_level": "Q4_0"}
            }
            mock_post.return_value = mock_response

            ollama_llm = OllamaLLM(model_name="llama2")
            max_length = ollama_llm.get_max_context_length()

            assert max_length == 2048  # TODO: Change this once implementation is complete

