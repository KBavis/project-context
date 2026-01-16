from .base import LLMBase
from llama_index.llms.ollama import Ollama

import requests
import os
import logging
import torch

from app.core import settings

logger = logging.getLogger(__name__)

# mapping of quantization level to corresponding bytes (for model params)
model_params_quantization_bytes = {
    'Q2_K': 0.25,
    'Q3_K_S': 0.375,
    'Q3_K_M': 0.375,
    'Q3_K_L': 0.375,
    'Q4_0': 0.5,
    'Q4_1': 0.5,
    'Q4_K_S': 0.5,
    'Q4_K_M': 0.5,
    'Q5_0': 0.625,
    'Q5_1': 0.625,
    'Q5_K_S': 0.625,
    'Q5_K_M': 0.625,
    'Q6_K': 0.75,
    'Q8_0': 1.0,
    'F16': 2.0,
    'F32': 4.0,
    'MXFP4': 0.5,
    'MXFP6': 0.75,
    'MXFP8': 1.0,
}

# mapping of quantization level to corresponding bytes (for kv cache)
kv_cache_quantization_bytes = {
    "f16": 2,
    "q8_0": 1,
    "q4_0": 0.5
}

class OllamaLLM(LLMBase):

    def __init__(self, model_name: str):
        self.model_name = model_name
    

    def get_max_context_length(self) -> int:
        """
        Return the maximum context length for the Ollama LLM.

        Note: This function will utilize the current systems hardware limitations 
        and the corresponding model configured context lenght to determine 
        what the max input is that we send to a particular model
        """

        machine_total_vram_bytes = self._get_total_vram()

        model_stats = self._get_model_stats()
        logger.debug(f"{self.model_name} Statistics: {model_stats}")

        # calcualte the total size of the model (account for params being quantized)
        bytes_per_parameter = model_params_quantization_bytes[model_stats['quantization_level']]
        model_size_bytes = model_stats["parameter_count"] * bytes_per_parameter

        # remaining vram of current machine, accounting for model size being loaded into memory
        total_vram_bytes_remaining = machine_total_vram_bytes - model_size_bytes
        
        # dedicate 15% reamining VRAM for inference overhead for GPU 
        inference_overhead = 0.15 * total_vram_bytes_remaining
        total_vram_bytes_remaining -= inference_overhead 

        # calculate KV-cache budget (including hardware limiations)
        hardware_max_tokens = total_vram_bytes_remaining / (
            2 * 
            model_stats['num_layers'] * 
            model_stats['hidden_dimensions'] * 
            kv_cache_quantization_bytes[settings.OLLAMA_KV_CACHE_TYPE] # kv cache number of bytes
        )

        # determine max token (min between model maximum and hardware limitation maximum)
        pratical_max_tokens = min(hardware_max_tokens, model_stats['model_context_length'])

        # account for response buffer (output tokens from LLM)
        return round(pratical_max_tokens - settings.LLM_EXPECTED_RESPONSE_SIZE)




    
    
    def tokenize(self, text: str) -> list[str]:
        """
        Tokenize the input text using the Ollama tokenizer and return list of tokens.

        Note: This function should be used by check to see if we are exceeding maximum context 
        length with our current input
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
            response = requests.get(os.getenv("OLLAMA_BASE_URL", settings.OLLAMA_LOCAL_HOST_URL) + "/api/tags")
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
    

    def _get_model_stats(self):
        """
        Retrieve relevant model stats for Ollama model 

        Information retrieved:
            a) model_context_length: the maximum number of tokens LLM can process in single conversation 
            b) parameter count: number of parameters utilized in model
            c) quantization_level: the level this models parameters are quantized (required for determing how many bytes required per parameter)
            d) num_layers: number of layers in the model
            e) hidden_dimensions: size of internal representations at each layer (length of vectors)
        """

        try:
            data = {
                "model": self.model_name
            }

            response = requests.post(os.getenv("OLLAMA_BASE_URL", settings.OLLAMA_LOCAL_HOST_URL) + "/api/show", json=data)
            response.raise_for_status()

            response_data = response.json()
            model_info = response_data["model_info"]

            # extract relevant names that response fields are prefixed with 
            model_architecture_name = model_info["general.architecture"]

            return {
                "model_context_length": model_info[f"{model_architecture_name}.context_length"],
                "parameter_count": model_info[f"general.parameter_count"], 
                "quantization_level": response_data['details']['quantization_level'], 
                "num_layers": model_info[f"{model_architecture_name}.block_count"], 
                "hidden_dimensions": model_info[f'{model_architecture_name}.embedding_length'] 
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Failure occurred while attempting to retrieve model stats", exc_info=True)
            raise e
        except Exception as ex:
            logger.error(f"An unexpected error occurred while retrieving model stats for model: {self.model_name}", exc_info=True)
            raise ex


    def _get_total_vram(self): 
        """
        Get the total VRAM for the current machine's GPU 

        Note: VRAM is essentially the working space for LLMs, everything must fit into
        this space: a) the model weights, b) KV-cache, c) input/output token generation, etc
        """

        # ensure that GPU device is avaialble 
        if torch.cuda.is_available():
            device = torch.device("cuda")
            total_vram_bytes = torch.cuda.get_device_properties(device=device).total_memory
            logger.debug(f"Total VRAM available for Ollama LLM: {total_vram_bytes} Bytes")
            return total_vram_bytes
        else:
            logger.warning("CUDA is not available. Ollama LLM may have limited performance on CPU-only systems.")
            # TODO: Consider setting default max length of CPU based systems or not allowing for usage 