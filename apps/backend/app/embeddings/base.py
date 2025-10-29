from abc import ABC, abstractmethod
from typing import Any

class Embeddings(ABC):


    @abstractmethod
    def _get_model_name():...

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...