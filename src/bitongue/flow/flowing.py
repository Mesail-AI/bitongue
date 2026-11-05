"""In-memory bounded event stream window."""

import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import anyio

from .events import Event, EventEntry

if TYPE_CHECKING:
    from anyio.streams.memory import (
        MemoryObjectReceiveStream,
        MemoryObjectSendStream,
    )


__all__ = ("Flowing",)


class Flowing[T: Event]:
    """Bounded FIFO window for events in memory.

    Backed by an anyio memory object stream of capacity ``buffer_size``:
    producers wait when the buffer is full, which gives natural
    backpressure. Each event is wrapped in an :class:`EventEntry` at
    send time; expiry is enforced on the consumer side — entries whose
    window elapsed before consumption are silently skipped, never
    reported as errors. The stream is single-consumer.
    """

    def __init__(
        self,
        buffer_size: int,
        *,
        timeout: float | None = None,
    ) -> None:
        """Create an unstarted window.

        Args:
            buffer_size: Capacity of the underlying buffer; a full
                buffer blocks producers.
            timeout: Expiry window applied to every entry, or ``None``
                for no expiry.
        """

        self._buffer_size = buffer_size
        self._timeout = timeout

        self._sender: MemoryObjectSendStream[EventEntry[T]] | None = None
        self._receiver: MemoryObjectReceiveStream[EventEntry[T]] | None = None

        self._running = False

    @property
    def running(self) -> bool:
        """Whether the window is currently started."""

        return self._running

    async def start(self) -> None:
        """Start the window. Idempotent."""

        if self._running:
            return

        if self._sender is None or self._receiver is None:
            self._sender, self._receiver = anyio.create_memory_object_stream[
                EventEntry[T]
            ](max_buffer_size=self._buffer_size)

        self._running = True

    async def close(self) -> None:
        """Close both ends of the window. Idempotent."""

        if not self._running:
            return

        if self._sender is not None:
            await self._sender.aclose()
            self._sender = None

        if self._receiver is not None:
            await self._receiver.aclose()
            self._receiver = None

        self._running = False

    async def send(self, event: "T") -> None:
        """Put an event into the window.

        Waits while the buffer is full. The entry's expiry clock starts
        now.

        Args:
            event: The event to enqueue.

        Raises:
            RuntimeError: If the window is not running.
        """

        if not self._running or self._sender is None:
            raise RuntimeError(
                "Flowing is not running",
            )

        await self._sender.send(
            EventEntry[T](
                event=event,
                enter_time=time.time(),
                timeout=self._timeout,
            )
        )

    async def receive(self) -> AsyncGenerator["T", None]:
        """Consume events in send order, one at a time.

        Entries whose expiry window elapsed before consumption are
        silently skipped.

        Yields:
            Events in send order, expired ones excluded.

        Raises:
            RuntimeError: If the window is not running.
        """

        if not self._running or self._receiver is None:
            raise RuntimeError(
                "Flowing is not running",
            )

        async for entry in self._receiver:
            if (
                entry.timeout is not None
                and time.time() - entry.enter_time > entry.timeout
            ):
                continue

            yield entry.event
