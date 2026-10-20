"""Fixtures and test doubles shared by the client unit tests."""

from collections.abc import Awaitable, Callable, Collection, Sequence

import anyio
import pytest

from bitongue.client import Bitongue, BitongueConfig
from bitongue.filter import BaseFilter
from bitongue.flow import BaseMessage
from bitongue.handler import BaseHandler, BaseResult, MessageHandleFailure

type MakeClient = Callable[..., Bitongue[BaseMessage, EchoResult]]
type MakeFilter = Callable[[bool], StubFilter]
type MakeHandler = Callable[..., ScriptedHandler]
type CollectResults = Callable[..., Awaitable[list[EchoResult]]]


class EchoResult(BaseResult):
    """Concrete result carrying the handled text."""

    content: str


class StubFilter:
    """Filter double with a fixed verdict, recording seen messages."""

    def __init__(self, verdict: bool) -> None:
        self.verdict = verdict
        self.seen: list[BaseMessage] = []

    async def filter(self, message: BaseMessage) -> bool:
        self.seen.append(message)
        return self.verdict


class ScriptedHandler:
    """Handler double with per-call delays, an optional error, and call recording."""

    def __init__(
        self,
        *,
        delays: Sequence[float] = (),
        error: Exception | None = None,
    ) -> None:
        self._delays = list(delays)
        self.error = error
        self.seen: list[BaseMessage] = []

    async def handle(self, message: BaseMessage) -> EchoResult:
        self.seen.append(message)
        delay = self._delays.pop(0) if self._delays else 0.0
        if delay:
            await anyio.sleep(delay)
        if self.error is not None:
            raise self.error
        return EchoResult(id=message.id, content=message.text or "")


def _build_client(
    handler: BaseHandler[BaseMessage, EchoResult] | None = None,
    *,
    filters: Collection[BaseFilter[BaseMessage]] | None = None,
    flowing_size: int = 8,
    flowing_timeout: int | None = None,
    handle_timeout: float = 1.0,
) -> Bitongue[BaseMessage, EchoResult]:
    """Build a client with sensible defaults; every knob is overridable."""
    config = BitongueConfig(
        flowing_size=flowing_size,
        flowing_timeout=flowing_timeout,
        handle_timeout=handle_timeout,
    )
    return Bitongue(
        config,
        handler=handler if handler is not None else ScriptedHandler(),
        filters=filters,
    )


async def _collect_results(
    client: Bitongue[BaseMessage, EchoResult],
    *,
    count: int,
) -> list[EchoResult]:
    """Consume exactly ``count`` handled results, then stop (5 s guard).

    Failure envelopes are not handled results and are skipped; a stream
    that only yields envelopes stalls into the guard timeout.
    """
    results: list[EchoResult] = []
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:

            async def drain() -> None:
                # 逐条 append 而非 extend: 部分结果需即时可见, 供外层轮询提前终止
                async for item in client.result():
                    if isinstance(item, MessageHandleFailure):
                        continue
                    results.append(item)

            tg.start_soon(drain)
            while len(results) < count:
                await anyio.sleep(0.01)
            tg.cancel_scope.cancel()
    return results


@pytest.fixture
def make_handler() -> MakeHandler:
    """Factory fixture for scripted handler doubles."""

    def _make(
        *, delays: Sequence[float] = (), error: Exception | None = None
    ) -> ScriptedHandler:
        return ScriptedHandler(delays=delays, error=error)

    return _make


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
def collect_results() -> CollectResults:
    """Bounded consumer helper for result streams."""
    return _collect_results
