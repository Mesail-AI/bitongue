"""End-to-end integration tests for the Bitongue client."""

import anyio
import pytest

from test_integration.conftest import (
    CollectResults,
    EchoResult,
    MakeClient,
    MakeFilter,
    MakeHandler,
    MakeMessage,
)

pytestmark = pytest.mark.integration


class TestEndToEndFlow:
    """start → 并发 send → filter → handle → result 收齐 → shutdown。"""

    async def test_delivers_all_messages_in_order(
        self,
        make_client: MakeClient,
        make_handler: MakeHandler,
        make_filter: MakeFilter,
        make_message: MakeMessage,
        collect_results: CollectResults,
    ) -> None:
        handler = make_handler()
        permit_all = make_filter(True)
        client = make_client(handler=handler, filters=[permit_all])
        await client.start()

        async with anyio.create_task_group() as tg:

            async def send_all() -> None:
                for i in range(3):
                    await client.send(make_message(f"m{i}"))

            tg.start_soon(send_all)
            results = await collect_results(client, count=3)
            assert [item.content for item in results] == ["m0", "m1", "m2"]

        assert len(handler.seen) == 3
        await client.shutdown()


class TestShutdownDuringConsumption:
    """特征测试(审计 B2 现状):shutdown 关闭 receiver,活跃消费者下一次取消息
    得到 ClosedResourceError 而非优雅排空。修复 B2 后翻转本断言。"""

    async def test_shutdown_mid_consumption_raises_closed_resource_error(
        self, make_client: MakeClient, make_message: MakeMessage
    ) -> None:
        client = make_client()
        await client.start()
        await client.send(make_message("only"))
        results = client.result()
        first = await results.__anext__()
        assert isinstance(first, EchoResult)
        assert first.content == "only"

        await client.shutdown()

        with pytest.raises(anyio.ClosedResourceError):
            await results.__anext__()
