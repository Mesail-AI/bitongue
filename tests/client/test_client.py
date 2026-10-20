"""Tests for bitongue.client.client."""

import anyio
import pytest
from tests.client.conftest import (
    CollectResults,
    EchoResult,
    MakeClient,
    MakeFilter,
    MakeHandler,
)
from tests.conftest import MakeMessage, WaitUntil

from bitongue.flow import BaseMessage
from bitongue.handler import MessageHandleFailure


class TestFilterChain:
    """审计 A1 回归:任一过滤器拒绝的消息不得到达 handler。"""

    async def test_rejected_message_never_reaches_handler(
        self,
        make_client: MakeClient,
        make_handler: MakeHandler,
        make_filter: MakeFilter,
        make_message: MakeMessage,
        wait_until: WaitUntil,
    ) -> None:
        reject_all = make_filter(False)
        permit_all = make_filter(True)
        handler = make_handler()
        client = make_client(handler=handler, filters=[reject_all, permit_all])
        await client.start()
        await client.send(make_message("m1"))

        async with anyio.create_task_group() as tg:

            async def drain() -> None:
                async for _ in client.result():
                    pass  # 被拒消息不产生结果

            tg.start_soon(drain)
            await wait_until(lambda: len(reject_all.seen) == 1)
            tg.cancel_scope.cancel()

        await client.shutdown()
        assert permit_all.seen  # 现状:过滤器链不短路,全部执行
        assert handler.seen == []

    async def test_all_messages_rejected_when_any_filter_rejects(
        self,
        make_client: MakeClient,
        make_handler: MakeHandler,
        make_filter: MakeFilter,
        make_message: MakeMessage,
        wait_until: WaitUntil,
    ) -> None:
        reject_all = make_filter(False)
        handler = make_handler()
        client = make_client(handler=handler, filters=[reject_all])
        await client.start()
        await client.send(make_message("m1"))
        await client.send(make_message("m2"))

        async with anyio.create_task_group() as tg:

            async def drain() -> None:
                async for _ in client.result():
                    pass  # 被拒消息不产生结果

            tg.start_soon(drain)
            await wait_until(lambda: len(reject_all.seen) == 2)
            tg.cancel_scope.cancel()

        await client.shutdown()
        assert handler.seen == []

    async def test_accepted_message_reaches_handler(
        self,
        make_client: MakeClient,
        make_handler: MakeHandler,
        make_filter: MakeFilter,
        make_message: MakeMessage,
        collect_results: CollectResults,
    ) -> None:
        permit_all = make_filter(True)
        handler = make_handler()
        client = make_client(handler=handler, filters=[permit_all])
        await client.start()
        message = make_message("pass")
        await client.send(message)

        results = await collect_results(client, count=1)

        await client.shutdown()
        assert [item.content for item in results] == ["pass"]
        assert handler.seen == [message]

    async def test_without_filters_every_message_reaches_handler(
        self,
        make_client: MakeClient,
        make_handler: MakeHandler,
        make_message: MakeMessage,
        collect_results: CollectResults,
    ) -> None:
        handler = make_handler()
        client = make_client(handler=handler)
        await client.start()
        await client.send(make_message("m1"))
        await client.send(make_message("m2"))

        results = await collect_results(client, count=2)

        await client.shutdown()
        assert [item.content for item in results] == ["m1", "m2"]

    async def test_filter_exceptions_raise_one_group_and_terminate_stream(
        self,
        make_client: MakeClient,
        make_handler: MakeHandler,
        make_message: MakeMessage,
    ) -> None:
        # 准入是管道级设施:filter 异常汇总为异常组上抛并终止流,
        # 而非转为消息级信封继续流动;并发的兄弟异常互不吞没。
        class BrokenFilter:
            """Filter that always raises the given error."""

            def __init__(self, error: Exception) -> None:
                self._error = error
                self.seen: list[BaseMessage] = []

            async def filter(self, message: BaseMessage) -> bool:
                self.seen.append(message)
                raise self._error

        handler = make_handler()
        client = make_client(
            handler=handler,
            filters=[
                BrokenFilter(RuntimeError("admission is down")),
                BrokenFilter(ValueError("verdict backend crashed")),
            ],
        )
        await client.start()
        await client.send(make_message("m1"))
        await client.send(make_message("m2"))

        consumed: list[EchoResult | MessageHandleFailure[BaseMessage]] = []
        with pytest.raises(ExceptionGroup) as excinfo:
            async for item in client.result():
                consumed.append(item)  # noqa: PERF401 -- 流应在此处终止

        assert consumed == []  # 流在第一条消息处终止,消息不转为信封继续流动
        assert {type(exc) for exc in excinfo.value.exceptions} == {
            RuntimeError,
            ValueError,
        }  # 两个并发失败的 filter 异常都被保留
        await client.shutdown()


