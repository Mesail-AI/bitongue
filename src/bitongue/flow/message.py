"""Message models carried by the flowing window."""

from typing import Literal
from uuid import UUID

from msgspec import field

from bitongue.base import BaseStruct

__all__ = (
    "BaseMessage",
    "MessageEntry",
    "TextualMessage",
)


class BaseMessage(BaseStruct):
    """Base message delivered through the flowing window.

    The minimal message envelope: a caller-supplied identity without a
    payload contract. Concrete message types subclass it to add their
    payload fields.

    Attributes:
        id: Caller-supplied unique identifier; bitongue never generates
            one — carry over the business-side ID the message came with.
    """

    id: UUID


class TextualMessage(BaseMessage):
    """A message whose payload is text.

    The default concrete message: ``type`` tags the payload kind and
    ``text`` carries the content. Built-in filters treat a message
    without a text payload as payloadless and release it.

    Attributes:
        type: Payload kind tag; fixed to ``"text"``.
        text: The text payload; ``None`` means the message carries no
            text payload.
    """

    type: Literal["text"] = "text"
    text: str | None = None


class MessageEntry[T: BaseMessage](BaseStruct):
    """A message wrapped for buffering inside the flowing window.

    Attributes:
        message: The wrapped message itself.
        enter_time: Epoch seconds when the entry entered the window; the
            expiry clock starts here, including time spent waiting in the
            buffer.
        timeout: Lifetime of the entry in seconds; ``None`` means the entry
            never expires. Enforced when the entry is drawn, not while it
            waits.
    """

    message: T

    enter_time: float
    timeout: float | None = field(default=None)
