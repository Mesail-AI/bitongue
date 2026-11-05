"""Event models flowing through the stream."""

from typing import Literal
from uuid import UUID

from bitongue.base import BaseStruct

__all__ = (
    "Event",
    "EventEntry",
    "TextEvent",
)


class Event(BaseStruct):
    """Minimal event envelope.

    Carries only the identity: callers generate the ``id`` and the
    library transparently passes it through — results derived from an
    event mirror its id back to the business side.
    """

    id: UUID


class TextEvent(BaseStruct):
    """Textual payload shape shared by text-oriented filters.

    Unlike :class:`Event` it carries no identity — it defines the
    ``type`` discriminator (fixed to ``"text"``) and the text body that
    text-oriented filters match against.
    """

    type: Literal["text"]
    text: str


class EventEntry[T: Event](BaseStruct):
    """Flow entry wrapping an event with timing metadata.

    Args:
        event: The wrapped event.
        enter_time: Time the event entered the flow.
        timeout: Expiry window relative to ``enter_time``; ``None``
            means the entry never expires.
    """

    event: T

    enter_time: float
    timeout: float | None = None
