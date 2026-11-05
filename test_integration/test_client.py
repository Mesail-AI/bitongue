"""End-to-end integration tests for the Bitongue client."""

import anyio
import pytest

from test_integration.conftest import (
    CollectEvents,
    MakeClient,
    MakeEvent,
    MakeFilter,
)

pytestmark = pytest.mark.integration


class TestEndToEndFlow:
    """start → 并发 send → filter → receive 收齐 → close。"""

    async def test_delivers_all_events_in_order(
        self,
        make_client: MakeClient,
        make_filter: MakeFilter,
        make_event: MakeEvent,
        collect_events: CollectEvents,
    ) -> None:
        pass_all = make_filter(False)
        client = make_client(pass_all)
        await client.start()

        async with anyio.create_task_group() as tg:

            async def send_all() -> None:
                for i in range(3):
                    await client.send(make_event(f"m{i}"))

            tg.start_soon(send_all)
            events = await collect_events(client, count=3)
            assert [item.text for item in events] == ["m0", "m1", "m2"]

        assert len(pass_all.seen) == 3
        await client.close()


class TestShutdownDuringConsumption:
    """特征测试(审计 B2 现状):close 关闭 receiver,活跃消费者下一次取事件
    得到 ClosedResourceError 而非优雅排空。修复 B2 后翻转本断言。"""

    async def test_close_mid_consumption_raises_closed_resource_error(
        self, make_client: MakeClient, make_event: MakeEvent
    ) -> None:
        client = make_client()
        await client.start()
        await client.send(make_event("only"))
        events = client.receive()
        first = await events.__anext__()
        assert first.text == "only"

        await client.close()

        with pytest.raises(anyio.ClosedResourceError):
            await events.__anext__()
