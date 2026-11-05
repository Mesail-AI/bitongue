# Bitongue

基于 [anyio](https://anyio.readthedocs.io/) 与 [msgspec](https://jcristharif.com/msgspec/) 的异步事件流处理库。

Bitongue 把「事件的接收、筛选、消费」拆成三个可独立演化的环节：生产者把事件投入内存流窗口，由窗口负责缓冲与存活控制；过滤器链决定哪些事件放行；业务逻辑留在消费侧自由实现。

## 特性

- **内存流窗口**：基于 anyio 内存流的有界缓冲，容量与事件存活时间可配置，
  过期事件在消费时自动剔除，详见[快速上手](guide/quickstart.md)
- **过滤器链准入**：过滤器并发执行、不短路，任一命中即拒绝，被拒绝的事件静默丢弃，
  语义见[核心概念](guide/concepts.md)
- **消费者扩展点**：`receive()` 按序产出通过过滤的事件，业务处理在消费侧完成，
  事件流转机制与业务处理解耦
- **存活超时保护**：`event_timeout` 控制事件在窗口内的存活时间，过期事件在消费侧
  被静默跳过，行为细节见[配置说明](guide/configuration.md)
- **类型安全**：事件均为 msgspec 结构体，自带字典 / JSON 序列化，
  泛型参数贯穿发送到消费的全流程
- **极简依赖**：核心仅依赖 anyio、msgspec 等少量包；`SparseTextFilter` 所需的
  领域依赖随可选依赖组 `sparse` 按需安装

要求 Python ≥ 3.12。

```{toctree}
:hidden:

guide/quickstart
guide/concepts
guide/architecture
guide/configuration
api
```
