"""Tests for bitongue.filter.neuro.filter (replayed model client)."""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import anyio
import pytest
from autogen_core.models import CreateResult, LLMMessage
from autogen_ext.models.replay import ReplayChatCompletionClient
from pytest_mock import MockerFixture
from tests.conftest import MakeMessage
from tests.filter.neuro.conftest import MakeNeuroFilter

from bitongue.client import Bitongue, BitongueConfig
from bitongue.filter.neuro import NeuroFilter, NeuroFilterPolicy
from bitongue.flow import BaseMessage
from bitongue.handler import BaseHandler, BaseResult

_REJECT = '{"filtered": true}'
_RELEASE = '{"filtered": false}'


class _EchoResult(BaseResult):
    content: str


class _EchoHandler(BaseHandler[BaseMessage, _EchoResult]):
    async def handle(self, message: BaseMessage) -> _EchoResult:
        return _EchoResult(id=message.id, content=message.text or "")


class TestConstruction:
    """Construction stores the policy and contacts nothing."""

    async def test_construction_is_lazy(
        self,
        make_neuro_filter: MakeNeuroFilter,
    ) -> None:
        sut, replay = make_neuro_filter([_RELEASE])
        assert sut.running is False
        assert replay.create_calls == []


class TestLifecycle:
    """Lifecycle: strict start, idempotent start/aclose, client
    orchestration, and a fresh model client after restart."""

    async def test_filter_before_start_raises(
        self,
        make_neuro_filter: MakeNeuroFilter,
        make_message: MakeMessage,
    ) -> None:
        sut, _ = make_neuro_filter([_RELEASE])
        with pytest.raises(RuntimeError, match="not running"):
            await sut.filter(make_message("hello"))

    async def test_filter_after_aclose_raises(
        self,
        make_neuro_filter: MakeNeuroFilter,
        make_message: MakeMessage,
    ) -> None:
        sut, _ = make_neuro_filter([_RELEASE])
        await sut.start()
        await sut.aclose()
        with pytest.raises(RuntimeError, match="not running"):
            await sut.filter(make_message("hello"))

    async def test_aclose_without_start_is_a_noop(
        self,
        make_neuro_filter: MakeNeuroFilter,
    ) -> None:
        sut, replay = make_neuro_filter([_RELEASE])
        await sut.aclose()
        assert sut.running is False
        assert replay.create_calls == []

    async def test_start_idempotent_closes_once(
        self,
        make_neuro_filter: MakeNeuroFilter,
        mocker: MockerFixture,
    ) -> None:
        sut, replay = make_neuro_filter([_RELEASE])
        spy = mocker.spy(replay, "close")
        await sut.start()
        await sut.start()
        await sut.aclose()
        await sut.aclose()
        assert sut.running is False
        assert spy.call_count == 1

    async def test_restart_builds_a_fresh_client(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_message: MakeMessage,
        mocker: MockerFixture,
    ) -> None:
        # Regression: aclose must drop the closed client, so the next start
        # builds a new one instead of reusing a closed connection pool.
        provided: list[ReplayChatCompletionClient] = []

        class _CountingProvider:
            def __init__(self, **_kwargs: object) -> None:
                return

            def provide(self) -> ReplayChatCompletionClient:
                client = ReplayChatCompletionClient([_RELEASE])
                provided.append(client)
                return client

        monkeypatch.setattr(
            "bitongue.filter.neuro.filter.OpenAIClientProvider",
            _CountingProvider,
        )
        sut: NeuroFilter[BaseMessage] = NeuroFilter(
            NeuroFilterPolicy(
                base_url="https://unit.test/v1",
                api_key="unit-key",
                model="unit-model",
                rules="no spam",
            ),
        )

        await sut.start()
        spy = mocker.spy(provided[0], "close")
        await sut.aclose()
        await sut.start()

        assert len(provided) == 2  # A fresh client was built for the restart.
        assert spy.call_count == 1  # The stale client was closed exactly once.
        assert await sut.filter(make_message("hello")) is True

    async def test_client_orchestration_starts_and_closes(
        self,
        make_neuro_filter: MakeNeuroFilter,
    ) -> None:
        sut, _ = make_neuro_filter([_RELEASE])
        config = BitongueConfig(
            flowing_size=8,
            flowing_timeout=30,
            handle_timeout=30,
        )
        client = Bitongue(config, handler=_EchoHandler(), filters=[sut])
        await client.start()
        assert sut.running is True
        await client.shutdown()
        assert sut.running is False


