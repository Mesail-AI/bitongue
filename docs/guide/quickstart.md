# 快速上手

本页带你从安装到跑通第一个完整示例：发送两条消息，经过过滤器与处理器，取出处理结果。

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

内置的 `SparseTextualFilter` 依赖 fastembed、jieba 与 qdrant-client，随可选依赖组
`sparse` 发布，按需安装（pip 用户写 `pip install "bitongue[sparse]"`）：

```bash
uv add "bitongue[sparse]"
```

内置的 `NeuroTextualFilter` 依赖 autogen 相关包，随可选依赖组 `neuro` 发布，按需安装
（pip 用户写 `pip install "bitongue[neuro]"`）：

```bash
uv add "bitongue[neuro]"
```

## 第一个示例

围绕 Bitongue 的开发方式是「实现三个部件，交给编排器」：

1. 定义一个**结果类型**（继承 `BaseResult`）；
2. 实现一个**处理器**（继承 `BaseHandler`，完成业务逻辑）；
3. 可选地实现若干**过滤器**（继承 `BaseFilter`，决定哪些消息放行）；
4. 用 `BitongueConfig` 与上述部件创建 `Bitongue` 编排器，`start` 后即可 `send` 与 `result`。

完整可运行示例（保存为 `demo.py`）：

```python
from uuid import uuid4

import anyio

from bitongue.client import Bitongue, BitongueConfig
from bitongue.filter import BaseFilter
from bitongue.flow import TextualMessage
from bitongue.handler import BaseHandler, BaseResult


class UpperResult(BaseResult):
    """处理结果：大写文本。"""

    text: str


class NonEmptyFilter(BaseFilter[TextualMessage]):
    """过滤器：丢弃空文本消息。"""

    async def filter(self, message: TextualMessage) -> bool:
        return bool(message.text)


class UpperHandler(BaseHandler[TextualMessage, UpperResult]):
    """处理器：把文本转成大写。"""

    async def handle(self, message: TextualMessage) -> UpperResult:
        return UpperResult(id=message.id, text=(message.text or "").upper())


async def main() -> None:
    config = BitongueConfig(
        flowing_size=16,       # 流窗口容量（有界缓冲大小）
        flowing_timeout=30,    # 消息在窗口内的存活秒数
        handle_timeout=5.0,    # 单条消息过滤+处理的超时秒数
    )
    client = Bitongue(config, handler=UpperHandler(), filters=[NonEmptyFilter()])

    await client.start()
    # id 由业务侧生成后透传；真实场景通常用业务系统已有的标识
    await client.send(TextualMessage(id=uuid4(), text="hello bitongue"))
    await client.send(TextualMessage(id=uuid4(), text=""))  # 会被过滤器丢弃

    async for result in client.result():
        print(result.text)  # HELLO BITONGUE
        break  # 示例到此结束；真实场景可按需持续消费

    await client.shutdown()


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

1. `client.send(...)` 把消息包成带入库时间与超时标记的条目，投入流窗口的有界缓冲；空文本消息同样入库。
2. `client.result()` 按入库顺序逐条消费：先剔除在窗口内停留超过 `flowing_timeout` 的过期消息；本例中空文本消息被 `NonEmptyFilter` 拒绝，静默丢弃，不产出结果。
3. 通过过滤的消息交给 `UpperHandler.handle` 处理，过滤与处理两段合计须在 `handle_timeout` 秒内完成，产出 `UpperResult`（结果镜像了来源消息的 `id`）。
4. `result()` 逐条 yield 处理结果；示例取到第一条即结束。

## 使用内置过滤器

除了自己实现 `BaseFilter`，`bitongue.filter` 还内置三个开箱即用的过滤器。
以关键词黑名单为例，只需替换过滤器集合：

```python
from bitongue.filter import KeywordsFilter

client = Bitongue(
    config,
    handler=UpperHandler(),
    filters=[KeywordsFilter(["spam", "违禁词"])],  # 命中任一关键词即拒绝
)
```

另一个内置过滤器 `SparseTextualFilter` 基于 qdrant 稀疏检索做判重拦截：给定参考语料，
与语料相似的消息被拒绝、无关消息放行，适合近重复内容准入；它需要安装可选依赖组
`sparse`（见上文安装一节），并从 sparse 子包导入：

```python
from bitongue.filter.sparse import SparseTextualFilter
```

第三个内置过滤器 `NeuroTextualFilter` 把自然语言规则与消息文本一起交给大语言模型
裁决，适合关键词难以穷举的语义类准入（例如「拒绝带攻击性的内容」）。它需要
安装可选依赖组 `neuro`（见上文安装一节），从独立子包导入，并且必须先启动——
交给编排器时由 `client.start()` 自动完成：

```python
from bitongue.filter.neuro import NeuroTextualFilter, NeuroFilterPolicy

neuro = NeuroTextualFilter(
    NeuroFilterPolicy(
        base_url="https://api.example.com/v1",
        api_key="<your-api-key>",
        model="<model-name>",
        rules="Reject messages containing abuse or profanity.",
    ),
)
client = Bitongue(config, handler=UpperHandler(), filters=[neuro])
```

三者的完整语义、配置项与边界行为（包括阈值调参直觉）
见[核心概念](concepts.md)的「内置过滤器」一节。

## 下一步

- 了解各部件的职责边界 → [核心概念](concepts.md)
- 调整缓冲、超时等行为 → [配置说明](configuration.md)
- 看清整体结构与消息生命周期 → [架构与数据流](architecture.md)
- 查阅公开对象与导入方式 → [API 参考](../api)
