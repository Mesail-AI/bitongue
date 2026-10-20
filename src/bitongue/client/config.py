from bitongue.base import BaseStruct

__all__ = ("BitongueConfig",)


class BitongueConfig(BaseStruct):
    """Bitongue configuration class."""

    flowing_size: int
    flowing_timeout: int | None

    handle_timeout: float
