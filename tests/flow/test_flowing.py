"""Tests for bitongue.flow.flowing."""

import anyio
import pytest
from tests.conftest import MakeMessage, WaitUntil

from bitongue.flow import BaseMessage, Flowing, FlowingNotInitializedError, TextualMessage


class TestFlowingLifecycle:
    """start / shutdown / running and the uninitialized guards."""

    async def test_draw_before_start_raises(self, make_message: MakeMessage) -> None:
        flow = Flowing[BaseMessage](size=1)

        with pytest.raises(FlowingNotInitializedError) as excinfo:
            await flow.draw(make_message())

        assert excinfo.type is FlowingNotInitializedError

    async def test_flow_before_start_raises_on_first_anext(self) -> None:
        flow = Flowing[BaseMessage](size=1)
        gen = flow.flow()

        with pytest.raises(FlowingNotInitializedError):
            await gen.__anext__()

    async def test_start_sets_running_and_allows_draw(
        self, make_message: MakeMessage
    ) -> None:
        flow = Flowing[BaseMessage](size=1)

        await flow.start()
        assert flow.running
        await flow.draw(make_message())

        await flow.shutdown()

    async def test_shutdown_clears_running(self, make_message: MakeMessage) -> None:
        flow = Flowing[BaseMessage](size=1)
        await flow.start()

        await flow.shutdown()
        assert not flow.running
        with pytest.raises(FlowingNotInitializedError):
            await flow.draw(make_message())

    async def test_start_is_idempotent(self, make_message: MakeMessage) -> None:
        flow = Flowing[BaseMessage](size=1)

        await flow.start()
        await flow.start()
        await flow.draw(make_message())

        await flow.shutdown()


class TestFlowingExpiry:
    """Expired entries are dropped; timeout=None never expires (审计 A2 回归)."""

    async def test_none_timeout_delivers_message(
        self, make_message: MakeMessage, wait_until: WaitUntil
    ) -> None:
        flow = Flowing[BaseMessage](size=4, timeout=None)
        await flow.start()
        message = make_message("m")
        await flow.draw(message)

        got: list[BaseMessage] = []
        async with anyio.create_task_group() as tg:

            async def drain() -> None:
                # 逐条 append 而非 extend: 部分结果需即时可见, 供轮询提前终止
                async for item in flow.flow():
                    got.append(item)  # noqa: PERF401

            tg.start_soon(drain)
            await wait_until(lambda: len(got) == 1)
            tg.cancel_scope.cancel()

        assert got == [message]
        await flow.shutdown()

    @pytest.mark.parametrize(
        ("advance", "delivered"),
        [(5.0, True), (15.0, False)],
        ids=["within-timeout", "past-timeout"],
    )
    async def test_entry_expiry_boundary(
        self,
        advance: float,
        delivered: bool,
        monkeypatch: pytest.MonkeyPatch,
        make_message: MakeMessage,
        wait_until: WaitUntil,
    ) -> None:
        clock = {"now": 1000.0}
        monkeypatch.setattr("bitongue.flow.flowing.time.time", lambda: clock["now"])
        flow = Flowing[TextualMessage](size=4, timeout=10)
        await flow.start()
        first = make_message("first")
        await flow.draw(first)
        clock["now"] = 1000.0 + advance
        second = make_message("second")
        await flow.draw(second)

        expected_count = 2 if delivered else 1
        got: list[TextualMessage] = []
        async with anyio.create_task_group() as tg:

            async def drain() -> None:
                # 逐条 append 而非 extend: 部分结果需即时可见, 供轮询提前终止
                async for item in flow.flow():
                    got.append(item)  # noqa: PERF401

            tg.start_soon(drain)
            await wait_until(lambda: len(got) == expected_count)
            tg.cancel_scope.cancel()

        if delivered:
            assert [item.text for item in got] == ["first", "second"]
        else:
            assert [item.text for item in got] == ["second"]
        await flow.shutdown()


class TestFlowingBackpressure:
    """A full buffer blocks draw() until the flow is consumed."""

    async def test_draw_blocks_when_buffer_full_then_resumes(
        self, make_message: MakeMessage, wait_until: WaitUntil
    ) -> None:
        flow = Flowing[BaseMessage](size=1)
        await flow.start()
        first = make_message("first")
        second = make_message("second")
        await flow.draw(first)

        got: list[BaseMessage] = []
        async with anyio.create_task_group() as tg:

            async def blocked_draw() -> None:
                await flow.draw(second)

            async def drain() -> None:
                # 逐条 append 而非 extend: 部分结果需即时可见, 供轮询提前终止
                async for item in flow.flow():
                    got.append(item)  # noqa: PERF401

            tg.start_soon(blocked_draw)
            tg.start_soon(drain)
            await wait_until(lambda: len(got) == 2)
            tg.cancel_scope.cancel()

        assert got == [first, second]
        await flow.shutdown()
