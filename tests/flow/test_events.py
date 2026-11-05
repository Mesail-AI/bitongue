"""Tests for bitongue.flow.events."""

from typing import Literal, cast
from uuid import UUID, uuid4

import msgspec
import pytest
from tests.conftest import TextualEvent

from bitongue.flow import Event, EventEntry, TextEvent


class TestEvent:
    """Minimal envelope contract: caller-supplied identity only."""

    def test_id_round_trips_through_serialization(self) -> None:
        event = Event(id=uuid4())

        assert Event.from_dict(event.to_dict()) == event
        assert Event.from_json(event.to_json()) == event
        assert isinstance(Event.from_dict(event.to_dict()).id, UUID)


class TestTextEvent:
    """Text payload contract: required text, literal type constraint."""

    def test_fields_round_trip_through_serialization(self) -> None:
        event = TextEvent(type="text", text="m")

        assert TextEvent.from_dict(event.to_dict()) == event
        assert TextEvent.from_json(event.to_json()) == event

    def test_carries_no_identity(self) -> None:
        # TextEvent is a payload shape, not an envelope: it deliberately
        # defines no id field.
        assert "id" not in TextEvent.__struct_fields__

    def test_rejects_unknown_type_in_conversion(self) -> None:
        # msgspec does not validate at __init__; Literal constraints apply
        # at convert/decode time.
        bogus = cast("Literal['text']", "voice")

        with pytest.raises(msgspec.ValidationError):
            msgspec.convert(
                {"type": bogus, "text": "x"},
                type=TextEvent,
            )


class TestTextualEvent:
    """Concrete event combining identity with the text payload shape."""

    def test_defaults(self) -> None:
        event = TextualEvent(id=uuid4())

        assert event.type == "text"
        assert event.text == "hello"

    def test_round_trips_through_serialization(self) -> None:
        event = TextualEvent(id=uuid4(), text="m")

        assert TextualEvent.from_dict(event.to_dict()) == event
        assert TextualEvent.from_json(event.to_json()) == event


class TestEventEntry:
    """Entry field defaults."""

    def test_timeout_defaults_to_none(self) -> None:
        entry = EventEntry(event=TextualEvent(id=uuid4()), enter_time=1.0)

        assert entry.timeout is None
