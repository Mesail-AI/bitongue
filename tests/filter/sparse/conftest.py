"""Fixtures for the sparse filter unit tests (qdrant ``:memory:``)."""

from collections.abc import AsyncIterator, Callable
from uuid import uuid4

import pytest

from bitongue.filter.sparse import QdrantPolicy, SparseTextualFilter
from bitongue.flow import TextualMessage

type MakeSparseTextualFilter = Callable[..., SparseTextualFilter[TextualMessage]]


@pytest.fixture
def in_memory_policy() -> QdrantPolicy:
    """In-memory connection policy; ``host`` must be ``None`` to satisfy exclusivity."""
    return QdrantPolicy(location=":memory:", host=None)


@pytest.fixture
async def make_sparse_filter(
    in_memory_policy: QdrantPolicy,
) -> AsyncIterator[MakeSparseTextualFilter]:
    """Factory fixture: an in-memory SparseTextualFilter per call; teardown
    closes all."""

    created: list[SparseTextualFilter[TextualMessage]] = []

    def _make(
        documents: list[str],
        *,
        filter_threshold: float = 0.8,
        normalize_scale: float = 5.0,
    ) -> SparseTextualFilter[TextualMessage]:
        sut: SparseTextualFilter[TextualMessage] = SparseTextualFilter(
            f"unit_{uuid4().hex}",
            documents,
            qdrant_policy=in_memory_policy,
            filter_threshold=filter_threshold,
            normalize_scale=normalize_scale,
        )
        created.append(sut)
        return sut

    yield _make

    for sut in created:
        await sut.aclose()
