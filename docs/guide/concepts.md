# 核心概念

Bitongue 把事件流转拆成四个各自独立、职责单一的概念。本页逐一说明它们的职责、协作方式与边界行为。

## 事件与条目（`Event` / `TextEvent` / `EventEntry`）

`Event` 是事件的基类（同时是所有数据结构共用的 `BaseStruct` msgspec 结构体的子类），只定义事件的最小信封：`id`（调用方传入的唯一标识——bitongue 不代为生成，业务侧已有的 ID 直接透传即可）。业务事件继承 `Event` 并补充自己的载荷字段，例如文本载荷可声明 `type`（载荷种类标记）与 `text` 字段。作为纯载荷形状的参照，`TextEvent` 定义了文本事件的结构（`type` 固定为 `"text"`、`text` 文本内容），内置过滤器都以它为泛型约束；它自身不带 `id`。事件继承的 `BaseStruct` 提供 `to_dict` / `from_dict` / `to_json` / `from_json` 序列化能力，因此每个事件天然可以在字典、JSON 与对象之间互转。

事件被发送时并不会直接进入缓冲，而是先被包装成 `EventEntry`：除事件本体之外，还记录 `enter_time`（入库时刻）与 `timeout`（存活秒数），供流窗口做过期剔除。

## 流窗口（`Flowing`）

`Flowing[T]` 是内存中的事件流窗口，是有界缓冲的持有者：

- **容量**：`buffer_size` 决定缓冲上限（基于 anyio 内存流实现）；窗口满时发送方等待，形成天然背压。
- **存活时间**：`timeout` 是事件在窗口内的存活秒数；不设置则永不过期。
- **生命周期**：`start()` 创建缓冲并开始运行，`close()` 关闭缓冲；未运行时调用 `send()`（投递）或 `receive()`（消费）会抛出 `RuntimeError`。两者均幂等。
- **过期剔除发生在消费侧**：`receive()` 逐条产出未过期事件，入库后超过存活秒数的条目被直接跳过，不产出、不报错。

一般情况下不直接操作 `Flowing`，而是通过编排器 `Bitongue` 使用它。

## 过滤器（`Filter`）

`Filter[T]` 是一个 Protocol（结构化接口），实现它只需要一个异步方法：

```python
async def filter(self, event: T) -> bool:
```

返回 `True` 表示命中拒绝，`False` 表示放行。要点：

- 过滤器链中**任何一个过滤器返回 `True`**，该事件就被静默丢弃；全部返回 `False` 才会产出给消费者。
- 过滤器**并发执行且不短路**：链上过滤器以任务组同时启动，互不等待、全部执行——每个过滤器都会看到每个事件。因此过滤器应当是只读的、无副作用的判断，也不应假设彼此的先后顺序。
- 不配置任何过滤器时，全部事件直接放行。
- 过滤器抛出的异常是管道级故障：编排器等全部过滤器执行完毕后，把所有异常汇总为一个 `ExceptionGroup` 上抛并终止事件流——准入机制失效后，后续任何事件都无法判定；并发的兄弟异常互不吞没。

## 内置过滤器

除自定义 Protocol 实现外，`bitongue` 还提供两个开箱即用的内置过滤器。
两者遵循同一个 `True`/`False` 契约，但取向不同：`KeywordFilter` 是**关键词黑名单**
（命中即拒），`SparseTextFilter` 是**判重拦截**（与语料相似即拒）。

### `KeywordFilter` — 关键词黑名单

基于 Aho-Corasick 自动机的多关键词匹配，位于 `bitongue.filter.keyword` 子包：

- **命中即拒**：文本中出现任一关键词 → 拒绝（返回 `True`）；未命中 → 放行；
- **归一化匹配**：关键词与事件文本都先经 `Normalizer` 归一化（casefold、
  非词字符折叠为空格、NFKC），大小写与标点差异不影响命中；
- **子串语义**：关键词作为文本片段出现即算命中（Aho-Corasick 匹配子串）；
- **边界行为**：无文本载荷的事件放行（无可匹配内容）；空关键词列表拦截不到任何
  事件，全部放行；
- 词表可来自变参列表或 `load_file`（逐行读取、UTF-8、忽略空行），两条构造路径
  行为一致；自动机在构造期完成构建，`filter` 是纯查询，无首次调用开销。

```python
from bitongue.filter.keyword import KeywordFilter
```

