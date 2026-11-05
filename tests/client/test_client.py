"""Tests for bitongue.client.client."""

import anyio
import pytest
from tests.client.conftest import CollectEvents, MakeClient, MakeFilter
from tests.conftest import MakeEvent, TextualEvent, WaitUntil

from bitongue.flow import Event


class TestFilterChain:
    """审计 A1 回归:任一过滤器拒绝的事件不得被产出;链不短路,全部执行。"""

    async def test_rejected_event_never_yielded(
        self,
        make_client: MakeClient,
        make_filter: MakeFilter,
        make_event: MakeEvent,
        wait_until: WaitUntil,
    ) -> None:
        reject_all = make_filter(True)
        pass_all = make_filter(False)
        client = make_client(reject_all, pass_all)
        await client.start()
        await client.send(make_event("m1"))

        async with anyio.create_task_group() as tg:

            async def drain() -> None:
                async for _ in client.receive():
                    pass  # 被拒事件不产出

            tg.start_soon(drain)
            await wait_until(lambda: len(reject_all.seen) == 1)
            tg.cancel_scope.cancel()

        await client.close()
        assert pass_all.seen  # 现状:过滤器链不短路,全部执行
        assert reject_all.verdict is True

    async def test_all_events_rejected_when_any_filter_rejects(
        self,
        make_client: MakeClient,
        make_filter: MakeFilter,
        make_event: MakeEvent,
        wait_until: WaitUntil,
    ) -> None:
        reject_all = make_filter(True)
        client = make_client(reject_all)
        await client.start()
        await client.send(make_event("m1"))
        await client.send(make_event("m2"))

        async with anyio.create_task_group() as tg:

            async def drain() -> None:
                async for _ in client.receive():
                    pass  # 被拒事件不产出

            tg.start_soon(drain)
            await wait_until(lambda: len(reject_all.seen) == 2)
            tg.cancel_scope.cancel()

        await client.close()

    async def test_accepted_events_yielded_in_order(
        self,
        make_client: MakeClient,
        make_filter: MakeFilter,
        make_event: MakeEvent,
        collect_events: CollectEvents,
    ) -> None:
        pass_all = make_filter(False)
        client = make_client(pass_all)
        await client.start()
        first = make_event("m1")
        second = make_event("m2")
        await client.send(first)
        await client.send(second)

        events = await collect_events(client, count=2)

        await client.close()
        assert events == [first, second]

    async def test_without_filters_every_event_yielded(
        self,
        make_client: MakeClient,
        make_event: MakeEvent,
        collect_events: CollectEvents,
    ) -> None:
        client = make_client()
        await client.start()
        await client.send(make_event("m1"))
        await client.send(make_event("m2"))

        events = await collect_events(client, count=2)

        await client.close()
        assert [item.text for item in events] == ["m1", "m2"]

    async def test_filter_exceptions_raise_one_group_and_terminate_stream(
        self,
        make_client: MakeClient,
        make_event: MakeEvent,
    ) -> None:
        # 准入是管道级设施:filter 异常汇总为异常组上抛并终止流,
        # 而非转为事件级信封继续流动;并发的兄弟异常互不吞没。
        class BrokenFilter:
            """Filter that always raises the given error."""

            def __init__(self, error: Exception) -> None:
                self._error = error
                self.seen: list[TextualEvent] = []

            async def filter(self, event: TextualEvent) -> bool:
                self.seen.append(event)
                raise self._error

        client = make_client(
            BrokenFilter(RuntimeError("admission is down")),
            BrokenFilter(ValueError("verdict backend crashed")),
        )
        await client.start()
        await client.send(make_event("m1"))
        await client.send(make_event("m2"))

        consumed: list[Event] = []
        with pytest.raises(ExceptionGroup) as excinfo:
            async for item in client.receive():
                consumed.append(item)  # noqa: PERF401 -- 流应在此处终止

        assert consumed == []  # 流在第一条事件处终止,事件不转为信封继续流动
        assert {type(exc) for exc in excinfo.value.exceptions} == {
            RuntimeError,
            ValueError,
        }  # 两个并发失败的 filter 异常都被保留
        await client.close()


class TestConcurrentFilters:
    """The filter chain runs its filters concurrently, not one by one."""

    async def test_filters_run_concurrently(
        self,
        make_client: MakeClient,
        make_event: MakeEvent,
    ) -> None:
        # The first filter blocks until the second one has been entered.
        # Sequential execution would deadlock forever; concurrent execution
        # lets both complete and the event flow.
        release_first = anyio.Event()

        class BlockingFilter:
            """Filter that waits until its companion has started."""

            def __init__(self) -> None:
                self.seen: list[TextualEvent] = []

            async def filter(self, event: TextualEvent) -> bool:
                self.seen.append(event)
                with anyio.fail_after(2):
                    await release_first.wait()

                return False

        class ReleasingFilter:
            """Companion filter that unblocks the waiting one."""

            def __init__(self) -> None:
                self.seen: list[TextualEvent] = []

            async def filter(self, event: TextualEvent) -> bool:
                self.seen.append(event)
                release_first.set()

                return False

        blocking = BlockingFilter()
        releasing = ReleasingFilter()
        client = make_client(blocking, releasing)
        await client.start()
        await client.send(make_event("concurrent"))

        # Both filters must see the event; receiving it proves no deadlock.
        async with anyio.create_task_group() as tg:

            async def drain() -> None:
                async for _ in client.receive():
                    pass

            tg.start_soon(drain)
            with anyio.fail_after(5):
                while len(blocking.seen) < 1 or len(releasing.seen) < 1:
                    await anyio.sleep(0.01)
            tg.cancel_scope.cancel()

        await client.close()
        assert len(blocking.seen) == 1
        assert len(releasing.seen) == 1