class TestConcurrentFilters:
    """The filter chain runs its filters concurrently, not one by one."""

    async def test_filters_run_concurrently(
        self,
        make_client: MakeClient,
        make_handler: MakeHandler,
        make_message: MakeMessage,
        collect_results: CollectResults,
    ) -> None:
        # The first filter blocks until the second one has been entered.
        # Sequential execution would deadlock into the handle timeout and
        # drop the message; concurrent execution lets both complete.
        release_first = anyio.Event()

        class BlockingFilter:
            """Filter that waits until its companion has started."""

            def __init__(self) -> None:
                self.seen: list[BaseMessage] = []

            async def filter(self, message: BaseMessage) -> bool:
                self.seen.append(message)
                with anyio.fail_after(2):
                    await release_first.wait()

                return True

        class ReleasingFilter:
            """Companion filter that unblocks the waiting one."""

            def __init__(self) -> None:
                self.seen: list[BaseMessage] = []

            async def filter(self, message: BaseMessage) -> bool:
                self.seen.append(message)
                release_first.set()

                return True

        blocking = BlockingFilter()
        releasing = ReleasingFilter()
        handler = make_handler()
        client = make_client(handler=handler, filters=[blocking, releasing])
        await client.start()
        await client.send(make_message("concurrent"))

        results = await collect_results(client, count=1)

        await client.shutdown()
        assert [item.content for item in results] == ["concurrent"]
        assert len(blocking.seen) == 1
        assert len(releasing.seen) == 1


class TestHandleTimeout:
    """审计 A3 回归:超时跳过消息但不断流;慢消费者不被误取消。"""

    async def test_timeout_skips_message_and_keeps_stream_alive(
        self,
        make_client: MakeClient,
        make_handler: MakeHandler,
        make_message: MakeMessage,
        collect_results: CollectResults,
    ) -> None:
        handler = make_handler(delays=[0.3, 0.0])
        client = make_client(handler=handler, handle_timeout=0.1)
        await client.start()
        await client.send(make_message("slow"))
        await client.send(make_message("fast"))

        results = await collect_results(client, count=1)

        await client.shutdown()
        assert [item.content for item in results] == ["fast"]
        assert len(handler.seen) == 2  # 慢消息进入了 handle,但被超时剔除

    async def test_slow_consumer_is_not_cancelled_between_results(
        self,
        make_client: MakeClient,
        make_handler: MakeHandler,
        make_message: MakeMessage,
        wait_until: WaitUntil,
    ) -> None:
        # 修复前:超时作用域跨越 yield,消费者在两次取结果之间的耗时计入
        # handle_timeout,导致消费者任务被误取消。本用例钉住修复后的行为。
        handler = make_handler()
        client = make_client(handler=handler, handle_timeout=0.1)
        await client.start()
        for i in range(3):
            await client.send(make_message(f"m{i}"))

        results: list[EchoResult] = []
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:

                async def drain() -> None:
                    async for item in client.result():
                        if isinstance(item, MessageHandleFailure):
                            continue
                        results.append(item)
                        await anyio.sleep(0.3)  # 每条结果取用耗时 > handle_timeout

                tg.start_soon(drain)
                await wait_until(lambda: len(results) == 3)
                tg.cancel_scope.cancel()

        assert [item.content for item in results] == ["m0", "m1", "m2"]
        await client.shutdown()


