from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from pathlib import Path

@dataclass(frozen=True)
class QueryHit:
    id: str
    score: float
    metadata: dict
    document: str
    embedding: list[float] | None = None

@runtime_checkable
class QueryableStore(Protocol):
    def query(self, embedding: list[float], top_k: int) -> list[QueryHit]:
        """Query the store for the top-k nearest neighbors."""
        ...

class ChromaQueryAdapter(QueryableStore):
    def __init__(self, index_dir: Path, collection_name: str, *, distance_metric: str = "cosine"):
        try:
            import chromadb
        except ImportError:
            raise RuntimeError("[ERR_DB] chromadb not installed. Run 'pip install chromadb'.")
        
        self.client = chromadb.PersistentClient(path=str(index_dir))
        self.collection = self.client.get_collection(name=collection_name)
        self.metric = distance_metric

    def query(self, embedding: list[float], top_k: int) -> list[QueryHit]:
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["metadatas", "documents", "distances", "embeddings"]
        )
        hits = []
        if not results["ids"] or not results["ids"][0]:
            return []
            
        for i in range(len(results["ids"][0])):
            # Chroma 'distance' is often 1 - similarity for cosine
            score = 1.0 - results["distances"][0][i] if self.metric == "cosine" else results["distances"][0][i]
            hits.append(QueryHit(
                id=results["ids"][0][i],
                score=score,
                metadata=results["metadatas"][0][i],
                document=results["documents"][0][i],
                embedding=results["embeddings"][0][i] if results.get("embeddings") else None
            ))
        return hits

class InMemoryQueryAdapter(QueryableStore):
    def __init__(self, store, *, distance_metric: str = "cosine"):
        self.store = store  # Expected to be M8 InMemoryVectorStore
        self.metric = distance_metric

    def query(self, embedding: list[float], top_k: int) -> list[QueryHit]:
        records = []
        for rid in self.store.ids():
            rec = self.store.get(rid)
            # Dot product similarity (assumes unit-norm vectors)
            score = sum(a * b for a, b in zip(embedding, rec["embedding"]))
            
            if self.metric == "l2":
                dist = math.sqrt(sum((a - b)**2 for a, b in zip(embedding, rec["embedding"])))
                score = 0.0 - dist # Simplified similarity for test stubs
                
            records.append(QueryHit(
                id=rid,
                score=score,
                metadata=rec["metadata"],
                document=rec["document"],
                embedding=rec["embedding"]
            ))
        
        # Sort by score descending
        records.sort(key=lambda x: x.score, reverse=True)
        return records[:top_k]

class BM25QueryAdapter(QueryableStore):
    """Simple pure-python BM25 implementation for lexical search."""
    def __init__(self, store, k1: float = 1.5, b: float = 0.75):
        self.store = store # InMemoryVectorStore or similar
        self.k1 = k1
        self.b = b
        self._initialize_index()

    def _initialize_index(self):
        self.corpus = []
        self.doc_ids = []
        self.doc_lengths = []
        
        for rid in self.store.ids():
            doc = self.store.get(rid)["document"].lower().split()
            self.corpus.append(doc)
            self.doc_ids.append(rid)
            self.doc_lengths.append(len(doc))
            
        self.avgdl = sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 0
        self.n = len(self.corpus)
        
        # Build term frequencies and document frequencies
        self.df = {}
        self.tfs = []
        for doc in self.corpus:
            tf = {}
            for word in doc:
                tf[word] = tf.get(word, 0) + 1
            self.tfs.append(tf)
            for word in tf:
                self.df[word] = self.df.get(word, 0) + 1

    def query(self, query_text: str, top_k: int) -> list[QueryHit]:
        # Note: In P5 retrieve.py, we pass the text query here instead of an embedding
        # This is a deviation from the Protocol signature supported by the hybrid logic
        query_terms = str(query_text).lower().split()
        scores = []

        for i in range(self.n):
            score = 0.0
            for term in query_terms:
                if term not in self.df:
                    continue
                
                # IDF
                idf = math.log((self.n - self.df[term] + 0.5) / (self.df[term] + 0.5) + 1.0)
                # TF
                tf = self.tfs[i].get(term, 0)
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * self.doc_lengths[i] / self.avgdl)
                score += idf * (numerator / denominator)
            
            if score > 0:
                rec = self.store.get(self.doc_ids[i])
                scores.append(QueryHit(
                    id=self.doc_ids[i],
                    score=score,
                    metadata=rec["metadata"],
                    document=rec["document"],
                    embedding=rec["embedding"]
                ))

        scores.sort(key=lambda x: x.score, reverse=True)
        return scores[:top_k]