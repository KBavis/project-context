from .base import Embeddings
class LlamaIndexEmbedding(Embeddings):


    def _get_model_name():
        return "xyz"
    

    def embed(self, text):
        return "todo"