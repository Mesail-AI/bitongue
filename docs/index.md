# Bitongue

基于 [anyio](https://anyio.readthedocs.io/) 与 [msgspec](https://jcristharif.com/msgspec/) 的异步消息流处理库。

Bitongue 把「消息的接收、筛选、处理」拆成三个可独立演化的环节：生产者把消息投入内存流窗口，由窗口负责缓冲与存活控制；过滤器链决定哪些消息放行；处理器完成业务逻辑并产出类型化的结果。

## 特性

- **内存流窗口**：基于 anyio 内存流的有界缓冲，容量与消息存活时间可配置，
  过期消息在消费时自动剔除，详见[快速上手](guide/quickstart.md)
- **过滤器链准入**：过滤器并发执行，全部通过才放行，被拒绝的消息静默丢弃，
  语义见[核心概念](guide/concepts.md)
- **处理器扩展点**：实现一个异步 `handle(message) -> result` 方法即可接入业务，
  处理超时只影响当前消息，不阻塞后续消费
- **双层超时保护**：窗口存活超时 + 单条消息过滤与处理的合计超时，
  行为细节见[配置说明](guide/configuration.md)
- **类型安全**：消息与结果均为 msgspec 结构体，自带字典 / JSON 序列化，
  泛型参数贯穿发送到结果的全流程
- **极简依赖**：核心仅依赖 anyio、msgspec 等少量包；`SparseTextualFilter` 与
  `NeuroTextualFilter` 所需的领域依赖分别随可选依赖组 `sparse`、`neuro` 按需安装

要求 Python ≥ 3.12。

```{toctree}
:hidden:

guide/quickstart
guide/concepts
guide/architecture
guide/configuration
api
```
