# Core concepts

Bitongue splits message handling into five independent, single-purpose concepts. This page explains each one's responsibility, how they cooperate, and their boundary behavior.

## Messages and entries (`BaseMessage` / `TextualMessage` / `MessageEntry`)

`BaseMessage` is the message base class (itself a subclass of `BaseStruct`, the msgspec struct wrapper shared by all data structures). It defines only the minimal message envelope: `id` (a caller-supplied unique identifier — bitongue never generates one; pass through the business-side ID you already have). The text message `TextualMessage` is the default concrete message type and adds two fields: `type` (a payload-kind tag, fixed to `"text"`) and `text` (optional text content; `None` means the message carries no text payload). The inherited `BaseStruct` provides `to_dict` / `from_dict` / `to_json` / `from_json`, so every message converts between dicts, JSON, and objects out of the box; messages with other payload shapes can subclass `BaseMessage` to add their own fields.

A message does not enter the buffer directly when sent; it is first wrapped into a `MessageEntry` that, besides the message itself, records `enter_time` (the moment of entry) and `timeout` (the lifetime in seconds) for the flowing window's expiry checks.

## The flowing window (`Flowing`)

`Flowing[T]` is the in-memory message flowing window — the holder of the bounded buffer:

- **Capacity**: `size` bounds the buffer (built on an anyio memory stream); when the window is full, the sender waits, which acts as natural backpressure.
- **Lifetime**: `timeout` is how many seconds a message may stay in the window; if unset, messages never expire.
- **Lifecycle**: `start()` creates the buffer and marks the window running; `shutdown()` closes it. Calling `draw()` (produce) or `flow()` (consume) while not running raises `FlowingNotInitializedError`.
- **Expiry is enforced on the consumer side**: `flow()` yields only unexpired messages; entries older than their lifetime are skipped without producing anything or raising.

You normally do not operate `Flowing` directly — use the `Bitongue` orchestrator instead.

## Filters (`BaseFilter`)

`BaseFilter[T]` is a Protocol (a structural interface); implementing it takes one async method:

```python
async def filter(self, message: T) -> bool:
```

Return `True` to release the message, `False` to reject it. Key points:

- A message proceeds to handling only when **every filter in the chain returns `True`**; a single `False` drops the message silently.
- Filters **run concurrently**: the chain starts them together in a task group — none waits for another, and all of them execute (no short-circuit). Filters should therefore be read-only, side-effect-free predicates, and must not assume any ordering among themselves.
- With no filters configured, every message passes.

## Built-in filters

Besides your own Protocol implementations, `bitongue.filter` ships three
ready-to-use filters. They share the same `True`/`False` contract but take
different admissions: `KeywordsFilter` is a **keyword blocklist** (a hit
rejects), `SparseTextualFilter` is **duplicate interception** (similarity to the
corpus rejects), and `NeuroTextualFilter` is **model judgment** (natural-language
rules decided by a large language model).

### `KeywordsFilter` — keyword blocklist

Multi-keyword matching on an Aho-Corasick automaton:

- **A hit rejects**: any keyword found in the text → reject; no hit → release;
- **Normalized matching**: keywords and message text both go through the
  `Normalizer` (casefold, non-word runs folded to spaces, NFKC), so case and
  punctuation differences cannot hide a hit;
- **Substring semantics**: a keyword firing as a fragment of the text counts
  as a hit (Aho-Corasick matches substrings);
- **Boundary behavior**: messages without a text payload are released (nothing
  to match); with an empty keyword list nothing can be intercepted, so every
  message is released;
- The keyword list may come from a list or `load_from_file` (line by line,
  UTF-8, blank lines ignored); both construction paths behave identically.
  The automaton is built eagerly in the constructor — `filter` is a pure
  lookup with no first-call cost.

### `SparseTextualFilter` — duplicate interception via sparse retrieval

The reference corpus is embedded into a qdrant sparse collection (BM25
term-frequency weights with IDF modification); each message is embedded as a
binary query vector and searched against it:

- **Similarity rejects**: a message whose similarity to the corpus exceeds
  `filter_threshold` (default 0.8) → reject; unrelated → release; no text
  payload → release;
- **Similarity mapping**: `similarity = scale·score / (1 + scale·score)`
  (`normalize_scale` default 5), monotonically increasing in the BM25 score,
  with a zero score (no overlap) mapping to zero. **The threshold semantics
  run sensitive: under the defaults, even a single token overlapping the
  corpus can push the BM25 score past 0.8 and trigger interception**; for a
  looser gate raise `filter_threshold` (e.g. 0.9+) or lower `normalize_scale`
  (e.g. 2.0);
- **Deduplicated seeding**: each corpus string is addressed by the UUID5 of
  its own text, so re-seeding overwrites existing points instead of stacking
  copies; corpus documents that normalize to no usable token are skipped;
