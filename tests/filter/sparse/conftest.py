"""Fixtures for the sparse filter unit tests (qdrant ``:memory:``)."""

from collections.abc import AsyncIterator, Callable
from uuid import uuid4

import pytest

from bitongue.filter.sparse import QdrantPolicy, SparseTextFilter
from bitongue.flow import TextEvent

type MakeSparseFilter = Callable[..., SparseTextFilter[TextEvent]]


@pytest.fixture
def in_memory_policy() -> QdrantPolicy:
    """In-memory connection policy; ``host`` must be ``None`` to satisfy exclusivity."""
    return QdrantPolicy(location=":memory:", host=None)


@pytest.fixture
async def make_sparse_filter(
    in_memory_policy: QdrantPolicy,
) -> AsyncIterator[MakeSparseFilter]:
    """Factory fixture: an in-memory SparseTextFilter per call; teardown
    closes all."""

    created: list[SparseTextFilter[TextEvent]] = []

    def _make(
        documents: list[str],
        *,
        filter_threshold: float = 0.8,
        normalize_scale: float = 5.0,
    ) -> SparseTextFilter[TextEvent]:
        sut: SparseTextFilter[TextEvent] = SparseTextFilter(
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
        await sut.close()
