from app.llm.providers.ollama import OllamaLLM

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

class TestOllamaLLM:
    
    @pytest.mark.unit
    async def test_get_max_context_length(self):
        with patch('app.llm.providers.ollama.httpx.AsyncClient') as mock_client_class:
            # Create mock response
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {
                "model_info": {
                    "general.architecture": "llama",
                    "llama.context_length": 2048,
                    "general.parameter_count": 7000000000,
                    "llama.block_count": 32,
                    "llama.embedding_length": 4096
                },
                "details": {"quantization_level": "Q4_0"}
            }
            
            # Create mock client instance with async post method
            mock_client_instance = MagicMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            
            # Make AsyncClient() return async context manager
            mock_client_class.return_value.__aenter__.return_value = mock_client_instance
            mock_client_class.return_value.__aexit__.return_value = None

            ollama_llm = OllamaLLM(model_name="llama2")
            max_length = await ollama_llm.get_max_context_length()

            assert max_length == 1548 