- **Lifecycle**: initialization includes building the embedding and a full
  corpus upsert, which is comparatively expensive, so the class implements
  `FilterLifecycle` (`start()` / `aclose()`): handed to a `Bitongue`
  orchestrator, `client.start()` initializes it and `shutdown()` releases the
  connection; standalone, the first `filter` call lazily initializes (lock
  protected, a one-time cost inside the caller's timeout budget);
- **Configuration**: `Bm25Policy` (`language="chinese"` selects the local
  `Bm25CN` implementation — no download, no network; any other language
  selects fastembed's `Bm25`, which requires `model_name` and downloads the
  model on first use) and `QdrantPolicy` (connection settings whose field
  names mirror the qdrant-client constructor; `location` / `url` / `host` /
  `path` are mutually exclusive — in-memory mode uses `location=":memory:"`
  with `host=None`);
- **Corpus chunking is the caller's responsibility**: each string is one
  searchable unit.

### `NeuroTextualFilter` — rule judgment by a large language model

The filtering rules and the message text travel together to an
OpenAI-compatible chat endpoint (via autogen's `AssistantAgent`
internally), and the model returns a structured verdict against the
rules:

- **A rejecting verdict rejects**: the model answering `filtered=True` →
  reject; a releasing verdict → release. Rules accept a single string or a
  list of strings (a list is joined into one rule block with newlines);
- **No model call, release**: messages without a text payload, or with
  rules that normalize to nothing, are released outright — neither boundary
  issues a model call;
- **Every failure on the model path raises**: a response not matching the
  verdict schema (`ValueError`), a backend error, or a single call exceeding
  `timeout` (`TimeoutError`) all raise — the filter swallows nothing. Under
  the orchestrator, a timeout is caught by the existing `handle_timeout`
  contract (that message is skipped silently); every other error is a
  pipeline-scoped failure, combined into the filter chain's `ExceptionGroup`
  that terminates the result stream;
- **Isolation between messages**: every verdict runs in a fresh conversation
  context that is cleared as soon as the verdict is read — one message's text
  never enters another's request; a single instance is not safe for
  concurrent calls (the orchestrator's single-consumer pipeline already
  serializes them);
- **Lifecycle**: construction only stores the configuration and contacts
  nothing; `start()` builds the agent and the model client, and calling
  `filter` before that raises `RuntimeError`. Unlike `SparseTextualFilter`'s lazy
  initialization, `NeuroTextualFilter` must be started first — handing it to an
  orchestrator covers this through `client.start()`;
- **Configuration**: `NeuroFilterPolicy` (endpoint `base_url`, `api_key`,
  model `model`, rules `rules`, per-verdict `timeout`); the customization
  point for endpoint and model capability claims is `OpenAIClientProvider`.
  Note that serializing the policy (`to_json`) carries the `api_key` along —
  treat a serialized policy as secret material;
- **Dependencies**: shipped as the optional `neuro` extra, imported from its
  own subpackage:

```python
from bitongue.filter.neuro import NeuroTextualFilter, NeuroFilterPolicy
```

The verdict type is a pydantic model — a hard requirement of autogen's
structured output, and the library's single deliberate exception to its
"all data structures are msgspec" convention.

The supporting tool `Normalizer` (text normalization) is usable on its own;
`JiebaTokenizer` (Chinese search-mode segmentation) lives in the sparse
subpackage (`bitongue.filter.sparse`) alongside `SparseTextualFilter` and requires
the optional `sparse` extra.

## Handlers and results (`BaseHandler` / `BaseResult` / `MessageHandleFailure`)

`BaseHandler[T, R]` is the business-logic extension point, also a Protocol, with one async method:

```python
async def handle(self, message: T) -> R:
```

`R` must be a subclass of `BaseResult` — results are msgspec structs just like messages, with the same serialization abilities; the base class already carries an `id` field (same convention as `BaseMessage.id`: a business-side identifier supplied by the caller, conventionally mirrored from the source message), and the subclass declares the remaining fields the handler yields. Declaring the result type as a generic parameter (`BaseHandler[TextualMessage, UpperResult]`) gives you type checking across the whole path from send to result.

Failures follow the scope of the fault. An exception a handler raises is a message-scoped failure: it is wrapped into `MessageHandleError` and emitted in order as a `MessageHandleFailure` envelope (carrying the source message and the error text), and the stream keeps consuming later messages — the yield type of `result()` is therefore `R | MessageHandleFailure`, and consumers tell normal results and failure envelopes apart with `isinstance`. If the combined time a message spends in filtering and handling exceeds the configured `handle_timeout`, that message is skipped silently (no result is produced, and consumption continues). An exception a filter raises is a pipeline-scoped failure: the orchestrator waits for every filter to finish, combines all their exceptions into one `ExceptionGroup`, and raises it, terminating the result stream — a broken admission mechanism cannot decide any further message, and concurrent sibling exceptions are never swallowed.

## The orchestrator (`Bitongue` / `BitongueConfig`)

`Bitongue[T, R]` assembles the parts above into one pipeline:

- **Construction**: takes a `BitongueConfig`, a handler (required), and an optional collection of filters;
- **Lifecycle**: `start()` creates and starts the flowing window internally; `shutdown()` closes it in reverse order; both are idempotent — calling `start()` on a running client or `shutdown()` on a stopped client does nothing — and the `running` property reports the current state;
- **Production side**: `send(message)` submits a message, wrapping and timing it internally;
- **Consumption side**: `result()` is an async generator that runs "expiry removal → filter chain → handler" in order (filters inside the chain run concurrently; `handle_timeout` covers both the filtering and handling phases) and yields results one at a time.

Two boundary behaviors to note: calling `send()` or `result()` before `start()` raises a `RuntimeError`, and `result()` should be iterated by exactly one consumer at a time (the underlying buffer is a single-consumer memory stream).

For the full semantics of the configuration fields, see [Configuration](configuration.md); for a structural view of the whole path, see [Architecture and data flow](architecture.md).
