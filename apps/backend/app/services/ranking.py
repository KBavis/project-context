from sqlalchemy.ext.asyncio import AsyncSession

import logging
from typing import List
from collections import defaultdict

from llama_index.core.schema import NodeWithScore
import asyncio

from app.core.constants import DOCS, CODE
from app.core.config import settings

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

class RankingService:

    def __init__(self, db: AsyncSession):
        self.db = db
    

    async def get_rankings(self, chunks: dict[str, List[NodeWithScore]], query: str, top_k: int = 5) -> List[NodeWithScore]:
        """
        Rank code and documentation chunks based on relevance to query 

        TODO: Use CrossEncoder from LlamaIndex to determine which chunks are most relevant to user posed question 

        Args:
            code_chunks (list): List of code chunks to rank.
            doc_chunks (list): List of documentation chunks to rank.
        """

        logger.debug(f"Ranking top {top_k} chunks for query: {query}")

        # initialize cross encoder model 
        cross_encoder = await asyncio.to_thread(self._get_cross_encoder, settings.CROSS_ENCODING_MODEL)

        # construct pairs for cross encoder scoring
        all_chunks = chunks.get(CODE, []) + chunks.get(DOCS, [])
        pairs = [[query, chunk.get_content()] for chunk in all_chunks]

        # score & sort pairs 
        scores = cross_encoder.predict(pairs)
        scored_nodes = list(zip(all_chunks, scores))
        scored_nodes.sort(key=lambda x: x[1], reverse=True)

        # log re-ranked nodes for debugging
        logger.debug(f"Top ranked chunks after re-ranking: \n")
        for i, chunk in enumerate(scored_nodes):
            logger.debug(f"\tRanked Chunk {i+1}: Score={chunk[1]}, Text={chunk[0].node.get_content()}")

        return [node for node, score in scored_nodes[:top_k]]


    # TODO: We should cache this cross encoder for performance gains 
    def _get_cross_encoder(self, model_name: str) -> CrossEncoder:
        """
        Retrieve CrossEncoder configured in configurations in a seperate worker thread 
        in order to no block main thread with long I/O process

        Args:
            modeL_name (str): the name of the cross encoding model 
        """
        try:

            return CrossEncoder(model_name)
        
        except Exception as e:
            logger.error(f"Failure occurred while downloading the following CrossEncoder: {model_name}", exc_info=True) 
            raise e