class TestEventTimeout:
    """过期事件在消费侧被静默剔除,流不断(超时作用于 flow 层)。"""

    async def test_expired_event_skipped_and_stream_stays_alive(
        self,
        make_client: MakeClient,
        make_event: MakeEvent,
        collect_events: CollectEvents,
    ) -> None:
        client = make_client(event_timeout=0.1)
        await client.start()
        stale = make_event("stale")
        await client.send(stale)
        await anyio.sleep(0.2)  # 让第一条事件过期
        fresh = make_event("fresh")
        await client.send(fresh)

        events = await collect_events(client, count=1)

        await client.close()
        assert [item.text for item in events] == ["fresh"]


class TestClientLifecycle:
    """start / close / 未初始化守卫。"""

    async def test_send_before_start_raises_runtime_error(
        self, make_client: MakeClient, make_event: MakeEvent
    ) -> None:
        client = make_client()

        with pytest.raises(RuntimeError, match=r"Run `start` first\."):
            await client.send(make_event())

    async def test_receive_before_start_raises_runtime_error(
        self, make_client: MakeClient
    ) -> None:
        client = make_client()
        gen = client.receive()

        with pytest.raises(RuntimeError, match=r"Run `start` first\."):
            await gen.__anext__()

    async def test_close_without_start_is_noop(self, make_client: MakeClient) -> None:
        client = make_client()

        await client.close()

    async def test_running_reflects_lifecycle(self, make_client: MakeClient) -> None:
        # Read the property into a local before asserting: mypy narrows
        # read-only member accesses, and asserting on the member directly
        # would mark the later statements unreachable.
        client = make_client()

        before = client.running
        assert before is False

        await client.start()

        started = client.running
        assert started is True

        await client.close()

        after = client.running
        assert after is False

    async def test_double_start_preserves_buffered_events(
        self,
        make_client: MakeClient,
        make_event: MakeEvent,
        collect_events: CollectEvents,
    ) -> None:
        # A redundant start() must be a no-op: recreating the window here
        # would silently drop the event buffered before the second call.
        client = make_client()
        await client.start()
        await client.send(make_event("kept"))

        await client.start()

        events = await collect_events(client, count=1)

        await client.close()
        assert [item.text for item in events] == ["kept"]

    async def test_restart_after_close_accepts_events(
        self,
        make_client: MakeClient,
        make_event: MakeEvent,
        collect_events: CollectEvents,
    ) -> None:
        client = make_client()
        await client.start()
        await client.close()

        await client.start()
        await client.send(make_event("again"))
        events = await collect_events(client, count=1)

        await client.close()
        assert [item.text for item in events] == ["again"]


class TestCloseLifecycle:
    """close 逆序关闭持有资源的过滤器,且只触碰实现了生命周期的过滤器。

    回归:close 一度误调用 filter 的 ``start`` 而非 ``close``。
    """

    async def test_closes_filters_in_reverse_order(self, make_client: MakeClient) -> None:
        calls: list[str] = []

        class LifecycleFilter:
            """Filter double recording lifecycle calls under a tag."""

            def __init__(self, tag: str) -> None:
                self._tag = tag

            async def start(self) -> None:
                calls.append(f"start:{self._tag}")

            async def close(self) -> None:
                calls.append(f"close:{self._tag}")

            async def filter(self, event: TextualEvent) -> bool:
                return False

        class PlainFilter:
            """Filter double without any lifecycle methods."""

            async def filter(self, event: TextualEvent) -> bool:
                return False

        first = LifecycleFilter("a")
        plain = PlainFilter()
        last = LifecycleFilter("c")
        client = make_client(first, plain, last)
        await client.start()
        calls.clear()  # 只关心 close 阶段的调用序列

        await client.close()

        assert calls == ["close:c", "close:a"]  # 逆序;plain 未被触碰

    async def test_double_close_is_noop(self, make_client: MakeClient) -> None:
        client = make_client()
        await client.start()

        await client.close()
        await client.close()


class TestConcurrentConsumers:
    """特征测试(审计 B7 现状):多个 receive() 消费者瓜分事件流(各得其一、无重复)。"""

    async def test_consumers_split_events_without_duplicates(
        self, make_client: MakeClient, make_event: MakeEvent
    ) -> None:
        client = make_client()
        await client.start()
        for text in ("a", "b", "c", "d"):
            await client.send(make_event(text))

        first = client.receive()
        second = client.receive()
        got_first = [await first.__anext__() for _ in range(2)]
        got_second = [await second.__anext__() for _ in range(2)]

        items = [*got_first, *got_second]
        texts = sorted(item.text for item in items)
        assert texts == ["a", "b", "c", "d"]
        await first.aclose()
        await second.aclose()
        await client.close()
