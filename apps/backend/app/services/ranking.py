from sqlalchemy.ext.asyncio import AsyncSession

import logging

logger = logging.getLogger(__name__)

class RankingService:

    def __init__(self, db: AsyncSession):
        self.db = db

    def get_rankings(self, code_chunks, doc_chunks, query: str, top_k: int = 5):
        """
        Rank code and documentation chunks based on relevance to query 

        TODO: Use CrossEncoder from LlamaIndex to determine which chunks are most relevant to user posed question 

        Args:
            code_chunks (list): List of code chunks to rank.
            doc_chunks (list): List of documentation chunks to rank.
        """

        logger.debug(f"Ranking top {top_k} chunks for {len(code_chunks)} code chunks and {len(doc_chunks)} doc chunks for query: {query}")

        return []  # Placeholder for ranked chunks