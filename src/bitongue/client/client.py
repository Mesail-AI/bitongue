"""Client-side orchestration of flow and filter chain."""

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, cast

import anyio
from aioresult import ResultCapture

from bitongue.flow import Event, Flowing

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bitongue.filter import Filter

    from .config import BitongueConfig


class Bitongue[T: Event]:
    """Orchestrator tying the flow window to a filter chain.

    Producers push events through :meth:`send`; the consumer iterates
    :meth:`receive`, which yields events in send order after expiry
    removal and filtering. Filters run concurrently per event without
    short-circuiting — every filter sees every event — and any
    ``True`` verdict rejects the event. Filter failures (all filters
    having completed) surface as a single ``BaseExceptionGroup`` that
    terminates the receive stream.

    Both lifecycle methods are idempotent; on close, resource-holding
    filters are closed in reverse registration order.

    Args:
        config: Buffer and expiry settings.
        *filters: Filters applied in order; each may optionally
            provide ``start``/``close`` lifecycle methods.
    """

    def __init__(
        self,
        config: "BitongueConfig",
        *filters: "Filter[T]",
    ) -> None:

        self._config = config
        self._filters = filters

        self._flowing: Flowing[T] | None = None

        self._running = False

    @property
    def running(self) -> bool:
        """Whether the client is currently started."""

        return self._running

    async def start(self) -> None:
        """Start the flow window and every lifecycle-capable filter.

        Idempotent.
        """

        if self._running:
            return

        if self._flowing is None:
            self._flowing = Flowing[T](
                buffer_size=self._config.buffer_size,
                timeout=self._config.event_timeout,
            )

        if not self._flowing.running:
            await self._flowing.start()

        for _filter in self._filters:
            start = cast(
                "Callable[[], Awaitable[None]] | None",
                getattr(_filter, "start", None),
            )

            if start is not None:
                await start()

        self._running = True

    async def close(self) -> None:
        """Close every lifecycle-capable filter in reverse order.

        Then closes and discards the flow window. Idempotent.
        """

        if not self._running:
            return

        for _filter in reversed(list(self._filters)):
            close = cast(
                "Callable[[], Awaitable[None]] | None",
                getattr(_filter, "close", None),
            )

            if close is not None:
                await close()

        if self._flowing is not None:
            if self._flowing.running:
                await self._flowing.close()

            self._flowing = None

        self._running = False

    async def send(self, event: "T") -> None:
        """Push an event into the flow window.

        Waits while the buffer is full.

        Args:
            event: The event to enqueue.

        Raises:
            RuntimeError: If the client is not started.
        """

        if not self._running or self._flowing is None or not self._flowing.running:
            raise RuntimeError("Run `start` first.")

        await self._flowing.send(event)

    async def _filter(self, event: "T") -> bool:
        """Run the whole filter chain concurrently over one event.

        Every filter executes to completion — no short-circuiting — so
        side effects stay uniform across the chain. Filter exceptions
        are collected and raised together once all filters finished.

        Args:
            event: The candidate event.

        Returns:
            ``True`` when any filter rejected the event.

        Raises:
            BaseExceptionGroup: If any filter raised, wrapping all the
                failures.
        """

        captures: list[ResultCapture[bool]] = []
        async with anyio.create_task_group() as tg:
            captures.extend(
                ResultCapture.start_soon(
                    tg,
                    _filter.filter,
                    event,
                    suppress_exception=True,
                )
                for _filter in self._filters
            )

        failures: list[BaseException] = []

        for capture in captures:
            failure = capture.exception()

            if failure is not None:
                failures.append(failure)

        if failures:
            raise BaseExceptionGroup(
                "Filter chain execute failed.",
                failures,
            )

        # If any of results is "True",
        # means event has been filtered.
        return any(capture.result() for capture in captures)

    async def receive(self) -> AsyncGenerator["T", None]:
        """Consume filtered events in send order.

        Expired events are dropped by the flow; filtered events are
        dropped here; survivors are yielded one at a time.

        Yields:
            Events that passed the filter chain.

        Raises:
            RuntimeError: If the client is not started.
            BaseExceptionGroup: If any filter raised.
        """

        if not self._running or self._flowing is None or not self._flowing.running:
            raise RuntimeError("Run `start` first.")

        async for event in self._flowing.receive():
            try:
                if self._filters and await self._filter(event):
                    continue

                yield event

            except TimeoutError:
                continue

            except anyio.get_cancelled_exc_class():
                raise
