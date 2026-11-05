# Architecture and data flow

This page explains how Bitongue is organized, from the static structure and the runtime in turn.

## Subpackage structure

The library splits into four subpackages with bottom-up dependencies: `base` depends on nothing internal, and `client` orchestrates all the rest:

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

| Subpackage | Responsibility | Main public objects |
|-|-|-|
| `base` | Data-structure foundation | `BaseStruct` |
| `flow` | In-memory flowing window: buffering, timing, expiry removal | `Flowing`, `Event`, `TextEvent`, `EventEntry` |
| `filter` | Event admission: Protocols and built-in filters | `Filter`, `FilterLifecycle`, `Normalizer`; subpackages `filter.keyword` (`KeywordFilter`), `filter.sparse` (`SparseTextFilter` etc.) |
| `client` | Lifecycle orchestration and both ends of the pipeline | `Bitongue`, `BitongueConfig` |

## The life of an event

From send to consumption, an event passes through the following stages:

```{mermaid}
sequenceDiagram
    participant P as Producer
    participant B as Bitongue
    participant F as Flowing window
    participant C as Consumer receive()
    participant FC as Filter chain

    P->>B: send(event)
    B->>F: send() wraps into EventEntry (records enter_time and timeout)
    F->>F: bounded buffer (sender waits when full)
    C->>F: receive() draws in order
    F-->>C: drops entries past their lifetime
    C->>FC: task group calls filter(event) concurrently
    FC-->>C: all pass? any match drops the event silently
    C-->>P: yield events that passed
```

A few key points tied to the code:

- **The clock starts at entry**: `send()` records `enter_time` immediately, so time spent waiting in the buffer counts against the lifetime.
- **Expiry is enforced on the consumer side**: an entry is only discovered expired when drawn; it is skipped — never yielded, never an error.
- **The filter chain is concurrent and non-short-circuiting**: filters start together in one task group and all execute; a single matching verdict drops the event.
- **Filter exceptions surface as one group**: the orchestrator waits for every filter to finish, merges all exceptions into a single `ExceptionGroup` and raises it, terminating the event stream — admission is a pipeline-level facility, and when it breaks no further event can be judged; concurrent sibling exceptions never swallow each other, and failing loudly beats in-band reporting.
- **Filter lifecycles roll up into the orchestrator**: filters implementing `FilterLifecycle` (`start()`/`close()`) are started and stopped by `Bitongue.start()/close()` (closing in reverse registration order) — for example `SparseTextFilter`'s collection creation and connection management, whose initialization cost lands at orchestrator startup rather than on the first event.

## Concurrency model

- Every async primitive comes from anyio, so the library runs on both asyncio and trio;
- The flowing window is a bounded memory stream: `send()` waits when the buffer is full (backpressure), and `receive()` waits while it is empty;
- `receive()` sits on a single-consumer stream — exactly one task should iterate it at a time; events are consumed serially one by one, with no concurrent consumption;
- The filter chain runs its filters concurrently inside a task group via aioresult, and aggregates the verdicts once all of them finish; any filter exception is merged into one `ExceptionGroup` and re-raised as-is.

## Design trade-offs

- **msgspec over dataclass/pydantic**: events serialize at high frequency, and `BaseStruct` uniformly provides immutable defaults, sorted-key JSON, and type conversion.
- **Protocols over inheritance**: a filter only needs "one method with the right signature"; business classes inherit nothing from the framework. Events do subclass `Event` to gain identity and serialization.
- **Business logic stays on the consumer side**: the library owns flow only (buffering, lifetime, filtering); the handling logic lives freely in the consumer's `receive()` loop, so neither constrains the other.
- **Centralized lifecycle in the orchestrator**: `Flowing` works standalone, but `start/close`, timeout configuration, and filter orchestration converge in `Bitongue` so users cannot assemble them wrong.

For the concrete semantics of each configuration knob, see [Configuration](configuration.md).
