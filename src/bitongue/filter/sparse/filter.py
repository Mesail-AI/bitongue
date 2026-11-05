"""Qdrant-backed sparse-retrieval dedup filter."""

import math
from collections.abc import Iterable
from typing import Final, cast
from uuid import UUID

import anyio
from fastembed.sparse.sparse_embedding_base import SparseTextEmbeddingBase
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qdrant_models
from uuid_utils.compat import uuid5

from bitongue.filter import Filter, FilterLifecycle
from bitongue.flow import TextEvent

from .bm25 import Bm25, Bm25CN
from .policy import Bm25Policy, QdrantPolicy

__all__ = ("SparseTextFilter",)


POINT_NAMESPACE: Final[UUID] = UUID("8326bf65-7163-4452-a591-c8dc45cd7670")

SPARSE_VECTOR_NAME: Final[str] = "sparse"


class SparseTextFilter[T: TextEvent](Filter, FilterLifecycle):
    """Corpus-similarity dedup filter over qdrant sparse retrieval.

    A corpus of reference documents is seeded into a qdrant collection,
    one point per document, addressed by a UUID5 derived from the
    document text itself — re-seeding the same corpus overwrites
    instead of accumulating. An event is rejected when its sparse
    embedding is similar enough to any corpus point: each hit score is
    squashed through a saturation curve and compared against
    ``filter_threshold``.

    The embedding model and qdrant client form a lazily built runtime:
    constructed on first use (or on :meth:`start`) under a lock, so
    construction never blocks on I/O. Must be started — explicitly or
    implicitly via :meth:`filter` — before it can match events.

    Args:
        collection_name: Target qdrant collection, created when absent.
        documents: Reference corpus seeded into the collection.
        embed_policy: Sparse embedding configuration; defaults to the
            local Chinese Bm25 implementation.
        qdrant_policy: qdrant connection settings; defaults to
            ``localhost:6333``.
        filter_threshold: Rejection threshold on the normalized score,
            strictly within ``(0, 1)``.
        normalize_scale: Saturation scale of the score normalization.

    Raises:
        ValueError: If ``filter_threshold`` is outside ``(0, 1)`` or
            ``normalize_scale`` is not positive and finite.
    """

    def __init__(
        self,
        collection_name: str,
        documents: Iterable[str],
        embed_policy: "Bm25Policy | None" = None,
        qdrant_policy: "QdrantPolicy | None" = None,
        *,
        filter_threshold: float = 0.8,
        normalize_scale: float = 5.0,
    ) -> None:

        if not 0.0 < filter_threshold < 1.0:
            raise ValueError(
                f"Invalid filter threshold: {filter_threshold}",
            )

        if not math.isfinite(normalize_scale) or normalize_scale <= 0:
            raise ValueError(
                f"Invalid normalize scale: {normalize_scale}, must be positive",
            )

        self._documents = list(documents)

        self._collection_name = collection_name
        self._filter_threshold = filter_threshold
        self._normalize_scale = normalize_scale

        self._embed_policy = embed_policy or Bm25Policy(
            model_name="",
            language="chinese",
        )
        self._qdrant_policy = qdrant_policy or QdrantPolicy()

        self._lock = anyio.Lock()
        self._runtime: (
            tuple[
                SparseTextEmbeddingBase,
                AsyncQdrantClient,
            ]
            | None
        ) = None

    @property
    def running(self) -> bool:
        """Whether the runtime is currently built."""

        return self._runtime is not None

    async def start(self) -> None:
        """Build the runtime eagerly: load the model, connect and seed."""

        await self._ensure_runtime()

    async def close(self) -> None:
        """Close the qdrant client and drop the runtime. Idempotent."""

        async with self._lock:
            if self._runtime is not None:
                _, qdrant = self._runtime
                await qdrant.close()

            self._runtime = None

    async def _ensure_runtime(
        self,
    ) -> tuple[SparseTextEmbeddingBase, AsyncQdrantClient]:
        """Return the runtime, building it once under the lock."""

        async with self._lock:
            if self._runtime is None:
                self._runtime = await self._build()

            return self._runtime

    async def _build(
        self,
    ) -> tuple[SparseTextEmbeddingBase, AsyncQdrantClient]:
        """Build the embedding model and the qdrant client, then seed.

        The collection is created with an IDF-modified sparse vector
        when absent. Corpus documents are embedded and upserted under
        their deterministic UUID5 ids; documents that normalize to no
        usable token are skipped.
        """

        policy = self._embed_policy
        embedding: SparseTextEmbeddingBase

        if policy.language == "chinese":
            embedding = Bm25CN(
                k=policy.k,
                b=policy.b,
                avg_len=policy.avg_len,
                language=policy.language,
                token_max_length=policy.token_max_length,
                disable_stemmer=policy.disable_stemmer,
                stemmer=policy.stemmer,
                stopwords=policy.stopwords,
                stopwords_filepath=policy.stopwords_filepath,
            )

        else:
            if not policy.model_name:
                raise ValueError(
                    "Bm25Policy.model_name is required for non-Chinese languages",
                )

            embedding = Bm25(
                model_name=policy.model_name,
                cache_dir=policy.cache_dir,
                k=policy.k,
                b=policy.b,
                avg_len=policy.avg_len,
                language=policy.language,
                token_max_length=policy.token_max_length,
                disable_stemmer=policy.disable_stemmer,
                specific_model_path=policy.specific_model_path,
                stemmer=policy.stemmer,
                stopwords=policy.stopwords,
            )

        qdrant = AsyncQdrantClient(
            **self._qdrant_policy.to_dict(),
        )

        if not await qdrant.collection_exists(self._collection_name):
            await qdrant.create_collection(
                collection_name=self._collection_name,
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: qdrant_models.SparseVectorParams(
                        modifier=qdrant_models.Modifier.IDF,
                    ),
                },
            )

        # Deterministic UUID5 ids make re-seeding overwrite duplicates;
        # documents that normalize to no usable token are skipped.
        await qdrant.upsert(
            collection_name=self._collection_name,
            points=[
                qdrant_models.PointStruct(
                    id=uuid5(namespace=POINT_NAMESPACE, name=document),
                    vector={
                        SPARSE_VECTOR_NAME: qdrant_models.SparseVector(
                            indices=cast("list[int]", corpus_embedding.indices.tolist()),
                            values=cast("list[float]", corpus_embedding.values.tolist()),
                        ),
                    },
                )
                for document, corpus_embedding in zip(
                    self._documents,
                    embedding.embed(documents=self._documents),
                    strict=True,
                )
                if corpus_embedding.indices.size
            ],
        )

        return embedding, qdrant

    def _score_normalize(self, score: float, *, scale: float) -> float:
        """Squash a raw score onto ``(0, 1)`` via a saturation curve.

        Computes ``scale * s / (1 + scale * s)``, which maps unbounded
        retrieval scores into a comparable range so a single fixed
        ``filter_threshold`` works across corpora.
        """

        return scale * score / (1.0 + scale * score)

    async def filter(self, event: "T") -> bool:
        """Reject the event when the corpus holds a close match.

        Queries the collection with the event's sparse embedding and
        rejects on the first hit whose normalized score exceeds the
        threshold. Non-text events, empty text, and queries that
        produce no tokens pass through.

        Args:
            event: The candidate event.

        Returns:
            ``True`` when the corpus matches too closely, ``False`` to
            pass.
        """

        if event.type != "text" or not event.text:
            return False

        embedding, qdrant = await self._ensure_runtime()

        query_embedding = next(
            iter(embedding.query_embed(query=event.text)),
        )

        if query_embedding.indices.size == 0:
            return False

        return any(
            self._score_normalize(point.score, scale=self._normalize_scale)
            > self._filter_threshold
            for point in (
                await qdrant.query_points(
                    collection_name=self._collection_name,
                    using=SPARSE_VECTOR_NAME,
                    query=qdrant_models.SparseVector(
                        indices=cast("list[int]", query_embedding.indices.tolist()),
                        values=cast("list[float]", query_embedding.values.tolist()),
                    ),
                    limit=15,
                )
            ).points
        )
