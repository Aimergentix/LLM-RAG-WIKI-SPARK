"""P5 Cross-Encoder Re-ranker.

Pure stdlib at module level; lazy imports sentence_transformers inside.
"""

from __future__ import annotations
import logging
from typing import List
from rag._query_store import QueryHit

logger = logging.getLogger("rag.reranker")

class CrossEncoderReranker:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self.model_id)
            except ImportError:
                raise RuntimeError("[ERR_EMBEDDING_MODEL] sentence-transformers not installed.")

    def rerank(self, query: str, hits: List[QueryHit], top_k: int) -> List[QueryHit]:
        if not hits:
            return []
        
        self._load()
        
        # Prepare pairs for cross-encoding
        pairs = [[query, hit.document] for hit in hits]
        scores = self._model.predict(pairs)
        
        # Pair scores with hits and sort
        ranked_hits = []
        for i, score in enumerate(scores):
            # We preserve original metadata but update score to the cross-encoder relevance
            ranked_hits.append(QueryHit(
                hits[i].id, 
                float(score), 
                hits[i].metadata, 
                hits[i].document,
                hits[i].embedding
            ))
        
        ranked_hits.sort(key=lambda x: x.score, reverse=True)
        return ranked_hits[:top_k]