# Core concepts

Bitongue splits event flow into four independent, single-responsibility concepts. This page covers each one's responsibilities, how they cooperate, and their edge behavior.

## Events and entries (`Event` / `TextEvent` / `EventEntry`)

`Event` is the base class of events (itself a subclass of the `BaseStruct` msgspec struct shared by all data structures), and defines only the minimal envelope: `id` (a unique identifier supplied by the caller — bitongue never generates ids; whatever identifier the business side already has is passed through). Business events subclass `Event` and add their own payload fields; a text payload, for instance, declares `type` (a payload-kind marker) and `text`. As the reference payload shape, `TextEvent` defines what a text event looks like (`type` fixed to `"text"`, `text` carrying the content); the built-in filters are generic over it. It carries no `id` of its own. The `BaseStruct` base provides `to_dict` / `from_dict` / `to_json` / `from_json` serialization, so every event converts naturally between dicts, JSON, and objects.

When an event is sent it does not enter the buffer directly; it is first wrapped into an `EventEntry`: alongside the event itself it records `enter_time` (when it entered the flow) and `timeout` (its lifetime in seconds), which the flowing window uses for expiry removal.

## Flowing window (`Flowing`)

`Flowing[T]` is the in-memory event flowing window, the owner of the bounded buffer:

- **Capacity**: `buffer_size` caps the buffer (built on an anyio memory stream); when the window is full the sender waits, creating natural backpressure.
- **Lifetime**: `timeout` is how long an event stays alive in the window; unset means it never expires.
- **Lifecycle**: `start()` creates the buffer and starts running; `close()` closes it. Calling `send()` (produce) or `receive()` (consume) while not running raises `RuntimeError`. Both lifecycle methods are idempotent.
- **Expiry is enforced on the consumer side**: `receive()` yields unexpired events one by one; entries past their lifetime are skipped outright — never yielded, never an error.

You normally do not operate `Flowing` directly; the `Bitongue` orchestrator drives it for you.

## Filters (`Filter`)

`Filter[T]` is a Protocol (a structural interface); implementing it takes one async method:

```python
async def filter(self, event: T) -> bool:
```

Returning `True` flags the event for rejection; `False` lets it pass. Key points:

- **Any filter returning `True`** drops the event silently; only when every filter returns `False` does the event reach the consumer.
- Filters **run concurrently without short-circuiting**: the chain starts them together in a task group, none waits for another, and all of them execute — every filter sees every event. Filters should therefore be read-only, side-effect-free judgments, and must not assume anything about each other's ordering.
- With no filters configured, every event passes.
- A filter exception is a pipeline-level failure: the orchestrator waits for every filter to finish, then raises all collected exceptions as one `ExceptionGroup`, terminating the event stream — once admission breaks, no further event can be judged; concurrent sibling exceptions never swallow each other.

## Built-in filters

Besides implementing the `Filter` Protocol yourself, `bitongue` ships two ready-made filters.
Both honor the same `True`/`False` contract with different intents: `KeywordFilter` is a
**keyword blocklist** (a match rejects), `SparseTextFilter` is **duplicate interception**
(similarity to the corpus rejects).

### `KeywordFilter` — keyword blocklist

Multi-keyword matching over an Aho-Corasick automaton, in the `bitongue.filter.keyword` subpackage:

- **A match rejects**: any keyword occurring in the text → reject (return `True`); no match → pass;
- **Normalized matching**: keywords and event text alike go through `Normalizer` first (casefold,
  non-word runs folded to spaces, NFKC), so case and punctuation differences cannot hide a match;
- **Substring semantics**: a keyword firing as a fragment of the text counts (Aho-Corasick matches substrings);
- **Edge behavior**: events without a text payload pass (nothing to match); an empty keyword list
  intercepts nothing and passes everything;
- The keyword set comes from varargs or `load_file` (read line by line, UTF-8, blank lines skipped); both construction paths behave identically. The automaton is built at construction time, so `filter` is a pure query with no first-call cost.

```python
from bitongue.filter.keyword import KeywordFilter
```

### `SparseTextFilter` — duplicate interception over sparse retrieval

