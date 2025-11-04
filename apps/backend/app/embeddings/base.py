from abc import ABC, abstractmethod

class Embeddings(ABC):


    @abstractmethod
    def _get_model_name():...

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...