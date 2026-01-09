from sqlalchemy.ext.asyncio import AsyncSession

import logging
from typing import List
from collections import defaultdict

from llama_index.core.schema import NodeWithScore

from app.core.config import settings

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

class RankingService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_rankings(self, chunks: defaultdict[str, List[NodeWithScore]], query: str, top_k: int = 5) -> List[NodeWithScore]:
        """
        Rank code and documentation chunks based on relevance to query 

        TODO: Use CrossEncoder from LlamaIndex to determine which chunks are most relevant to user posed question 

        Args:
            code_chunks (list): List of code chunks to rank.
            doc_chunks (list): List of documentation chunks to rank.
        """

        logger.debug(f"Ranking top {top_k} chunks for query: {query}")

        # initialize cross encoder model 
        cross_encoder = CrossEncoder(settings.CROSS_ENCODING_MODEL)

        # construct pairs for cross encoder scoring
        all_chunks = chunks['CODE'] + chunks['DOCS']
        pairs = [[query, chunk.get_content()] for chunk in all_chunks]

        # score & sort pairs 
        scores = cross_encoder.predict(pairs)
        scored_nodes = list(zip(all_chunks, scores))
        scored_nodes.sort(key=lambda x: x[1], reverse=True)

        return [node for node, score in scored_nodes[:top_k]]


        
        


