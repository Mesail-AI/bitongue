"""Event models flowing through the stream."""

from typing import Any, Literal
from uuid import UUID

from bitongue.base import BaseStruct

__all__ = (
    "Event",
    "EventEntry",
    "TextEvent",
)


class Event(BaseStruct):
    """Minimal event envelope.

    Carries the caller-supplied ``id``, optional free-form ``metadata``,
    and a ``content`` view resolving the payload named by
    ``content_type``. The library transparently passes events through —
    results derived from an event mirror its id back to the business
    side.
    """

    id: UUID

    metadata: dict[str, Any] | None = None

    @property
    def content(self) -> Any:
        """Payload named by ``content_type``, or ``None`` when absent."""

        if (content_type := getattr(self, "content_type", None)) is None:
            return None

        return getattr(self, content_type, None)


class TextEvent(Event, kw_only=True):
    """Textual payload shape shared by text-oriented filters.

    Adds the ``content_type`` discriminator (fixed to ``"text"``) and the
    text body that text-oriented filters match against. Construction is
    keyword-only, inherited envelope fields included.
    """

    content_type: Literal["text"]
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
