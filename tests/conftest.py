"""Global fixtures shared across unit-test subdirectories.

Subtree-specific fixtures live in their subtree's ``conftest.py``.
"""

from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import uuid4

import anyio
import pytest

from bitongue.flow import Event, TextEvent

type MakeEvent = Callable[..., "TextualEvent"]
type MakeTextEvent = Callable[..., TextEvent]
type WaitUntil = Callable[[Callable[[], bool]], Awaitable[None]]


class TextualEvent(Event):
    """Concrete business event: identity plus a text payload.

    Tests flow this through ``Flowing``/``Bitongue``/``Filter`` the way
    a real consumer would: a concrete ``Event`` subclass carrying the
    textual fields text-oriented filters match against.
    """

    type: Literal["text"] = "text"
    text: str = "hello"


@pytest.fixture
def make_event() -> MakeEvent:
    """Factory fixture for minimal text events."""

    def _make(text: str = "hello") -> TextualEvent:
        return TextualEvent(id=uuid4(), text=text)

    return _make


@pytest.fixture
def make_text_event() -> MakeTextEvent:
    """Factory fixture for bare text payloads (no identity)."""

    def _make(text: str = "hello") -> TextEvent:
        return TextEvent(type="text", text=text)

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
