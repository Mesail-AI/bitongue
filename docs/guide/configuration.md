# 配置说明

Bitongue 的运行行为由 `BitongueConfig` 集中描述，在创建编排器时传入：

```python
from bitongue.client import BitongueConfig

config = BitongueConfig(
    buffer_size=16,
    event_timeout=30,
)
```

`BitongueConfig` 本身是 msgspec 结构体（继承 `BaseStruct`），`buffer_size` 必填，
`event_timeout` 可选。

## 字段一览

| 字段 | 类型 | 单位 | 语义 |
|-|-|-|-|
| `buffer_size` | `int` | 条 | 流窗口的有界缓冲容量；窗口满时 `send()` 等待，形成背压 |
| `event_timeout` | `float \| None` | 秒 | 事件在窗口内的存活时间；消费时剔除入库后超时的条目；`None`（默认）表示永不过期 |

## 各字段的行为细节

### `buffer_size`

容量作用于 anyio 内存流的最大缓冲长度。事件从 `send()` 进入缓冲，到 `receive()` 取出为止都占用一个槽位。取值建议：

- 值过小：突发流量下生产者频繁等待；
- 值过大：突发流量被全量缓存，消费侧的过期剔除压力与内存占用随之上升。

### `event_timeout`

存活计时从事件**入库**（`send()`）时刻开始，等待缓冲的时间也计入。过期条目在**消费侧**被剔除：不产出、不报错，对生产者完全透明。设为 `None` 可关闭该层超时，让事件无限期等待消费。

## 生命周期约束

配置只在创建 `Bitongue` 时读取一次，`start()` 时用于构建内部流窗口：

- 未 `start()` 就调用 `send()` 或 `receive()` 会抛出 `RuntimeError`；
- `close()` 之后窗口关闭，复用同一编排器需重新 `start()`。

## 一个超时组合的例子

```python
config = BitongueConfig(
    buffer_size=64,     # 允许突发 64 条排队
    event_timeout=10,   # 排队超过 10 秒的事件到期作废
)
```

该组合的含义：一条事件从入库起算最多存活 10 秒，过期即作废；过期事件不会阻塞后续事件的消费。

## 过滤器配置（`SparseTextFilter`）

`SparseTextFilter` 的行为由构造参数与两个 policy 结构体描述（完整字段见
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
**事件与语料哪怕只有一个词元重叠也可能触发拦截**（语料越大、该词元 IDF 越低时
越难触发；小语料场景则容易）。要减少误拦：提高 `filter_threshold`（如 0.9+）或
调低 `normalize_scale`（如 2.0）；要更激进地拦截近重复则反向调整。

非中文嵌入模型首次使用时从 HuggingFace 下载，可用 `Bm25Policy.cache_dir` 或
环境变量 `FASTEMBED_CACHE_PATH` 控制缓存位置；`KeywordFilter` 无网络行为，
无需配置。
