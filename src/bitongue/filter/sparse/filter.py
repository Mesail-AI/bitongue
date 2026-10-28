import math
from collections.abc import Iterable
from typing import Final, cast
from uuid import UUID

import anyio
from fastembed.sparse.sparse_embedding_base import SparseTextEmbeddingBase
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qdrant_models
from uuid_utils.compat import uuid5

from bitongue.filter.protocols import BaseFilter, FilterLifecycle
from bitongue.flow import TextualMessage

from .bm25 import Bm25, Bm25CN
from .policy import Bm25Policy, QdrantPolicy

__all__ = ("SparseTextualFilter",)


POINT_NAMESPACE: Final[UUID] = UUID("8326bf65-7163-4452-a591-c8dc45cd7670")

SPARSE_VECTOR_NAME: Final[str] = "sparse"


class SparseTextualFilter[T: TextualMessage](BaseFilter, FilterLifecycle):
    """Reject messages that duplicate one of the reference documents.

    The reference corpus is embedded with BM25 into a qdrant sparse
    collection (IDF-modified). Each incoming message is embedded as a
    binary query vector and searched against the corpus; when its best
    matches exceed ``filter_threshold`` similarity the message is
    rejected, and messages unrelated to the corpus are released. A
    message without a text payload is released as well — there is
    nothing to match.

    Reference-document chunking is the caller's responsibility: each
    string becomes exactly one searchable point, addressed by a UUID5
    derived from its own text, so re-seeding the same corpus overwrites
    existing points instead of piling up copies. Corpus documents that
    normalize to no usable token are skipped rather than seeded.

    Initialization is comparatively expensive (embedding construction
    plus a full corpus upsert), so the class implements
    :class:`FilterLifecycle`: hand it to a
    :class:`bitongue.client.Bitongue` client, which starts and closes it
    around the pipeline lifecycle. Standalone use stays possible — the
    first :meth:`filter` call lazily runs the same one-time
    initialization under a lock, paying the cost inside the caller's
    timeout budget.

    Configuration problems raise at construction; start-up problems
    raise from :meth:`start` (or the orchestrating client). The
    :meth:`filter` call itself raises no expected errors — runtime
    lookups degrade to the documented release/reject outcomes.
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
                f"Invalid filter threshold: {filter_threshold}, must be in (0, 1)",
            )

        if not math.isfinite(normalize_scale) or normalize_scale <= 0:
            raise ValueError(
                f"Invalid normalize scale: {normalize_scale}, must be positive",
            )

        self._documents = tuple(documents)

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

        return self._runtime is not None

    async def start(self) -> None:

        await self._ensure_runtime()

    async def aclose(self) -> None:

        async with self._lock:
            if self._runtime is not None:
                _, qdrant = self._runtime
                await qdrant.close()

            self._runtime = None

    async def _ensure_runtime(
        self,
    ) -> tuple[SparseTextEmbeddingBase, AsyncQdrantClient]:

        async with self._lock:
            if self._runtime is None:
                self._runtime = await self._build()

            return self._runtime

    async def _build(
        self,
    ) -> tuple[SparseTextEmbeddingBase, AsyncQdrantClient]:

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

        return scale * score / (1.0 + scale * score)

    async def filter(self, message: "T") -> bool:
        """Reject the message when it duplicates a reference document.

        Returns:
            ``False`` when a corpus point matches the message with
            similarity above ``filter_threshold``; ``True`` when the
            message is unrelated to the corpus or carries no text
            payload.
        """

        if message.type != "text" or not message.text:
            # Not a text message or no text payload. Release it.
            return True

        embedding, qdrant = await self._ensure_runtime()

        query_embedding = next(
            iter(embedding.query_embed(query=message.text)),
        )

        if query_embedding.indices.size == 0:
            return True

        return not any(
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