class TestHandlerError:
    """handler 异常转为 MessageHandleFailure 信封按序产出,结果流不终止。"""

    async def test_handler_error_yields_failure_envelope_and_stream_continues(
        self,
        make_client: MakeClient,
        make_message: MakeMessage,
        wait_until: WaitUntil,
    ) -> None:
        class FailOnceHandler:
            """Handler that fails the first call and succeeds afterwards."""

            def __init__(self) -> None:
                self.seen: list[BaseMessage] = []

            async def handle(self, message: BaseMessage) -> EchoResult:
                self.seen.append(message)
                if len(self.seen) == 1:
                    raise ValueError("boom")

                return EchoResult(id=message.id, content=message.text or "")

        handler = FailOnceHandler()
        client = make_client(handler=handler)
        await client.start()
        first = make_message("m1")
        second = make_message("m2")
        await client.send(first)
        await client.send(second)

        emitted: list[EchoResult | MessageHandleFailure[BaseMessage]] = []
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:

                async def drain() -> None:
                    async for item in client.result():
                        emitted.append(item)  # noqa: PERF401 -- 消费须可随时取消

                tg.start_soon(drain)
                await wait_until(lambda: len(emitted) == 2)
                tg.cancel_scope.cancel()

        await client.shutdown()
        failure = emitted[0]
        outcome = emitted[1]
        assert isinstance(failure, MessageHandleFailure)
        assert isinstance(outcome, EchoResult)
        assert failure.message is first  # 信封携带来源消息
        assert "boom" in failure.error  # 错误文本保留原始异常信息
        assert outcome.content == "m2"  # 流未终止,第二条消息正常产出
        assert handler.seen == [first, second]  # 两条消息都进入了 handle


class TestClientLifecycle:
    """start / shutdown / 未初始化守卫。"""

    async def test_send_before_start_raises_runtime_error(
        self, make_client: MakeClient, make_message: MakeMessage
    ) -> None:
        client = make_client()

        with pytest.raises(RuntimeError, match=r"Run `start` first\."):
            await client.send(make_message())

    async def test_result_before_start_raises_runtime_error(
        self, make_client: MakeClient
    ) -> None:
        client = make_client()
        gen = client.result()

        with pytest.raises(RuntimeError, match=r"Run `start` first\."):
            await gen.__anext__()

    async def test_shutdown_without_start_is_noop(self, make_client: MakeClient) -> None:
        client = make_client()

        await client.shutdown()

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

        await client.shutdown()

        after = client.running
        assert after is False

    async def test_double_start_preserves_buffered_messages(
        self,
        make_client: MakeClient,
        make_message: MakeMessage,
        collect_results: CollectResults,
    ) -> None:
        # A redundant start() must be a no-op: recreating the window here
        # would silently drop the message buffered before the second call.
        client = make_client()
        await client.start()
        await client.send(make_message("kept"))

        await client.start()

        results = await collect_results(client, count=1)

        await client.shutdown()
        assert [item.content for item in results] == ["kept"]

    async def test_double_start_keeps_client_usable(
        self,
        make_client: MakeClient,
        make_message: MakeMessage,
        collect_results: CollectResults,
    ) -> None:
        client = make_client()
        await client.start()

        await client.start()
        await client.send(make_message("m"))
        results = await collect_results(client, count=1)

        await client.shutdown()
        assert len(results) == 1

    async def test_restart_after_shutdown_accepts_messages(
        self,
        make_client: MakeClient,
        make_message: MakeMessage,
        collect_results: CollectResults,
    ) -> None:
        client = make_client()
        await client.start()
        await client.shutdown()

        await client.start()
        await client.send(make_message("again"))
        results = await collect_results(client, count=1)

        await client.shutdown()
        assert [item.content for item in results] == ["again"]


class TestConcurrentConsumers:
    """特征测试(审计 B7 现状):多个 result() 消费者瓜分消息流(各得其一、无重复)。"""

    async def test_consumers_split_messages_without_duplicates(
        self, make_client: MakeClient, make_message: MakeMessage
    ) -> None:
        client = make_client()
        await client.start()
        for text in ("a", "b", "c", "d"):
            await client.send(make_message(text))

        first = client.result()
        second = client.result()
        got_first = [await first.__anext__() for _ in range(2)]
        got_second = [await second.__anext__() for _ in range(2)]

        items = [*got_first, *got_second]
        contents = sorted(item.content for item in items if isinstance(item, EchoResult))
        assert contents == ["a", "b", "c", "d"]
        await first.aclose()
        await second.aclose()
        await client.shutdown()
