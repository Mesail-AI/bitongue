"""Result models produced by handling messages."""

from uuid import UUID

from bitongue.base import BaseStruct

# Runtime import, not TYPE_CHECKING: msgspec resolves the generic TypeVar's
# bound when converting or decoding unparametrized instances of the struct.
from bitongue.flow import BaseMessage

__all__ = (
    "BaseResult",
    "MessageHandleFailure",
)


class BaseResult(BaseStruct):
    """Base class for handling results.

    Subclass it to declare the fields a handler yields; results are
    msgspec structures with the same serialization abilities as messages.

    Attributes:
        id: Caller-supplied unique identifier, mirrored from the source
            message; bitongue never generates one.
    """

    id: UUID


class MessageHandleFailure[T: BaseMessage](BaseStruct):
    """Failure envelope emitted when handling a message fails.

    When a handler raises, the orchestrator wraps the exception into
    :class:`bitongue.client.MessageHandleError` and emits one instance of
    this structure into the result stream, in order, before consuming the
    next message: a single message's failure never terminates the stream.

    It deliberately does not subclass :class:`BaseResult`. Normal results
    are handler-defined ``R`` structures; this is the library's own record
    of a failure, so consumers tell the two apart with ``isinstance``.

    Attributes:
        message: The source message whose handling failed.
        error: Text of the wrapped :class:`bitongue.client.MessageHandleError`.
    """

    message: T
    error: str
