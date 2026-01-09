from sqlalchemy.ext.asyncio import AsyncSession

import logging
from typing import List

from collections import defaultdict

from llama_index.core.schema import NodeWithScore

logger = logging.getLogger(__name__)

class RankingService:

    def __init__(self, db: AsyncSession):
        self.db = db

    def get_rankings(self, chunks: defaultdict[str, List[NodeWithScore]], query: str, top_k: int = 5):
        """
        Rank code and documentation chunks based on relevance to query 

        TODO: Use CrossEncoder from LlamaIndex to determine which chunks are most relevant to user posed question 

        Args:
            code_chunks (list): List of code chunks to rank.
            doc_chunks (list): List of documentation chunks to rank.
        """

        logger.debug(f"Ranking top {top_k} chunks for query: {query}")

        return ['Test']  # Placeholder for ranked chunks