# 配置说明

Bitongue 的运行行为由 `BitongueConfig` 集中描述，在创建编排器时传入：

```python
from bitongue.client import BitongueConfig

config = BitongueConfig(
    flowing_size=16,
    flowing_timeout=30,
    handle_timeout=5.0,
)
```

`BitongueConfig` 本身是 msgspec 结构体（继承 `BaseStruct`），三个字段均为必填。

## 字段一览

| 字段 | 类型 | 单位 | 语义 |
|-|-|-|-|
| `flowing_size` | `int` | 条 | 流窗口的有界缓冲容量；窗口满时 `send()` 等待，形成背压 |
| `flowing_timeout` | `int \| None` | 秒 | 消息在窗口内的存活时间；消费时剔除入库后超时的条目；`None` 表示永不过期 |
| `handle_timeout` | `float` | 秒 | 单条消息过滤与处理两段合计允许的最大耗时；超时消息被跳过（不产出结果，不中断消费） |

## 各字段的行为细节

### `flowing_size`

容量作用于 anyio 内存流的最大缓冲长度。消息从 `send()` 进入缓冲，到 `result()` 取出为止都占用一个槽位。取值建议：

- 值过小：突发流量下生产者频繁等待；
- 值过大：突发流量被全量缓存，消费侧的过期剔除压力与内存占用随之上升。

### `flowing_timeout`

存活计时从消息**入库**（`send()`）时刻开始，等待缓冲的时间也计入。过期条目在**消费侧**被剔除：不产出结果、不报错，对生产者完全透明。设为 `None` 可关闭该层超时，让消息无限期等待消费。

两层超时的分工：`flowing_timeout` 管「消息值得被处理多久」，`handle_timeout` 管「单条消息走完过滤与处理最多花多久」。

### `handle_timeout`

超时窗口覆盖单条消息的**过滤与处理两段**（过滤器链的总耗时计入预算）。以 anyio 取消作用域实现：超时会**真正取消**过滤或处理内的执行（而不仅是放弃等待），随后该消息被跳过，消费继续下一条。处理器内部的清理逻辑（`try/finally`、`async with` 等）会正常执行。

消息逐条**串行**处理：`result()` 的底层是单消费者内存流，配置不提供并发处理选项；需要更高吞吐时，按业务分片运行多个编排器实例。

## 生命周期约束

配置只在创建 `Bitongue` 时读取一次，`start()` 时用于构建内部流窗口：

- 未 `start()` 就调用 `send()` 或 `result()` 会抛出 `RuntimeError`；
- `shutdown()` 之后窗口关闭，复用同一编排器需重新 `start()`。

## 一个超时组合的例子

```python
config = BitongueConfig(
    flowing_size=64,      # 允许突发 64 条排队
    flowing_timeout=10,   # 排队超过 10 秒的消息到期作废
    handle_timeout=2.0,   # 单条处理最多 2 秒，超时跳过
)
```

该组合的含义：最坏情况下，一条消息从入库到被处理完成不会超过约 12 秒；过期或超时的消息都不会阻塞后续消息的消费。

## 过滤器配置（`SparseFilter`）

`SparseFilter` 的行为由构造参数与两个 policy 结构体描述（完整字段见
[API 参考](../api)中对应模块；此处列出调参最常触及的部分）：

| 参数 / 字段 | 默认 | 语义 |
|-|-|-|
| `filter_threshold` | `0.8` | 判重阈值：相似度超过它即拒绝；取值为 (0, 1) 开区间 |
| `normalize_scale` | `5.0` | 相似度饱和速率；越大则越低的 BM25 分就会被视为高相似（更敏感） |
| `Bm25Policy.language` | `"chinese"` | 中文走本地 `Bm25CN` 实现（零下载零联网）；其他语言走 fastembed `Bm25` |
| `Bm25Policy.model_name` | `""` | 非中文语言必填（空串视为未设置，启动时明确报错）；中文路径忽略 |
| `Bm25Policy.k` / `b` / `avg_len` | `1.2` / `0.75` / `256.0` | BM25 公式参数（词频饱和、长度归一、平均文档长度） |
| `QdrantPolicy.location` / `url` / `host` / `path` | `host="localhost"` | 连接目标，**四者互斥**（qdrant-client 校验）；内存模式用 `location=":memory:"` 且 `host=None` |
| `QdrantPolicy.port` / `grpc_port` | `6333` / `6334` | host 模式的 REST / gRPC 端口 |

阈值与 scale 的调参直觉：默认组合下「相似度 > 0.8」等价于「BM25 分 > 0.8」——
**消息与语料哪怕只有一个词元重叠也可能触发拦截**（语料越大、该词元 IDF 越低时
越难触发；小语料场景则容易）。要减少误拦：提高 `filter_threshold`（如 0.9+）或
调低 `normalize_scale`（如 2.0）；要更激进地拦截近重复则反向调整。

非中文嵌入模型首次使用时从 HuggingFace 下载，可用 `Bm25Policy.cache_dir` 或
环境变量 `FASTEMBED_CACHE_PATH` 控制缓存位置；`KeywordsFilter` 无网络行为，
无需配置。

## 过滤器配置（`NeuroFilter`）

`NeuroFilter` 的行为由 `NeuroFilterPolicy` 一个结构体描述：

| 字段 | 默认 | 语义 |
|-|-|-|
| `base_url` | 必填 | OpenAI 兼容对话端点的基地址 |
| `api_key` | 必填 | 端点密钥；序列化 policy（`to_json`）会把它一并带出，序列化结果按机密信息对待 |
| `model` | 必填 | 端点提供的模型名 |
| `rules` | 必填 | 过滤规则；字符串列表按行拼接为一段规则文本，单个字符串原样使用；清洗后为空则所有消息放行 |
| `timeout` | `10.0` | 单次模型判定的秒数上限；超时以 `TimeoutError` 抛出 |

两层超时的分工：`timeout` 管单次模型调用本身，超出即抛错；整个过滤阶段仍计入
`handle_timeout` 预算。给带 `NeuroFilter` 的管线配置时，`handle_timeout` 需要
容纳模型调用的典型延迟。

端点与模型的能力声明在 `OpenAIClientProvider` 中定制：客户端向 autogen 声明
结构化输出等能力，模型才会按约定的 JSON 结构返回判定；后端模型实际不支持时，
调用会在运行期失败——接入非标准后端时先在此处按真实能力声明。
