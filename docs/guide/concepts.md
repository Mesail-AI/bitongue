# 核心概念

Bitongue 把消息处理拆成五个各自独立、职责单一的概念。本页逐一说明它们的职责、协作方式与边界行为。

## 消息与条目（`BaseMessage` / `TextualMessage` / `MessageEntry`）

`BaseMessage` 是消息的基类（同时是所有数据结构共用的 `BaseStruct` msgspec 结构体的子类），只定义消息的最小信封：`id`（调用方传入的唯一标识——bitongue 不代为生成，业务侧已有的 ID 直接透传即可）。文本消息 `TextualMessage` 是默认的具体消息类型，在其上补充两个字段：`type`（固定为 `"text"` 的载荷种类标记）与 `text`（可选文本内容，为 `None` 表示消息不带文本负载）。它们继承的 `BaseStruct` 提供 `to_dict` / `from_dict` / `to_json` / `from_json` 序列化能力，因此每条消息天然可以在字典、JSON 与对象之间互转；其他载荷形态的消息可以继承 `BaseMessage` 自行扩展。

消息被发送时并不会直接进入缓冲，而是先被包装成 `MessageEntry`：除消息本体之外，还记录 `enter_time`（入库时刻）与 `timeout`（存活秒数），供流窗口做过期剔除。

## 流窗口（`Flowing`）

`Flowing[T]` 是内存中的消息流窗口，是有界缓冲的持有者：

- **容量**：`size` 决定缓冲上限（基于 anyio 内存流实现）；窗口满时发送方等待，形成天然背压。
- **存活时间**：`timeout` 是消息在窗口内的存活秒数；不设置则永不过期。
- **生命周期**：`start()` 创建缓冲并开始运行，`shutdown()` 关闭缓冲；未运行时调用 `draw()`（投递）或 `flow()`（消费）会抛出 `FlowingNotInitializedError`。
- **过期剔除发生在消费侧**：`flow()` 逐条产出未过期消息，入库后超过存活秒数的条目被直接跳过，不产出、不报错。

一般情况下不直接操作 `Flowing`，而是通过编排器 `Bitongue` 使用它。

## 过滤器（`BaseFilter`）

`BaseFilter[T]` 是一个 Protocol（结构化接口），实现它只需要一个异步方法：

```python
async def filter(self, message: T) -> bool:
```

返回 `True` 表示放行，`False` 表示拒绝。要点：

- 过滤器链中**全部过滤器都返回 `True`** 消息才会进入处理；任何一个返回 `False`，该消息被静默丢弃。
- 过滤器**并发执行**：链上过滤器以任务组同时启动，互不等待、全部执行（不做短路）。因此过滤器应当是只读的、无副作用的判断，也不应假设彼此的先后顺序。
- 不配置任何过滤器时，全部消息直接放行。

## 内置过滤器

除自定义 Protocol 实现外，`bitongue.filter` 还提供三个开箱即用的内置过滤器。
三者遵循同一个 `True`/`False` 契约，但取向不同：`KeywordsFilter` 是**关键词黑名单**
（命中即拒），`SparseTextualFilter` 是**判重拦截**（与语料相似即拒），`NeuroTextualFilter` 是
**模型判定**（按自然语言规则交给大语言模型裁决）。

### `KeywordsFilter` — 关键词黑名单

基于 Aho-Corasick 自动机的多关键词匹配：

- **命中即拒**：文本中出现任一关键词 → 拒绝；未命中 → 放行；
- **归一化匹配**：关键词与消息文本都先经 `Normalizer` 归一化（casefold、
  非词字符折叠为空格、NFKC），大小写与标点差异不影响命中；
- **子串语义**：关键词作为文本片段出现即算命中（Aho-Corasick 匹配子串）；
- **边界行为**：无文本载荷的消息放行（无可匹配内容）；空关键词列表拦截不到任何
  消息，全部放行；
- 词表可来自列表或 `load_from_file`（逐行读取、UTF-8、忽略空行），两条构造路径
  行为一致；自动机在构造期完成构建，`filter` 是纯查询，无首次调用开销。

### `SparseTextualFilter` — 基于稀疏检索的判重拦截

把参考语料嵌入 qdrant 稀疏集合（BM25 词频权重 + IDF 修正），每条消息作为二值
查询向量检索语料：

- **相似即拒**：消息与语料的相似度超过 `filter_threshold`（默认 0.8）→ 拒绝；
  与语料无关 → 放行；无文本载荷 → 放行；
- **相似度映射**：`similarity = scale·score / (1 + scale·score)`（`normalize_scale`
  默认 5），随 BM25 分单调递增，score 为 0（零重叠）自然映射为 0。**阈值语义偏
  敏感：默认参数下哪怕只有一个词元与语料重叠，BM25 分也可能越过 0.8 触发拦截**；
  要求更宽松时提高 `filter_threshold`（如 0.9+）或调低 `normalize_scale`（如 2.0）；
- **语料去重播种**：每个语料字符串按其文本的 UUID5 寻址，重复播种覆盖旧点而非
  堆积副本；清洗后无有效词元的语料文档自动跳过；
- **生命周期**：初始化包含建模与全量语料 upsert，开销较大，因此实现了
  `FilterLifecycle`（`start()` / `aclose()`）：交给 `Bitongue` 编排器时由
  `client.start()` 统一初始化、`shutdown()` 释放连接；独立使用时首次 `filter`
  触发懒初始化（锁保护，一次性成本计入调用方的超时预算）；