### `SparseTextFilter` — 基于稀疏检索的判重拦截

把参考语料嵌入 qdrant 稀疏集合（BM25 词频权重 + IDF 修正），每个事件作为二值
查询向量检索语料，位于 `bitongue.filter.sparse` 子包：

- **相似即拒**：事件与语料的相似度超过 `filter_threshold`（默认 0.8）→ 拒绝
  （返回 `True`）；与语料无关 → 放行；无文本载荷 → 放行；
- **相似度映射**：`similarity = scale·score / (1 + scale·score)`（`normalize_scale`
  默认 5），随 BM25 分单调递增，score 为 0（零重叠）自然映射为 0。**阈值语义偏
  敏感：默认参数下哪怕只有一个词元与语料重叠，BM25 分也可能越过 0.8 触发拦截**；
  要求更宽松时提高 `filter_threshold`（如 0.9+）或调低 `normalize_scale`（如 2.0）；
- **语料去重播种**：每个语料字符串按其文本的 UUID5 寻址，重复播种覆盖旧点而非
  堆积副本；清洗后无有效词元的语料文档自动跳过；语料在构造时物化，传入生成器也安全；
- **生命周期**：初始化包含建模与全量语料 upsert，开销较大，因此实现了
  `FilterLifecycle`（`start()` / `close()`）：交给 `Bitongue` 编排器时由
  `client.start()` 统一初始化、`close()` 释放连接；独立使用时首次 `filter`
  触发懒初始化（锁保护，一次性成本计入调用方的超时预算）；
- **配置**：`Bm25Policy`（`language="chinese"` 走本地 `Bm25CN` 实现，零下载
  零联网；其他语言走 fastembed `Bm25`，须提供 `model_name` 且首次使用下载模型）
  与 `QdrantPolicy`（连接设置，字段镜像 qdrant-client 构造签名；`location` /
  `url` / `host` / `path` 四者互斥，内存模式用 `location=":memory:"` 且
  `host=None`）；
- **语料分块由调用者负责**：每个字符串就是一个可检索单元；
- **依赖**：随可选依赖组 `sparse` 发布，从 sparse 子包导入：

```python
from bitongue.filter.sparse import SparseTextFilter
```

支撑工具 `Normalizer`（文本归一化）可从 `bitongue.filter` 独立导入；
`JiebaTokenizer`（中文搜索引擎模式分词）随 `SparseTextFilter` 位于 sparse 子包
（`bitongue.filter.sparse`），使用需安装 `sparse` 可选依赖组。

## 消费者扩展点

Bitongue 不规定业务如何处理事件：`receive()` 按序产出通过过滤的事件，业务逻辑在
消费循环内自由实现——转写、入库、转发、调用模型皆可。事件流转机制（缓冲、存活控制、
过滤）与业务处理因此完全解耦：更换业务逻辑不影响流转配置，反之亦然。

失败语义同样围绕流转而非业务：过滤链是准入设施，其异常汇总为一个 `ExceptionGroup`
上抛并终止事件流（见「过滤器」一节）；业务侧的异常如何处理由消费者自行决定，
库不做包装与转发。

## 编排器（`Bitongue` / `BitongueConfig`）

`Bitongue[T]` 把上述部件组装成一条完整流水线：

- **构造**：传入 `BitongueConfig` 与若干过滤器（可选，变参传入）；
- **生命周期**：`start()` 内部创建并启动流窗口、逐个启动实现了 `FilterLifecycle`
  的过滤器；`close()` **逆序**关闭这类过滤器并关闭窗口；两者都是幂等的——对运行中的
  客户端重复 `start()`、对已停止的客户端 `close()` 均不做任何事；`running` 属性反映
  当前是否处于运行态；
- **生产侧**：`send(event)` 投递事件，内部完成条目包装与计时；
- **消费侧**：`receive()` 是异步生成器，按序执行「过期剔除 → 过滤链」，逐条产出
  通过过滤的事件（过滤链内的过滤器并发执行）。

注意两个边界行为：未 `start()` 就调用 `send()` 或 `receive()` 会抛出 `RuntimeError`；
`receive()` 同一时刻只应被一个消费者迭代（底层缓冲是单消费者内存流）。

配置项的完整语义见[配置说明](configuration.md)；整条链路的结构视图见[架构与数据流](architecture.md)。
