# Configuration

Bitongue's runtime behavior is described centrally by `BitongueConfig`, passed when creating the orchestrator:

```python
from bitongue.client import BitongueConfig

config = BitongueConfig(
    buffer_size=16,
    event_timeout=30,
)
```

`BitongueConfig` is itself a msgspec struct (subclassing `BaseStruct`); `buffer_size` is required and `event_timeout` is optional.

## Field reference

| Field | Type | Unit | Meaning |
|-|-|-|-|
| `buffer_size` | `int` | events | Bounded-buffer capacity of the flowing window; `send()` waits when full, creating backpressure |
| `event_timeout` | `float \| None` | seconds | How long an event stays alive in the window; entries past it are removed at consumption time; `None` (default) means never expiring |

## Field behavior in detail

### `buffer_size`

The capacity is the maximum buffer length of the anyio memory stream. An event occupies one slot from `send()` until `receive()` draws it. Sizing guidance:

- Too small: producers wait frequently under bursty traffic;
- Too large: bursts are buffered wholesale, and the consumer's expiry-removal pressure and memory footprint grow with them.

### `event_timeout`

The lifetime clock starts when the event **enters** the buffer (`send()`), and time spent waiting in the buffer counts. Expired entries are removed **on the consumer side**: never yielded, never an error, fully transparent to producers. Set it to `None` to switch this timeout layer off and let events wait indefinitely for consumption.

## Lifecycle constraints

The configuration is read once, when `Bitongue` is created, and used to build the internal window at `start()`:

- Calling `send()` or `receive()` before `start()` raises `RuntimeError`;
- After `close()` the window is shut; reusing the same orchestrator requires another `start()`.

## A timeout combination example

```python
config = BitongueConfig(
    buffer_size=64,    # room for a burst of 64 queued events
    event_timeout=10,  # events queued longer than 10 seconds expire
)
```

The meaning of this combination: an event lives at most 10 seconds counted from entry, then expires; expired events never block the consumption of the ones behind them.

## Filter configuration (`SparseTextFilter`)

`SparseTextFilter` behavior is described by its constructor arguments and two policy structs (full fields in the corresponding modules of the [API reference](../api); the most commonly tuned parts are listed here):

| Parameter / field | Default | Meaning |
|-|-|-|
| `filter_threshold` | `0.8` | Duplicate threshold: similarity above it rejects; value must lie in the open interval (0, 1) |
| `normalize_scale` | `5.0` | Saturation rate of the similarity mapping; the larger it is, the lower a BM25 score counts as highly similar (more sensitive) |
| `Bm25Policy.language` | `"chinese"` | Chinese selects the local `Bm25CN` implementation (no downloads, no network); other languages select fastembed's `Bm25` |
| `Bm25Policy.model_name` | `""` | Required for non-Chinese languages (empty means unset and fails loudly at startup); ignored on the Chinese path |
| `Bm25Policy.k` / `b` / `avg_len` | `1.2` / `0.75` / `256.0` | BM25 formula parameters (term-frequency saturation, length normalization, average document length) |
| `QdrantPolicy.location` / `url` / `host` / `path` | `host="localhost"` | Connection target, **mutually exclusive** (enforced by qdrant-client); in-memory mode uses `location=":memory:"` with `host=None` |
| `QdrantPolicy.port` / `grpc_port` | `6333` / `6334` | REST / gRPC ports for host-based connections |

Threshold and scale tuning intuition: with the defaults, "similarity > 0.8" is equivalent to "BM25 score > 0.8" —
**an event sharing even a single token with the corpus may trigger interception** (a larger corpus lowers the
token's IDF and makes it harder to trigger; small corpora make it easy). To reduce false positives: raise
`filter_threshold` (e.g. 0.9+) or lower `normalize_scale` (e.g. 2.0); to intercept near-duplicates more
aggressively, adjust in the opposite direction.

Non-Chinese embedding models download from HuggingFace on first use; control the cache location with
`Bm25Policy.cache_dir` or the `FASTEMBED_CACHE_PATH` environment variable. `KeywordFilter` performs no
network access and needs no configuration.
