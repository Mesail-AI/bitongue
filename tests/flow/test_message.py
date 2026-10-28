"""Tests for bitongue.flow.message."""

from typing import Literal, cast
from uuid import UUID, uuid4

import msgspec
import pytest

from bitongue.flow import BaseMessage, MessageEntry, TextualMessage


class TestBaseMessage:
    """Minimal envelope contract: caller-supplied identity only."""

    def test_id_round_trips_through_serialization(self) -> None:
        message = BaseMessage(id=uuid4())

        assert BaseMessage.from_dict(message.to_dict()) == message
        assert BaseMessage.from_json(message.to_json()) == message
        assert isinstance(BaseMessage.from_dict(message.to_dict()).id, UUID)


class TestTextualMessage:
    """Text payload contract: defaults, serialization, and the literal
    type constraint."""

    def test_type_defaults_to_text_and_text_to_none(self) -> None:
        message = TextualMessage(id=uuid4())

        assert message.type == "text"
        assert message.text is None

    def test_fields_round_trip_through_serialization(self) -> None:
        message = TextualMessage(id=uuid4(), text="m")

        assert TextualMessage.from_dict(message.to_dict()) == message
        assert TextualMessage.from_json(message.to_json()) == message

    def test_rejects_unknown_type_in_conversion(self) -> None:
        # msgspec does not validate at __init__; Literal constraints apply
        # at convert/decode time. The dict carries a valid id so the
        # reported error is the bogus type, not the missing field.
        bogus = cast("Literal['text']", "voice")

        with pytest.raises(msgspec.ValidationError):
            msgspec.convert(
                {"id": str(uuid4()), "type": bogus, "text": "x"},
                type=TextualMessage,
            )


class TestMessageEntry:
    """Entry field defaults."""

    def test_timeout_defaults_to_none(self) -> None:
        entry = MessageEntry(message=BaseMessage(id=uuid4()), enter_time=1.0)

        assert entry.timeout is None
