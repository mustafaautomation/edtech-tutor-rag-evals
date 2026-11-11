"""Embedding providers. Offline retrieval uses a fitted hashing embedder."""

import hashlib
import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from harborlight_tutor.textutil import content_tokens


def _features(text: str) -> list[str]:
    tokens = content_tokens(text)
    features = list(tokens)
    features.extend(f"{left}_{right}" for left, right in zip(tokens, tokens[1:], strict=False))
    return features


def _bucket(token: str, dim: int) -> tuple[int, float]:
    digest = hashlib.md5(token.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "little") % dim
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    return index, sign


class HashingEmbedder:
    """Signed feature hashing with corpus IDF. Vectors are L2-normalized."""

    def __init__(self, dim: int = 384) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim
        self._df: dict[str, int] = {}
        self._n = 0
        self._fitted = False

    def fit(self, texts: Sequence[str]) -> "HashingEmbedder":
        df: dict[str, int] = {}
        for text in texts:
            for token in set(_features(text)):
                df[token] = df.get(token, 0) + 1
        self._df = df
        self._n = len(list(texts))
        self._fitted = True
        return self

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("HashingEmbedder.fit must be called before embed")
        matrix = np.zeros((len(list(texts)), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            counts: dict[str, int] = {}
            for token in _features(text):
                counts[token] = counts.get(token, 0) + 1
            for token, count in counts.items():
                index, sign = _bucket(token, self.dim)
                matrix[row, index] += np.float32(sign * self._idf(token) * float(count))
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        matrix /= norms
        return matrix

    def _idf(self, token: str) -> float:
        # Tokens that never appear in the notes cannot be a real match. Giving them
        # a high IDF lets hash collisions outrank the chunk that actually shares words.
        df = self._df.get(token)
        if df is None:
            return 0.0
        return math.log((self._n + 1) / (df + 1)) + 1.0


class OpenAIEmbedder:
    """API embedder. Offline runs do not construct it."""

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model
        self.dim: int | None = None

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        response = self._client.embeddings.create(model=self._model, input=list(texts))
        ordered = sorted(response.data, key=lambda item: int(item.index))
        matrix = np.asarray([list(item.embedding) for item in ordered], dtype=np.float32)
        if matrix.ndim != 2:
            raise RuntimeError("expected a 2-d embedding matrix")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        matrix /= norms
        self.dim = int(matrix.shape[1])
        return matrix