- **配置**：`Bm25Policy`（`language="chinese"` 走本地 `Bm25CN` 实现，零下载
  零联网；其他语言走 fastembed `Bm25`，须提供 `model_name` 且首次使用下载模型）
  与 `QdrantPolicy`（连接设置，字段镜像 qdrant-client 构造签名；`location` /
  `url` / `host` / `path` 四者互斥，内存模式用 `location=":memory:"` 且
  `host=None`）；
- **语料分块由调用者负责**：每个字符串就是一个可检索单元。

### `NeuroTextualFilter` — 基于大语言模型的规则判定

把过滤规则与消息文本一起交给 OpenAI 兼容的对话端点（内部经由
[autogen](https://microsoft.github.io/autogen/) 的 `AssistantAgent`），由模型
按规则给出结构化判定：

- **判定即拒**：模型判定 `filtered=True` → 拒绝；判定放行 → 放行。规则支持
  单个字符串或字符串列表（列表按行拼接为一段规则文本）；
- **无模型调用即放行**：无文本载荷、或规则清洗后为空的消息直接放行——这两类
  边界不发起任何模型调用；
- **模型路径上的失败一律抛出**：响应不符合约定判定结构（`ValueError`）、后端
  错误、或单次调用超过 `timeout`（`TimeoutError`）都原样抛出，过滤器不做
  吞没；交给编排器时，超时由 `handle_timeout` 的既有契约接住（该消息被静默
  跳过），其余错误属于管道级失败，随过滤链汇总为 `ExceptionGroup` 上抛并
  终止结果流；
- **消息间隔离**：每次判定使用独立的对话上下文，判定完成后立即清空——前一条
  消息的文本不会进入后一条的请求；单实例不可并发调用（编排器的单消费者管线
  已保证串行）；
- **生命周期**：构造只保存配置、不发起网络请求；`start()` 构建代理与模型
  客户端，未启动就调用 `filter` 抛 `RuntimeError`。与 `SparseTextualFilter` 的懒
  初始化不同，`NeuroTextualFilter` 必须先启动——交给编排器时由 `client.start()`
  统一处理；
- **配置**：`NeuroFilterPolicy`（端点 `base_url`、`api_key`、模型 `model`、
  规则 `rules`、单次判定超时 `timeout`）；端点与模型能力声明的定制点是
  `OpenAIClientProvider`。注意序列化 policy（`to_json`）会把 `api_key`
  一并带出，序列化结果按机密信息对待；
- **依赖**：随可选依赖组 `neuro` 发布，从独立子包导入：

```python
from bitongue.filter.neuro import NeuroTextualFilter, NeuroFilterPolicy
```

判定结果类型是 pydantic 模型——这是 autogen 结构化输出的强制要求，也是整个
库对「数据结构一律 msgspec」约定的唯一例外。

支撑工具 `Normalizer`（文本归一化）可独立使用；`JiebaTokenizer`（中文搜索引擎
模式分词）随 `SparseTextualFilter` 位于 sparse 子包（`bitongue.filter.sparse`），
使用需安装 `sparse` 可选依赖组。

## 处理器与结果（`BaseHandler` / `BaseResult` / `MessageHandleFailure`）

`BaseHandler[T, R]` 是业务处理的扩展点，同样是 Protocol，实现一个异步方法：

```python
async def handle(self, message: T) -> R:
```

`R` 必须是 `BaseResult` 的子类 —— 处理结果与消息一样是 msgspec 结构体，具备序列化能力；基类自带 `id` 字段（与 `BaseMessage.id` 同一约定：由调用方传入的业务侧标识，惯例上镜像来源消息的 `id`），子类声明处理器产出的其余字段。把结果类型作为泛型参数显式声明（`BaseHandler[TextualMessage, UpperResult]`），可以从发送到取结果的整个链路都获得类型检查。

失败按故障的作用域分级。处理器抛出的异常是消息级故障：被包装成 `MessageHandleError` 后转为 `MessageHandleFailure` 信封（携带来源消息与错误文本）按序产出，结果流继续消费后续消息——`result()` 的产出类型因此是 `R | MessageHandleFailure`，消费者用 `isinstance` 区分正常结果与失败信封。单条消息在过滤与处理两段的总耗时超过配置的 `handle_timeout`，则该条消息被静默跳过（不产出结果，也不中断后续消费）。过滤器抛出的异常是管道级故障：编排器等全部过滤器执行完毕后，把所有异常汇总为一个 `ExceptionGroup` 上抛并终止结果流——准入机制失效后，后续任何消息都无法判定；并发的兄弟异常互不吞没。

## 编排器（`Bitongue` / `BitongueConfig`）

`Bitongue[T, R]` 把上述部件组装成一条完整流水线：

- **构造**：传入 `BitongueConfig` 与处理器（必选）、过滤器集合（可选）；
- **生命周期**：`start()` 内部创建并启动流窗口；`shutdown()` 反向关闭；两者都是幂等的——对运行中的客户端重复 `start()`、对已停止的客户端 `shutdown()` 均不做任何事；`running` 属性反映当前是否处于运行态；
- **生产侧**：`send(message)` 投递消息，内部完成条目包装与计时；
- **消费侧**：`result()` 是异步生成器，按序执行「过期剔除 → 过滤链 → 处理器」（过滤链内的过滤器并发执行，`handle_timeout` 覆盖过滤与处理两段），逐条产出结果。

注意两个边界行为：未 `start()` 就调用 `send()` 或 `result()` 会抛出 `RuntimeError`；`result()` 同一时刻只应被一个消费者迭代（底层缓冲是单消费者内存流）。

配置项的完整语义见[配置说明](configuration.md)；整条链路的结构视图见[架构与数据流](architecture.md)。
