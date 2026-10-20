"""Tests for bitongue.handler.result."""

from uuid import uuid4

import pytest

from bitongue.flow import BaseMessage
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
        message = BaseMessage(id=uuid4(), type="text", text="m")
        failure = MessageHandleFailure(message=message, error="boom")

        assert MessageHandleFailure.from_dict(failure.to_dict()) == failure
        assert MessageHandleFailure.from_json(failure.to_json()) == failure

    def test_dict_keeps_the_source_message_and_error(self) -> None:
        message = BaseMessage(id=uuid4(), type="text", text="m")
        failure = MessageHandleFailure(message=message, error="boom")

        data = failure.to_dict()

        assert data["error"] == "boom"
        assert data["message"] == message.to_dict()
