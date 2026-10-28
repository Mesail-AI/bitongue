# Architecture and data flow

This page explains Bitongue from two angles: the static structure and the runtime behavior.

## Subpackage structure

The library is organized into five subpackages with bottom-up dependencies: `base` depends on nothing internal, and `client` orchestrates all the others:

```{mermaid}
graph BT
    base["base<br/>BaseStruct · exception hierarchy"]
    flow["flow<br/>Flowing · BaseMessage · MessageEntry"]
    filter["filter<br/>BaseFilter · KeywordsFilter · SparseTextualFilter · NeuroTextualFilter"]
    handler["handler<br/>BaseHandler · BaseResult"]
    client["client<br/>Bitongue · BitongueConfig"]

    flow --> base
    filter --> flow
    handler --> base
    client --> flow
    client --> handler
    client --> filter
```

| Subpackage | Responsibility | Main public objects |
|-|-|-|
| `base` | Data-structure foundation and exception root | `BaseStruct`, `BitongueError` and its subclasses |
| `flow` | In-memory flowing window: buffering, timing, expiry removal | `Flowing`, `BaseMessage`, `MessageEntry` |
| `filter` | Message admission gate: Protocol and built-in filters | `BaseFilter`, `KeywordsFilter`, `SparseTextualFilter`, `NeuroTextualFilter` |
| `handler` | Business handling extension point (Protocol) and result base | `BaseHandler`, `BaseResult` |
| `client` | Lifecycle orchestration and both production/consumption ends | `Bitongue`, `BitongueConfig` |

## The life of a message

From send to result, a message passes through these stages:

```{mermaid}
sequenceDiagram
    participant P as Producer
    participant B as Bitongue
    participant F as Flowing window
    participant C as Consumer result()
    participant FC as Filter chain
    participant H as Handler

    P->>B: send(message)
    B->>F: draw() wraps it into a MessageEntry (records enter_time and timeout)
    F->>F: bounded buffer (sender waits when full)
    C->>F: flow() draws entries in order
    F-->>C: entries past their lifetime are dropped as expired
    C->>FC: calls filter(message) concurrently in a task group
    FC-->>C: all passed? otherwise the message is dropped silently
    C->>H: handle(message) (bounded by handle_timeout)
    alt handling succeeds
        H-->>C: returns result R
        C-->>P: yields the result
    else the handler raises
        H--x C: exception (wrapped as MessageHandleError)
        C-->>P: yields a MessageHandleFailure envelope (stream continues)
    end
```

The key points, mapped to the code:

- **The clock starts at entry**: `send()` records `enter_time` immediately, so time spent waiting in the buffer counts against the lifetime.
- **Expiry is enforced on the consumer side**: an expired entry is discovered and skipped when drawn — nothing is produced, nothing raises.
- **The filter chain runs concurrently and does not short-circuit**: the filters start together inside one task group and all of them run; a single rejection drops the message.
- **Handling timeouts are local**: `handle_timeout` covers both the filtering and handling phases of one message; a timeout only affects that message (it is skipped), and the generator keeps consuming.
- **Handling exceptions become failure envelopes**: exceptions raised by the handler are wrapped as `MessageHandleError` and emitted in order as `MessageHandleFailure` envelopes (carrying the source message and the error text) — a single message's failure does not terminate the result stream, and consumers tell results and envelopes apart with `isinstance`.
- **Filter exceptions are combined and raised**: exceptions raised by filters are collected once every filter has finished, combined into one `ExceptionGroup`, and raised, terminating the result stream — admission is pipeline-level infrastructure, and once it breaks no further message can be decided; concurrent sibling exceptions are never swallowed, and a loud failure beats in-band reporting.
- **Filter lifecycles can move up to the orchestrator**: filters implementing `FilterLifecycle` (`start()`/`aclose()`) are started and closed by `Bitongue.start()/shutdown()` — for `SparseTextualFilter` this means collection creation and connection management, for `NeuroTextualFilter` building the agent and the model client, with the one-time cost landing on orchestrator startup instead of the first message.

## Concurrency model

- All async primitives come from anyio, so the library runs on asyncio as well as trio;
- The flowing window is a bounded memory stream: a full buffer makes `send()` wait (backpressure), an empty one makes `result()` wait;
- `result()`'s underlying stream is single-consumer; exactly one task should iterate it at a time; messages are filtered and handled strictly one at a time — there is no concurrent handling;
- The filter chain uses aioresult to run its filters concurrently inside a task group and combines their verdicts once all complete; exceptions raised by any filter are combined into one `ExceptionGroup` and raised as-is;
- `handle_timeout` is implemented with an anyio cancel scope, so a timeout actually cancels the work inside filtering and handling rather than merely abandoning the wait.

## Design trade-offs

- **msgspec instead of dataclass/pydantic**: messages and results need high-frequency serialization; `BaseStruct` provides one consistent surface with sorted-key JSON and typed conversion.
- **Protocols instead of inheritance**: filters and handlers only need "a method with the right signature"; business classes do not inherit any framework base class.
- **Lifecycle centralized in the orchestrator**: `Flowing` can be used standalone, but starting/stopping, timeout configuration, and filter/handler orchestration all converge in `Bitongue` so users cannot assemble the pieces incorrectly.

For the concrete semantics of each configuration field, see [Configuration](configuration.md).
