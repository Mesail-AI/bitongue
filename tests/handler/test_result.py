"""Tests for bitongue.handler.result."""

from uuid import uuid4

import pytest

from bitongue.flow import BaseMessage, TextualMessage
from bitongue.handler import BaseResult, MessageHandleFailure


class SampleResult(BaseResult):
    """Concrete result exercising the base contract."""

    content: str


class TestBaseResult:
    """Result construction and serialization contract."""

    def test_id_is_required(self) -> None:
        with pytest.raises(TypeError):
            SampleResult(content="x")  # type: ignore[call-arg]

    def test_round_trips_through_dict_and_json(self) -> None:
        result = SampleResult(id=uuid4(), content="x")

        assert SampleResult.from_dict(result.to_dict()) == result
        assert SampleResult.from_json(result.to_json()) == result


class TestMessageHandleFailure:
    """Failure envelope construction and serialization contract."""

    def test_round_trips_through_dict_and_json(self) -> None:
        # Envelope decode resolves the generic TypeVar to its bound (see the
        # note in handler/result.py), so from_dict restores the message at
        # BaseMessage fidelity; the payload fields survive in the serialized
        # form, pinned by the dict-content test below.
        message = TextualMessage(id=uuid4(), text="m")
        failure = MessageHandleFailure(message=message, error="boom")

        restored: MessageHandleFailure[BaseMessage] = MessageHandleFailure.from_dict(
            failure.to_dict(),
        )

        assert restored == MessageHandleFailure(
            message=BaseMessage(id=message.id),
            error="boom",
        )

        restored_json: MessageHandleFailure[BaseMessage] = MessageHandleFailure.from_json(
            failure.to_json()
        )

        assert restored_json.message.id == message.id
        assert restored_json.error == "boom"

    def test_dict_keeps_the_source_message_and_error(self) -> None:
        message = TextualMessage(id=uuid4(), text="m")
        failure = MessageHandleFailure(message=message, error="boom")

        data = failure.to_dict()

        assert data["error"] == "boom"
        assert data["message"] == message.to_dict()
