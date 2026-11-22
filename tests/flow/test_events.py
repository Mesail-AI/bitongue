"""Tests for bitongue.flow.events."""

from collections.abc import Callable
from typing import Literal, cast
from uuid import UUID, uuid4

import msgspec
import pytest

from bitongue.flow import Event, EventEntry, TextEvent


class VoiceEvent(Event):
    """Event whose discriminator names a payload field it does not carry."""

    content_type: Literal["voice"] = "voice"


class TestEvent:
    """Envelope contract: caller-supplied identity, optional metadata, and
    payload resolution through ``content``."""

    def test_id_round_trips_through_serialization(self) -> None:
        event = Event(id=uuid4())

        assert Event.from_dict(event.to_dict()) == event
        assert Event.from_json(event.to_json()) == event
        assert isinstance(Event.from_dict(event.to_dict()).id, UUID)

    def test_metadata_defaults_to_none(self) -> None:
        assert Event(id=uuid4()).metadata is None

    def test_metadata_round_trips_through_serialization(self) -> None:
        event = Event(id=uuid4(), metadata={"source": "test", "retries": 1})

        assert Event.from_dict(event.to_dict()) == event
        assert Event.from_json(event.to_json()) == event

    def test_content_is_none_without_content_type(self) -> None:
        assert Event(id=uuid4()).content is None

    def test_content_is_none_when_named_field_is_absent(self) -> None:
        assert VoiceEvent(id=uuid4()).content is None


class TestTextEvent:
    """Text payload contract: inherits the envelope, discriminates by
    ``content_type``, and requires keyword-only construction."""

    def test_is_an_event(self) -> None:
        assert issubclass(TextEvent, Event)

    def test_rejects_positional_construction(self) -> None:
        constructor = cast("Callable[..., TextEvent]", TextEvent)

        with pytest.raises(TypeError, match="positional"):
            constructor(uuid4(), "text", "m")

    def test_fields_round_trip_through_serialization(self) -> None:
        event = TextEvent(id=uuid4(), content_type="text", text="m")
        decoded = TextEvent.from_dict(event.to_dict())

        assert decoded == event
        assert decoded.id == event.id
        assert TextEvent.from_json(event.to_json()) == event

    def test_content_resolves_text_payload(self) -> None:
        event = TextEvent(id=uuid4(), content_type="text", text="m")

        assert event.content == "m"

    def test_rejects_unknown_content_type_in_conversion(self) -> None:
        # msgspec does not validate at __init__; Literal constraints apply
        # at convert/decode time.
        bogus = cast("Literal['text']", "voice")

        with pytest.raises(msgspec.ValidationError):
            msgspec.convert(
                {"id": uuid4(), "content_type": bogus, "text": "x"},
                type=TextEvent,
            )


class TestEventEntry:
    """Entry field defaults."""

    def test_timeout_defaults_to_none(self) -> None:
        event = TextEvent(id=uuid4(), content_type="text", text="hello")
        entry = EventEntry(event=event, enter_time=1.0)

        assert entry.timeout is None
