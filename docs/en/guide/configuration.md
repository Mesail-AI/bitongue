# Configuration

Bitongue's runtime behavior is described centrally by `BitongueConfig`, passed when the orchestrator is created:

```python
from bitongue.client import BitongueConfig

config = BitongueConfig(
    flowing_size=16,
    flowing_timeout=30,
    handle_timeout=5.0,
)
```

`BitongueConfig` is itself a msgspec struct (inheriting `BaseStruct`); all three fields are required.

## Field overview

| Field | Type | Unit | Meaning |
|-|-|-|-|
| `flowing_size` | `int` | messages | Capacity of the flowing window's bounded buffer; when full, `send()` waits, creating backpressure |
| `flowing_timeout` | `int \| None` | seconds | How long a message may live in the window; entries older than this are dropped at consumption time; `None` means never expire |
| `handle_timeout` | `float` | seconds | Maximum combined time allowed per message across filtering and handling; timed-out messages are skipped (no result, consumption continues) |

## Field behavior in detail

### `flowing_size`

The capacity maps to the maximum buffer length of the anyio memory stream. A message occupies one slot from `send()` until `result()` draws it out. Choosing a value:

- Too small: producers wait frequently under bursty traffic;
- Too large: bursts are buffered in full, raising memory usage and the expiry-removal load on the consumer side.

### `flowing_timeout`

The lifetime clock starts when the message **enters the buffer** (`send()`), so time spent waiting counts. Expired entries are removed **on the consumer side**: no result, no error, and completely transparent to the producer. Set it to `None` to disable this timeout layer and let messages wait indefinitely for consumption.

Division of labor between the two timeout layers: `flowing_timeout` governs "how long a message is worth processing at all", while `handle_timeout` governs "how long one message may take through filtering and handling".

### `handle_timeout`

The timeout window covers both the **filtering and handling phases** of one message (the filter chain's total time counts against the budget). Implemented with an anyio cancel scope: a timeout **actually cancels** the execution inside filtering or handling (it does not merely stop waiting), then skips that message and continues with the next one. Cleanup logic inside the handler (`try/finally`, `async with`, and so on) runs normally.

Messages are handled **strictly one at a time**: `result()`'s underlying stream is single-consumer and the config offers no concurrent-handling option; for higher throughput, shard traffic across multiple orchestrator instances.

## Lifecycle constraints

The configuration is read once when the `Bitongue` orchestrator is created, and used to build the internal flowing window at `start()`:

- Calling `send()` or `result()` before `start()` raises a `RuntimeError`;
- After `shutdown()` the window is closed; reuse the orchestrator by calling `start()` again.

## One timeout-combination example

```python
config = BitongueConfig(
    flowing_size=64,      # allow bursts of up to 64 queued messages
    flowing_timeout=10,   # messages queued longer than 10 seconds expire
    handle_timeout=2.0,   # at most 2 seconds per message, timed-out ones are skipped
)
```

The meaning of this combination: in the worst case, a message takes no more than about 12 seconds from entering the buffer to finishing processing; expired or timed-out messages never block the consumption of later ones.

## Filter configuration (`SparseFilter`)

`SparseFilter` behavior is described by its constructor arguments and two
policy structs (the full field lists live in the
[API reference](../api); the tuning-relevant parts are below):

| Parameter / field | Default | Meaning |
|-|-|-|
| `filter_threshold` | `0.8` | Duplicate threshold: a message is rejected once its similarity exceeds it; valid range is the open interval (0, 1) |
| `normalize_scale` | `5.0` | Similarity saturation rate; the larger it is, the lower a BM25 score counts as highly similar (more sensitive) |
| `Bm25Policy.language` | `"chinese"` | Chinese uses the local `Bm25CN` implementation (no download, no network); other languages use fastembed's `Bm25` |
| `Bm25Policy.model_name` | `""` | Required for non-Chinese languages (an empty string means unset and fails at startup with a clear error); ignored on the Chinese path |
| `Bm25Policy.k` / `b` / `avg_len` | `1.2` / `0.75` / `256.0` | BM25 formula parameters (term-frequency saturation, length normalization, average document length) |
| `QdrantPolicy.location` / `url` / `host` / `path` | `host="localhost"` | Connection target; **the four are mutually exclusive** (enforced by qdrant-client); in-memory mode uses `location=":memory:"` with `host=None` |
| `QdrantPolicy.port` / `grpc_port` | `6333` / `6334` | REST / gRPC ports for host-based connections |

How to think about threshold and scale: under the defaults, "similarity > 0.8"
is equivalent to "BM25 score > 0.8" — **even a single token overlapping the
corpus can trigger interception** (harder on large corpora where the token's
IDF is low, easier on small ones). To reduce false interception, raise
`filter_threshold` (e.g. 0.9+) or lower `normalize_scale` (e.g. 2.0); to
intercept near-duplicates more aggressively, adjust in the opposite direction.

Non-Chinese embedding models are downloaded from HuggingFace on first use;
place the cache with `Bm25Policy.cache_dir` or the `FASTEMBED_CACHE_PATH`
environment variable. `KeywordsFilter` performs no network access and needs
no configuration.

## Filter configuration (`NeuroFilter`)

`NeuroFilter` behavior is described by a single struct, `NeuroFilterPolicy`:

| Field | Default | Meaning |
|-|-|-|
| `base_url` | required | Base URL of an OpenAI-compatible chat endpoint |
| `api_key` | required | Endpoint key; serializing the policy (`to_json`) carries it along, so treat a serialized policy as secret material |
| `model` | required | Model name served by the endpoint |
| `rules` | required | Filtering rules; a list of strings is joined into one rule block with newlines, a single string is used verbatim; rules that normalize to nothing release every message |
| `timeout` | `10.0` | Seconds allowed for one model verdict; a call that outlives it raises `TimeoutError` |

Division of labor between the two timeout layers: `timeout` governs a single
model call and raises once exceeded, while the whole filtering phase still
counts against the `handle_timeout` budget — a pipeline with `NeuroFilter`
needs a `handle_timeout` that accommodates the model call's typical latency.

Endpoint and model capability claims are customized in
`OpenAIClientProvider`: the client declares structured output and related
capabilities to autogen, which is what makes the model answer with the agreed
JSON verdict shape. A backend model that does not actually support them fails
at call time — declare the real capabilities there when adapting to a
non-standard backend.
