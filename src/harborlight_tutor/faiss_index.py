"""FAISS inner-product index over normalized embeddings (cosine similarity)."""

from collections.abc import Sequence

import faiss
import numpy as np

from harborlight_tutor.embeddings import HashingEmbedder
from harborlight_tutor.models import Chunk, RetrievedChunk


class FaissIndex:
    def __init__(self, embedder: HashingEmbedder, chunks: Sequence[Chunk]) -> None:
        if hasattr(faiss, "omp_set_num_threads"):
            faiss.omp_set_num_threads(1)
        self.embedder = embedder
        self.chunks = list(chunks)
        self.embedder.fit([chunk.text for chunk in self.chunks])
        vectors = np.ascontiguousarray(self.embedder.embed([chunk.text for chunk in self.chunks]))
        self._index = faiss.IndexFlatIP(self.embedder.dim)
        if self.chunks:
            self._index.add(vectors)

    def search(self, query: str, k: int) -> list[RetrievedChunk]:
        if not self.chunks or k <= 0:
            return []
        query_vector = np.ascontiguousarray(self.embedder.embed([query]))
        limit = min(k, len(self.chunks))
        scores, ids = self._index.search(query_vector, limit)
        found: list[RetrievedChunk] = []
        for score, idx in zip(scores[0], ids[0], strict=False):
            index = int(idx)
            if index < 0:
                continue
            found.append(RetrievedChunk(chunk=self.chunks[index], score=float(score)))
        found.sort(key=lambda item: (-item.score, item.chunk.id))
        return found
