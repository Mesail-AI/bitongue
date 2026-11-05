"""Client configuration."""

from bitongue.base import BaseStruct

__all__ = ("BitongueConfig",)


class BitongueConfig(BaseStruct):
    """Runtime knobs for the :class:`Bitongue` orchestrator.

    Attributes:
        buffer_size: Capacity of the underlying flow window; a full
            buffer blocks producers (natural backpressure).
        event_timeout: Expiry window applied to every event, enforced
            at consumption time; ``None`` means events never expire.
    """

    buffer_size: int
    event_timeout: float | None = None
