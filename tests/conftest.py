"""Global fixtures shared across unit-test subdirectories.

Subtree-specific fixtures live in their subtree's ``conftest.py``.
"""

from collections.abc import Awaitable, Callable
from uuid import uuid4

import anyio
import pytest

from bitongue.flow import TextualMessage

type MakeMessage = Callable[..., TextualMessage]
type WaitUntil = Callable[[Callable[[], bool]], Awaitable[None]]


@pytest.fixture
def make_message() -> MakeMessage:
    """Factory fixture for minimal text messages."""

    def _make(text: str = "hello") -> TextualMessage:
        return TextualMessage(id=uuid4(), text=text)

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
