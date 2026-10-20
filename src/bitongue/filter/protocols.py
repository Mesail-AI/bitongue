"""Message admission gate for the flowing pipeline.

A filter decides whether a message is allowed to proceed to handling.
Implement the protocol with a plain class — no inheritance required.
"""

from typing import Protocol, runtime_checkable

from bitongue.flow import BaseMessage

__all__ = (
    "BaseFilter",
    "FilterLifecycle",
)


class BaseFilter[T: BaseMessage](Protocol):
    """A predicate that decides which messages may proceed.

    Implementations should be side-effect-free predicates: the orchestrator
    runs every filter in the chain without short-circuiting, so a filter
    may be called even when an earlier one already rejected the message.

    Raising turns the whole admission round into a pipeline-scoped
    failure: the orchestrator waits for every filter, collects all their
    exceptions into one :class:`ExceptionGroup`, and raises it —
    terminating the result stream.

    Returns:
        ``True`` to release the message into handling; ``False`` to reject
        it, which drops the message silently with no result and no error.
    """

    async def filter(self, message: "T") -> bool: ...


@runtime_checkable
class FilterLifecycle(Protocol):
    """Lifecycle hooks for filters that hold runtime resources.

    A filter that builds connections or loads models implements this
    protocol so the orchestrator can pay the initialization cost once at
    client start-up instead of on the first filtered message: the client
    calls :meth:`start` when it starts and :meth:`aclose` when it shuts
    down. Plain filters do not implement it and work with no lifecycle
    management.

    The capability is detected structurally, so :meth:`start` should be
    idempotent — a filter started eagerly by the client still tolerates a
    lazy start attempt from its own code path.
    """

    async def start(self) -> None: ...

    async def aclose(self) -> None: ...
