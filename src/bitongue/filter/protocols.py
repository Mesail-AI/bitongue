"""Filter chain contracts."""

from typing import Protocol, runtime_checkable

from bitongue.flow import Event

__all__ = (
    "Filter",
    "FilterLifecycle",
)


@runtime_checkable
class Filter[T: Event](Protocol):
    """Gate an event before it reaches the consumer."""

    async def filter(self, event: "T") -> bool:
        """Judge the event.

        Args:
            event: The candidate event.

        Returns:
            ``True`` to reject the event (silently dropped), ``False``
            to let it pass.
        """

        ...


@runtime_checkable
class FilterLifecycle(Protocol):
    """Lifecycle for filters holding resources.

    The client probes this structurally (``getattr``): filters that
    implement ``start``/``close`` are started and closed by the client,
    so resource-holding filters should expose exactly these names.
    """

    async def start(self) -> None: ...

    async def close(self) -> None: ...
