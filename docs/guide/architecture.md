# 架构与数据流

本页从静态结构与运行时两条视角说明 Bitongue 的组织方式。

## 子包结构

库分为四个子包，依赖方向自底向上，`base` 不依赖任何内部包，`client` 编排其余全部：

```{mermaid}
graph BT
    base["base<br/>BaseStruct"]
    flow["flow<br/>Flowing · Event · EventEntry"]
    filter["filter<br/>Filter · KeywordFilter · SparseTextFilter"]
    client["client<br/>Bitongue · BitongueConfig"]

    flow --> base
    filter --> flow
    client --> flow
    client --> filter
```

| 子包 | 职责 | 主要公开对象 |
|-|-|-|
| `base` | 数据结构地基 | `BaseStruct` |
| `flow` | 内存流窗口：缓冲、计时、过期剔除 | `Flowing`、`Event`、`TextEvent`、`EventEntry` |
| `filter` | 事件准入门：Protocol 与内置过滤器 | `Filter`、`FilterLifecycle`、`Normalizer`；子包 `filter.keyword`（`KeywordFilter`）、`filter.sparse`（`SparseTextFilter` 等） |
| `client` | 生命周期编排与生产/消费两端 | `Bitongue`、`BitongueConfig` |

## 一条事件的生命周期

从发送到被消费，一条事件经过以下环节：

```{mermaid}
sequenceDiagram
    participant P as 生产者
    participant B as Bitongue
    participant F as Flowing 窗口
    participant C as 消费者 receive()
    participant FC as 过滤器链

    P->>B: send(event)
    B->>F: send() 包装为 EventEntry（记录 enter_time 与 timeout）
    F->>F: 有界缓冲（窗口满时发送方等待）
    C->>F: receive() 按序取出
    F-->>C: 丢弃入库后超过存活时间的过期条目
    C->>FC: 任务组并发调用 filter(event)
    FC-->>C: 全部放行？任一命中即静默丢弃该事件
    C-->>P: yield 通过过滤的事件
```

结合代码的几个关键点：

- **计时从入库开始**：`send()` 时刻即记下 `enter_time`，等待缓冲的时间计入存活期。
- **过期剔除在消费侧**：取出时才发现过期，直接跳过，不产出、不报错。
- **过滤链并发且不短路**：链上过滤器在同一任务组内并发启动、全部执行；任何一个命中即丢弃该事件。
- **过滤器异常汇总上抛**：过滤器抛出的异常由编排器等全部过滤器执行完毕后合并为一个 `ExceptionGroup` 上抛，终止事件流——准入是管道级设施，其失效意味着后续任何事件都无法判定；并发的兄弟异常互不吞没，响亮失败优于带内上报。
- **过滤器生命周期可上收**：实现 `FilterLifecycle`（`start()`/`close()`）的过滤器由 `Bitongue.start()/close()` 统一启动与关闭（关闭按注册的逆序进行）——如 `SparseTextFilter` 的建集合与连接管理，其初始化成本因此落在编排器启动阶段而非首条事件。

## 并发模型

- 全部异步原语来自 anyio，可在 asyncio 与 trio 之上运行；
- 流窗口是有界内存流：容量满时 `send()` 等待（背压），缓冲为空时 `receive()` 等待；
- `receive()` 的底层是单消费者流，同一时刻应由一个任务迭代；事件逐条串行消费，不支持并发消费；
- 过滤链借助 aioresult 在任务组内并发执行各过滤器，全部完成后汇总裁决；任一过滤器抛出的异常在汇总时合并为一个 `ExceptionGroup` 原样上抛。

## 设计取舍

- **msgspec 而非 dataclass/pydantic**：事件需要高频序列化，`BaseStruct` 统一提供不可变默认、排序键 JSON 与类型转换。
- **Protocol 而非继承**：过滤器只要求「有一个满足签名的方法」，业务类不必继承任何框架基类；事件则继承 `Event` 以获得身份与序列化能力。
- **业务留在消费侧**：库只负责流转（缓冲、存活、过滤），处理逻辑由消费者在 `receive()` 循环内自由实现，流转与业务互不牵制。
- **编排器集中生命周期**：`Flowing` 可以独立使用，但 `start/close`、超时配置与过滤的编排统一收敛在 `Bitongue`，避免使用者拼装出错。

各配置项的具体语义见[配置说明](configuration.md)。
