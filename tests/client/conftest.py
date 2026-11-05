"""Fixtures and test doubles shared by the client unit tests."""

from collections.abc import Awaitable, Callable

import anyio
import pytest
from tests.conftest import TextualEvent

from bitongue.client import Bitongue, BitongueConfig
from bitongue.filter import Filter

type MakeClient = Callable[..., Bitongue[TextualEvent]]
type MakeFilter = Callable[[bool], StubFilter]
type CollectEvents = Callable[..., Awaitable[list[TextualEvent]]]


class StubFilter:
    """Filter double with a fixed verdict, recording seen events.

    Verdict follows the library contract: ``True`` rejects the event,
    ``False`` lets it pass.
    """

    def __init__(self, verdict: bool) -> None:
        self.verdict = verdict
        self.seen: list[TextualEvent] = []

    async def filter(self, event: TextualEvent) -> bool:
        self.seen.append(event)
        return self.verdict


def _build_client(
    *filters: Filter[TextualEvent],
    buffer_size: int = 8,
    event_timeout: float | None = None,
) -> Bitongue[TextualEvent]:
    """Build a client with sensible defaults; every knob is overridable."""
    config = BitongueConfig(
        buffer_size=buffer_size,
        event_timeout=event_timeout,
    )
    return Bitongue(config, *filters)


async def _collect_events(
    client: Bitongue[TextualEvent],
    *,
    count: int,
) -> list[TextualEvent]:
    """Consume exactly ``count`` events, then stop (5 s guard).

    A stream that yields fewer events stalls into the guard timeout and
    fails the test through ``TimeoutError``.
    """
    events: list[TextualEvent] = []
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:

            async def drain() -> None:
                async for item in client.receive():
                    # 逐条 append 而非 extend: 部分结果需即时可见, 供外层轮询提前终止
                    events.append(item)  # noqa: PERF401

            tg.start_soon(drain)
            while len(events) < count:
                await anyio.sleep(0.01)
            tg.cancel_scope.cancel()
    return events


@pytest.fixture
def make_filter() -> MakeFilter:
    """Factory fixture for stub filter doubles."""

    def _make(verdict: bool) -> StubFilter:
        return StubFilter(verdict)

    return _make


@pytest.fixture
def make_client() -> MakeClient:
    """Factory fixture for configured Bitongue clients."""
    return _build_client


@pytest.fixture
def collect_events() -> CollectEvents:
    """Bounded consumer helper for event streams."""
    return _collect_events
