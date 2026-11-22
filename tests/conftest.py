"""Global fixtures shared across unit-test subdirectories.

Subtree-specific fixtures live in their subtree's ``conftest.py``.
"""

from collections.abc import Awaitable, Callable
from uuid import uuid4

import anyio
import pytest

from bitongue.flow import TextEvent

type MakeEvent = Callable[..., TextEvent]
type WaitUntil = Callable[[Callable[[], bool]], Awaitable[None]]


@pytest.fixture
def make_event() -> MakeEvent:
    """Factory fixture for text events with a fresh caller-supplied id."""

    def _make(text: str = "hello") -> TextEvent:
        return TextEvent(id=uuid4(), content_type="text", text=text)

    return _make


@pytest.fixture
def wait_until() -> WaitUntil:
    """Condition-polling helper, bounded by a timeout."""

    async def _wait_until(
        predicate: Callable[[], bool],
        *,
        timeout: float = 2.0,
    ) -> None:
        with anyio.fail_after(timeout):
            while not predicate():
                await anyio.sleep(0.01)

    return _wait_until