The reference corpus is embedded into a qdrant sparse collection (BM25 term-frequency weights + IDF correction), and each event queries it as a binary vector; the filter lives in the `bitongue.filter.sparse` subpackage:

- **Similarity rejects**: when an event's similarity to the corpus exceeds `filter_threshold` (default 0.8) → reject (return `True`); unrelated events pass; no text payload → pass;
- **Similarity mapping**: `similarity = scale·score / (1 + scale·score)` (`normalize_scale` defaults to 5), monotonically increasing with the BM25 score, with a zero score (no overlap) mapping naturally to 0. **The threshold leans sensitive: with the defaults, a single overlapping token can push the BM25 score past 0.8 and trigger interception.** For looser admission raise `filter_threshold` (e.g. 0.9+) or lower `normalize_scale` (e.g. 2.0);
- **Deduplicated seeding**: each corpus string is addressed by a UUID5 derived from its own text, so re-seeding overwrites old points instead of accumulating copies; corpus documents that normalize to no usable token are skipped; the corpus is materialized at construction, so passing a generator is safe;
- **Lifecycle**: initialization includes model building and a full corpus upsert, which is expensive, so the filter implements `FilterLifecycle` (`start()` / `close()`): driven by the `Bitongue` orchestrator, `client.start()` initializes it and `close()` releases the connection; standalone, the first `filter` call triggers lazy initialization (lock-protected, a one-off cost charged to the caller's timeout budget);
- **Configuration**: `Bm25Policy` (`language="chinese"` selects the local `Bm25CN` implementation — no downloads, no network; other languages select fastembed's `Bm25`, which requires `model_name` and downloads the model on first use) and `QdrantPolicy` (connection settings whose fields mirror the qdrant-client constructor signature; `location` / `url` / `host` / `path` are mutually exclusive, and in-memory mode uses `location=":memory:"` with `host=None`);
- **Corpus chunking is the caller's job**: each string is one retrievable unit;
- **Dependencies**: shipped as the optional `sparse` extra, imported from the sparse subpackage:

```python
from bitongue.filter.sparse import SparseTextFilter
```

The supporting tool `Normalizer` (text normalization) is importable standalone from `bitongue.filter`;
`JiebaTokenizer` (Chinese search-engine-mode segmentation) lives in the sparse subpackage
(`bitongue.filter.sparse`) alongside `SparseTextFilter`, and requires the `sparse` extra.

## The consumer extension point

Bitongue does not prescribe how events are handled: `receive()` yields the events that passed filtering in order, and the business logic runs freely inside the consume loop — rewriting, persisting, forwarding, calling a model, all up to you. Flow mechanics (buffering, lifetime control, filtering) are therefore fully decoupled from business processing: swapping the logic does not touch the flow configuration, and vice versa.

Failure semantics revolve around flow, not business: the filter chain is an admission facility, and its exceptions surface as one `ExceptionGroup` that terminates the event stream (see "Filters" above); what the consumer does with its own exceptions is the consumer's decision — the library wraps and forwards nothing.

## Orchestrator (`Bitongue` / `BitongueConfig`)

`Bitongue[T]` assembles the parts above into one complete pipeline:

- **Construction**: a `BitongueConfig` plus any number of filters (optional, passed as varargs);
- **Lifecycle**: `start()` creates and starts the flowing window and starts every filter implementing `FilterLifecycle`; `close()` closes those filters in **reverse** registration order and then the window; both are idempotent — a repeated `start()` on a running client and a `close()` on a stopped one do nothing; the `running` property reflects the current state;
- **Production side**: `send(event)` enqueues an event, wrapping and timing the entry internally;
- **Consumption side**: `receive()` is an async generator that runs "expiry removal → filter chain" in order and yields the events that passed (filters within the chain run concurrently).

Two edge behaviors to note: calling `send()` or `receive()` before `start()` raises `RuntimeError`; `receive()` should be iterated by exactly one consumer at a time (the underlying buffer is a single-consumer memory stream).

For full configuration semantics see [Configuration](configuration.md); for the structural view of the whole pipeline see [Architecture and data flow](architecture.md).
