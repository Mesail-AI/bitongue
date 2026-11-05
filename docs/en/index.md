# Bitongue

An async event flowing library built on [anyio](https://anyio.readthedocs.io/) and [msgspec](https://jcristharif.com/msgspec/).

Bitongue splits "receiving, filtering, and consuming" into three independently evolving stages: producers put events into an in-memory flowing window that owns buffering and lifetime control; a filter chain decides which events pass; business logic stays free-form on the consumer side.

## Features

- **In-memory flowing window**: a bounded buffer built on anyio memory streams, with a configurable window size and event lifetime;
  expired events are dropped automatically at consumption time, see [Quick start](guide/quickstart.md)
- **Filter-chain admission**: filters run concurrently without short-circuiting, and a single matching verdict rejects the event;
  rejected events are dropped silently, see [Core concepts](guide/concepts.md)
- **Consumer extension point**: `receive()` yields the events that passed filtering in order; business logic lives in the
  consume loop, keeping flow mechanics decoupled from event processing
- **Lifetime timeout protection**: `event_timeout` bounds how long an event stays alive in the window; expired events are
  skipped silently on the consumer side, see [Configuration](guide/configuration.md)
- **Type safety**: events are msgspec structs with built-in dict / JSON serialization, and generic parameters flow through
  from send to consumption
- **Minimal dependencies**: the core depends only on a few packages such as anyio and msgspec; the domain dependencies of
  `SparseTextFilter` ship as the optional `sparse` extra

Python ≥ 3.12 is required.

```{toctree}
:hidden:

guide/quickstart
guide/concepts
guide/architecture
guide/configuration
api
```
