"""SparseTextFilter integration tests against a real qdrant server.

Connection: ``BITONGUE_TEST_QDRANT_URL`` first, falling back to
``BITONGUE_TEST_QDRANT_HOST``/``BITONGUE_TEST_QDRANT_PORT`` (default
``localhost:6333``). An unreachable server skips the suite instead of
failing it.
"""

import os
from collections.abc import AsyncIterator, Callable
from uuid import uuid4

import anyio
import pytest
from qdrant_client import AsyncQdrantClient
from tests.conftest import MakeTextEvent, TextualEvent

from bitongue.client import Bitongue, BitongueConfig
from bitongue.filter.sparse import QdrantPolicy, SparseTextFilter
from bitongue.flow import TextEvent
from test_integration.conftest import CollectEvents

pytestmark = pytest.mark.integration

_PROBED: dict[str, bool] = {"done": False, "ok": False}


def _policy_from_env() -> QdrantPolicy:
    url = os.environ.get("BITONGUE_TEST_QDRANT_URL")
    if url:
        return QdrantPolicy(url=url)
    return QdrantPolicy(
        host=os.environ.get("BITONGUE_TEST_QDRANT_HOST", "localhost"),
        port=int(os.environ.get("BITONGUE_TEST_QDRANT_PORT", "6333")),
    )


async def _probe(policy: QdrantPolicy) -> bool:
    """Short-timeout liveness probe: listing collections counts as reachable."""
    try:
        client = AsyncQdrantClient(**{**policy.to_dict(), "timeout": 2})
    except Exception:
        return False

    try:
        with anyio.fail_after(5):
            await client.get_collections()
    except Exception:
        return False
    finally:
        await client.close()

    return True


type MakeIntegrationFilter = Callable[..., SparseTextFilter[TextEvent]]


@pytest.fixture
async def real_qdrant_policy() -> QdrantPolicy:
    """Probe once per session; skip the whole tree when unreachable."""
    if not _PROBED["done"]:
        _PROBED["ok"] = await _probe(_policy_from_env())
        _PROBED["done"] = True
    if not _PROBED["ok"]:
        pytest.skip("qdrant unreachable (BITONGUE_TEST_QDRANT_URL/HOST/PORT)")
    return _policy_from_env()


@pytest.fixture
async def make_integration_filter(
    real_qdrant_policy: QdrantPolicy,
) -> AsyncIterator[MakeIntegrationFilter]:
    """Factory fixture: a real-server SparseTextFilter; teardown closes
    it and deletes the collection."""

    raw = AsyncQdrantClient(**{**real_qdrant_policy.to_dict(), "timeout": 30})
    created: list[tuple[SparseTextFilter[TextEvent], str]] = []

    def _make(
        documents: list[str],
        *,
        filter_threshold: float = 0.8,
        normalize_scale: float = 5.0,
        collection_name: str | None = None,
    ) -> SparseTextFilter[TextEvent]:
        name = collection_name or f"it_{uuid4().hex}"
        sut: SparseTextFilter[TextEvent] = SparseTextFilter(
            name,
            documents,
            qdrant_policy=real_qdrant_policy,
            filter_threshold=filter_threshold,
            normalize_scale=normalize_scale,
        )
        created.append((sut, name))
        return sut

    yield _make

    for sut, _name in created:
        await sut.close()
    for _sut, name in created:
        try:
            await raw.delete_collection(name)
        except Exception:
            pass
    await raw.close()


class TestDuplicateInterception:
    """Duplicate interception against the real server."""

    async def test_variant_rejected_and_unrelated_released(
        self,
        make_integration_filter: MakeIntegrationFilter,
        make_text_event: MakeTextEvent,
    ) -> None:
        sut = make_integration_filter(
            ["已知违规文案示例 alpha", "another known reference beta"],
        )
        await sut.start()
        assert await sut.filter(make_text_event("已知违规文案示例 alpha 修改版")) is True
        assert (
            await sut.filter(make_text_event("completely unrelated new content")) is False
        )

    async def test_reseed_keeps_verdicts_consistent(
        self,
        make_integration_filter: MakeIntegrationFilter,
        make_text_event: MakeTextEvent,
    ) -> None:
        # Re-seeding the same collection name: uuid5 dedup upsert, and the
        # verdicts stay consistent across instances.
        name = f"it_{uuid4().hex}"
        first = make_integration_filter(["持久化判重语料"], collection_name=name)
        await first.start()
        await first.close()

        second = make_integration_filter(["持久化判重语料"], collection_name=name)
        await second.start()
        assert await second.filter(make_text_event("持久化判重语料 变体")) is True
        assert await second.filter(make_text_event("无关新内容")) is False


class TestClientAssembly:
    """Real pipeline assembled through Bitongue: lifecycle and interception
    working together."""

    async def test_lifecycle_end_to_end(
        self,
        make_integration_filter: MakeIntegrationFilter,
        collect_events: CollectEvents,
    ) -> None:
        sut = make_integration_filter(["端到端违规文案"])
        config = BitongueConfig(
            buffer_size=8,
            event_timeout=30,
        )
        client = Bitongue(config, sut)
        await client.start()  # Init cost lands on client.start, not message 1.
        assert sut.running is True

        # The rejected variant must share tokens with the corpus; the
        # released message must share zero tokens with it: even a single
        # overlapping token can score above the default threshold.
        rejected = TextualEvent(id=uuid4(), text="端到端违规文案 变体")
        released = TextualEvent(id=uuid4(), text="totally different subject")
        await client.send(rejected)
        await client.send(released)

        events = await collect_events(client, count=1)
        await client.close()
        assert [item.text for item in events] == ["totally different subject"]
