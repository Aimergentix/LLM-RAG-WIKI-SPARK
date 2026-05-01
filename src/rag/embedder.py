"""M8 embedder backends — production + deterministic stub.

Per START-PROMPT §5 M8 contract; MASTER §9 (``[ERR_EMBEDDING_MODEL]``).

Pure stdlib at module level. ``sentence_transformers`` is imported
**inside** :class:`SentenceTransformersEmbedder.__init__` only.
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod

ERR_EMBEDDING_MODEL = "[ERR_EMBEDDING_MODEL]"


class EmbedderError(Exception):
    """Raised on embedder load or encode failures.

    Message always begins with ``[ERR_EMBEDDING_MODEL]``.
    """


class EmbedderBackend(ABC):
    """Abstract embedder. Implementations return ``list[list[float]]``."""

    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input string, in input order."""


class SentenceTransformersEmbedder(EmbedderBackend):
    """Production embedder backed by ``sentence-transformers``.

    The constructor performs a lazy import of ``sentence_transformers``
    and instantiates the model. Any failure (missing package, model
    download error, runtime error) is converted into
    :class:`EmbedderError` carrying ``[ERR_EMBEDDING_MODEL]``; partial
    construction is never observable.
    """

    def __init__(self, model_id: str, *, normalize: bool) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        except ImportError as exc:
            raise EmbedderError(
                f"{ERR_EMBEDDING_MODEL} sentence-transformers is required;"
                " install with: pip install sentence-transformers"
            ) from exc
        try:
            model = SentenceTransformer(model_id)
        except Exception as exc:
            raise EmbedderError(
                f"{ERR_EMBEDDING_MODEL} failed to load model '{model_id}': {exc}"
            ) from exc
        # Only assign after the model is fully constructed.
        self._model = model
        self._normalize = bool(normalize)
        self._model_id = model_id
        try:
            self.dim = int(model.get_sentence_embedding_dimension())
        except Exception:
            self.dim = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            arr = self._model.encode(
                texts,
                normalize_embeddings=self._normalize,
                convert_to_numpy=True,
            )
        except Exception as exc:
            raise EmbedderError(
                f"{ERR_EMBEDDING_MODEL} encode failed: {exc}"
            ) from exc
        return [list(map(float, row)) for row in arr]


class DeterministicHashEmbedder(EmbedderBackend):
    """Test-only deterministic embedder.

    Maps each input to a unit-norm vector by feeding ``sha256(text || i)``
    bytes into ``dim`` little-endian uint64 → float in ``[-1, 1]``, then
    L2-normalizing. Identical input → identical vector.
    """

    def __init__(self, dim: int = 16) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = self._hash_to_vector(text)
            out.append(vec)
        return out

    def _hash_to_vector(self, text: str) -> list[float]:
        components: list[float] = []
        i = 0
        while len(components) < self.dim:
            digest = hashlib.sha256(f"{text}\x00{i}".encode("utf-8")).digest()
            # Each digest yields 4 floats (8 bytes each → uint64 → [-1, 1]).
            for off in range(0, 32, 8):
                if len(components) >= self.dim:
                    break
                u = int.from_bytes(digest[off : off + 8], "little", signed=False)
                # Map uint64 to [-1, 1].
                f = (u / (2**64 - 1)) * 2.0 - 1.0
                components.append(f)
            i += 1
        norm = math.sqrt(sum(x * x for x in components))
        if norm == 0.0:
            # Edge case (theoretically impossible): emit a unit basis vector.
            components[0] = 1.0
            norm = 1.0
        return [x / norm for x in components]
