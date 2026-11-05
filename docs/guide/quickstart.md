# 快速上手

本页带你从安装到跑通第一个完整示例：发送两条事件，经过过滤器，消费通过的事件。

## 前置要求

- Python 3.12 及以上版本；
- 可选：[uv](https://docs.astral.sh/uv/)（推荐的包管理器）。

## 安装

使用 uv：

```bash
uv add bitongue
```

或使用 pip：

```bash
pip install bitongue
```

如果该包尚未发布到 PyPI，可以直接从源码安装：

```bash
uv add git+https://github.com/Ahsen17/bitongue.git
```

内置的 `SparseTextFilter` 依赖 fastembed、jieba 与 qdrant-client，随可选依赖组
`sparse` 发布，按需安装（pip 用户写 `pip install "bitongue[sparse]"`）：

```bash
uv add "bitongue[sparse]"
```

## 第一个示例

围绕 Bitongue 的开发方式是「定义事件，实现过滤器，消费通过的事件」：

1. 定义一个**业务事件类型**（继承 `Event`，补充自己的载荷字段）；
2. 实现若干**过滤器**（满足 `Filter` Protocol，命中即返回 `True`）；
3. 用 `BitongueConfig` 与过滤器创建 `Bitongue` 编排器，`start` 后即可 `send` 与 `receive`；
4. 在 `receive()` 的消费循环里完成业务处理。

完整可运行示例（保存为 `demo.py`）：

```python
from uuid import uuid4

import anyio

from bitongue.client import Bitongue, BitongueConfig
from bitongue.flow import Event


class TextEvent(Event):
    """业务事件：身份 + 文本载荷。"""

    type: str = "text"
    text: str = ""


class EmptyTextFilter:
    """过滤器：空文本事件判定命中（返回 True 即拒绝）。"""

    async def filter(self, event: TextEvent) -> bool:
        return not event.text


async def main() -> None:
    config = BitongueConfig(
        buffer_size=16,     # 流窗口容量（有界缓冲大小）
        event_timeout=30,   # 事件在窗口内的存活秒数
    )
    client = Bitongue(config, EmptyTextFilter())
    await client.start()

    async def consume() -> None:
        async for event in client.receive():
            print(event.text.upper())  # 业务处理：转大写
            break  # 示例到此结束；真实场景可按需持续消费

    async with anyio.create_task_group() as tg:
        tg.start_soon(consume)
        # id 由业务侧生成后透传；真实场景通常用业务系统已有的标识
        await client.send(TextEvent(id=uuid4(), text="hello bitongue"))
        await client.send(TextEvent(id=uuid4(), text=""))  # 会被过滤器拒绝

    await client.close()


if __name__ == "__main__":
    anyio.run(main)
```

运行：

```bash
uv run demo.py
```

输出：

```text
HELLO BITONGUE
```

## 发生了什么

1. `client.send(...)` 把事件包成带入库时间与超时标记的条目，投入流窗口的有界缓冲；空文本事件同样入库。
2. `client.receive()` 按入库顺序逐条消费：先剔除在窗口内停留超过 `event_timeout` 的过期事件；本例中空文本事件被 `EmptyTextFilter` 判定命中（返回 `True`），静默丢弃，不产出。
3. 通过过滤的事件被 `receive()` 逐条 yield 给消费者；业务处理（转大写）在消费循环内完成。
4. 示例取到第一条即结束。

## 使用内置过滤器

除了自己实现 `Filter` Protocol，`bitongue` 还内置两个开箱即用的过滤器。
以关键词黑名单为例，只需替换过滤器集合（命中任一关键词即拒绝）：

```python
from bitongue.filter.keyword import KeywordFilter

client = Bitongue(config, KeywordFilter("spam", "违禁词"))
```

另一个内置过滤器 `SparseTextFilter` 基于 qdrant 稀疏检索做判重拦截：给定参考语料，
与语料相似的事件被拒绝、无关事件放行，适合近重复内容准入；它需要安装可选依赖组
`sparse`（见上文安装一节），并从 sparse 子包导入：

```python
from bitongue.filter.sparse import SparseTextFilter
```

两者的完整语义、配置项与边界行为（包括阈值调参直觉）
见[核心概念](concepts.md)的「内置过滤器」一节。

## 下一步

- 了解各部件的职责边界 → [核心概念](concepts.md)
- 调整缓冲、超时等行为 → [配置说明](configuration.md)
- 看清整体结构与事件生命周期 → [架构与数据流](architecture.md)
- 查阅公开对象与导入方式 → [API 参考](../api)
