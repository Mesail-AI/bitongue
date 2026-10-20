# 架构与数据流

本页从静态结构与运行时两条视角说明 Bitongue 的组织方式。

## 子包结构

库分为五个子包，依赖方向自底向上，`base` 不依赖任何内部包，`client` 编排其余全部：

```{mermaid}
graph BT
    base["base<br/>BaseStruct · 异常体系"]
    flow["flow<br/>Flowing · BaseMessage · MessageEntry"]
    filter["filter<br/>BaseFilter · KeywordsFilter · SparseFilter · NeuroFilter"]
    handler["handler<br/>BaseHandler · BaseResult"]
    client["client<br/>Bitongue · BitongueConfig"]

    flow --> base
    filter --> flow
    handler --> base
    client --> flow
    client --> handler
    client --> filter
```

| 子包 | 职责 | 主要公开对象 |
|-|-|-|
| `base` | 数据结构地基与异常根 | `BaseStruct`、`BitongueError` 及其子类 |
| `flow` | 内存流窗口：缓冲、计时、过期剔除 | `Flowing`、`BaseMessage`、`MessageEntry` |
| `filter` | 消息准入门：Protocol 与内置过滤器 | `BaseFilter`、`KeywordsFilter`、`SparseFilter`、`NeuroFilter` |
| `handler` | 业务处理扩展点（Protocol）与结果基类 | `BaseHandler`、`BaseResult` |
| `client` | 生命周期编排与生产/消费两端 | `Bitongue`、`BitongueConfig` |

## 一条消息的生命周期

从发送到产出结果，一条消息经过以下环节：

```{mermaid}
sequenceDiagram
    participant P as 生产者
    participant B as Bitongue
    participant F as Flowing 窗口
    participant C as 消费者 result()
    participant FC as 过滤器链
    participant H as 处理器

    P->>B: send(message)
    B->>F: draw() 包装为 MessageEntry（记录 enter_time 与 timeout）
    F->>F: 有界缓冲（窗口满时发送方等待）
    C->>F: flow() 按序取出
    F-->>C: 丢弃入库后超过存活时间的过期条目
    C->>FC: 任务组并发调用 filter(message)
    FC-->>C: 全部通过？否则静默丢弃该消息
    C->>H: handle(message)（限 handle_timeout 秒）
    alt 处理成功
        H-->>C: 返回结果 R
        C-->>P: yield 结果
    else 处理器抛出异常
        H--x C: 异常（包装为 MessageHandleError）
        C-->>P: yield MessageHandleFailure 信封（流继续）
    end
```

结合代码的几个关键点：

- **计时从入库开始**：`send()` 时刻即记下 `enter_time`，等待缓冲的时间计入存活期。
- **过期剔除在消费侧**：取出时才发现过期，直接跳过，不产出、不报错。
- **过滤链并发且不短路**：链上过滤器在同一任务组内并发启动、全部执行；任何一个拒绝即丢弃。
- **处理超时局部化**：`handle_timeout` 覆盖单条消息的过滤与处理两段；超时只影响该条消息（被跳过），不中断生成器。
- **处理异常转为失败信封**：处理器抛出的异常被包装为 `MessageHandleError`，转为 `MessageHandleFailure` 信封（携带来源消息与错误文本）按序产出——单条消息的失败不终止结果流，消费者以 `isinstance` 区分结果与信封。
- **过滤器异常汇总上抛**：过滤器抛出的异常由编排器等全部过滤器执行完毕后合并为一个 `ExceptionGroup` 上抛，终止结果流——准入是管道级设施，其失效意味着后续任何消息都无法判定；并发的兄弟异常互不吞没，响亮失败优于带内上报。
- **过滤器生命周期可上收**：实现 `FilterLifecycle`（`start()`/`aclose()`）的过滤器由 `Bitongue.start()/shutdown()` 统一启动与关闭——如 `SparseFilter` 的建集合与连接管理、`NeuroFilter` 的代理与模型客户端构建，其初始化成本因此落在编排器启动阶段而非首条消息。

## 并发模型

- 全部异步原语来自 anyio，可在 asyncio 与 trio 之上运行；
- 流窗口是有界内存流：容量满时 `send()` 等待（背压），缓冲为空时 `result()` 等待；
- `result()` 的底层是单消费者流，同一时刻应由一个任务迭代；
- 过滤链借助 aioresult 在任务组内并发执行各过滤器，全部完成后汇总裁决；任一过滤器抛出的异常在汇总时合并为一个 `ExceptionGroup` 原样上抛；
- `handle_timeout` 用 anyio 取消作用域实现，超时会真正取消过滤与处理内的执行，而不是仅仅放弃等待。

## 设计取舍

- **msgspec 而非 dataclass/pydantic**：消息与结果需要高频序列化，`BaseStruct` 统一提供不可变默认、排序键 JSON 与类型转换。
- **Protocol 而非继承**：过滤器与处理器只要求「有一个满足签名的方法」，业务类不必继承任何框架基类。
- **编排器集中生命周期**：`Flowing` 可以独立使用，但 `start/shutdown`、超时配置与过滤/处理的编排统一收敛在 `Bitongue`，避免使用者拼装出错。

各配置项的具体语义见[配置说明](configuration.md)。