class TestVerdict:
    """Verdict handling: structured verdicts decide; guard paths release
    without a model call; rules and text reach the model as one isolated
    exchange."""

    async def test_filtered_verdict_rejected(
        self,
        make_neuro_filter: MakeNeuroFilter,
        make_message: MakeMessage,
    ) -> None:
        sut, _ = make_neuro_filter([_REJECT])
        await sut.start()
        assert await sut.filter(make_message("违规内容")) is False

    async def test_released_verdict_released(
        self,
        make_neuro_filter: MakeNeuroFilter,
        make_message: MakeMessage,
    ) -> None:
        sut, _ = make_neuro_filter([_RELEASE])
        await sut.start()
        assert await sut.filter(make_message("正常内容")) is True

    @pytest.mark.parametrize("text", [None, ""], ids=["none", "empty"])
    async def test_payloadless_message_released_without_model_call(
        self,
        make_neuro_filter: MakeNeuroFilter,
        text: str | None,
    ) -> None:
        sut, replay = make_neuro_filter([_REJECT])
        await sut.start()
        assert await sut.filter(BaseMessage(id=uuid4(), type="text", text=text)) is True
        assert replay.create_calls == []

    @pytest.mark.parametrize(
        "rules",
        ["", "   ", []],
        ids=["empty-str", "blank-str", "empty-list"],
    )
    async def test_empty_rules_release_without_model_call(
        self,
        make_neuro_filter: MakeNeuroFilter,
        rules: str | list[str],
        make_message: MakeMessage,
    ) -> None:
        sut, replay = make_neuro_filter([_REJECT], rules=rules)
        await sut.start()
        assert await sut.filter(make_message("hello")) is True
        assert replay.create_calls == []

    async def test_string_rules_used_verbatim(
        self,
        make_neuro_filter: MakeNeuroFilter,
        make_message: MakeMessage,
    ) -> None:
        # Regression: a str rules value must reach the model as-is, not
        # exploded into one-character lines by an Iterable misdispatch.
        sut, replay = make_neuro_filter([_RELEASE], rules="no spam")
        await sut.start()
        await sut.filter(make_message("hello"))
        contents = [m.content for m in replay.create_calls[0]["messages"]]
        assert "no spam" in contents
        assert "n\no\n \ns\np\na\nm" not in contents

    async def test_list_rules_joined_with_newlines(
        self,
        make_neuro_filter: MakeNeuroFilter,
        make_message: MakeMessage,
    ) -> None:
        sut, replay = make_neuro_filter(
            [_RELEASE],
            rules=["no spam", "no ads"],
        )
        await sut.start()
        await sut.filter(make_message("hello"))
        contents = [m.content for m in replay.create_calls[0]["messages"]]
        assert "no spam\nno ads" in contents

    async def test_message_text_reaches_model(
        self,
        make_neuro_filter: MakeNeuroFilter,
        make_message: MakeMessage,
    ) -> None:
        sut, replay = make_neuro_filter([_RELEASE])
        await sut.start()
        await sut.filter(make_message("hello"))
        contents = [m.content for m in replay.create_calls[0]["messages"]]
        assert "hello" in contents

    async def test_exchanges_are_isolated(
        self,
        make_neuro_filter: MakeNeuroFilter,
        make_message: MakeMessage,
    ) -> None:
        # Regression: the conversation buffer is cleared after every verdict
        # (in a finally block), so the second exchange sees a fresh context —
        # same shape as the first, with no trace of the first message text.
        sut, replay = make_neuro_filter([_RELEASE, _RELEASE])
        await sut.start()
        await sut.filter(make_message("first"))
        await sut.filter(make_message("second"))
        first, second = replay.create_calls
        assert len(second["messages"]) == len(first["messages"])
        assert "first" not in [m.content for m in second["messages"]]


class TestFailure:
    """Failure surface: unusable responses and backend errors propagate;
    a model call outliving the policy timeout raises TimeoutError."""

    async def test_unparseable_verdict_propagates(
        self,
        make_neuro_filter: MakeNeuroFilter,
        make_message: MakeMessage,
    ) -> None:
        # The model must answer with the agreed JSON shape; anything else is
        # a backend failure that surfaces, not a silent release.
        sut, _ = make_neuro_filter(['"just a string"'])
        await sut.start()
        with pytest.raises(ValueError):
            await sut.filter(make_message("hello"))

    async def test_backend_error_propagates(
        self,
        make_neuro_filter: MakeNeuroFilter,
        make_message: MakeMessage,
    ) -> None:
        # An empty replay queue makes the client raise on call, standing in
        # for any backend error: it must reach the caller unchanged.
        sut, _ = make_neuro_filter([])
        await sut.start()
        with pytest.raises(ValueError, match="No more mock responses"):
            await sut.filter(make_message("hello"))

    async def test_timeout_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_message: MakeMessage,
    ) -> None:
        class _SlowClient(ReplayChatCompletionClient):
            def __init__(self) -> None:
                super().__init__([_RELEASE])
                self._delay = 1.0

            async def create(
                self,
                messages: Sequence[LLMMessage],
                **kwargs: Any,
            ) -> CreateResult:
                await anyio.sleep(self._delay)
                return await super().create(messages, **kwargs)

        class _StubProvider:
            def __init__(self, **_kwargs: object) -> None:
                return

            def provide(self) -> _SlowClient:
                return _SlowClient()

        monkeypatch.setattr(
            "bitongue.filter.neuro.filter.OpenAIClientProvider",
            _StubProvider,
        )
        sut: NeuroFilter[BaseMessage] = NeuroFilter(
            NeuroFilterPolicy(
                base_url="https://unit.test/v1",
                api_key="unit-key",
                model="unit-model",
                rules="no spam",
                timeout=0.05,
            ),
        )
        await sut.start()
        with pytest.raises(TimeoutError):
            await sut.filter(make_message("hello"))
