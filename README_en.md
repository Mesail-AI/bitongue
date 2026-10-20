<div align="center">

# Bitongue

An async message flowing library built on anyio and msgspec

[中文](README.md) **·** [English]

[![Tests](https://github.com/Ahsen17/bitongue/actions/workflows/pytest.yml/badge.svg)](https://github.com/Ahsen17/bitongue/actions/workflows/pytest.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](pyproject.toml)

</div>

---

## Contents

[About](#about) **·** [Features](#features) **·** [Installation](#installation) **·** [Quick start](#quick-start) **·** [Architecture](#architecture) **·** [Development](#development) **·** [Documentation](#documentation) **·** [Contributing](#contributing) **·** [License](#license)

## About

Bitongue - A message flowing noting library.

Bitongue is an async message flowing library: producers put messages into an in-memory flowing window; consumers draw them in order, pass them through filters, and hand them to a handler that produces results. Messages and results are [msgspec](https://jcristharif.com/msgspec/) structs and the async primitives come from [anyio](https://anyio.readthedocs.io/) — the flowing window owns buffering and lifetime control, the filter chain owns admission, and the handler owns business logic, each evolving independently.

## Features

- **In-memory message flowing window**: a bounded buffer built on anyio memory streams, with a configurable window size and message lifetime; expired messages are dropped automatically at consumption time, and rejected or expired messages never block the rest
- **Filter-chain admission**: messages pass through the filter chain before processing; filters run concurrently and a message is released only when every filter accepts it, while rejected messages are dropped silently
- **Built-in filters**: the keyword blocklist `KeywordsFilter` (Aho-Corasick with normalized matching), duplicate interception via `SparseFilter` (qdrant sparse retrieval — similar to the corpus means rejected), and model judgment via `NeuroFilter` (natural-language rules decided by a large language model); filters implementing `FilterLifecycle` are started and stopped by the orchestrator
- **Handler extension point**: implement one async `handle(message) -> result` method to plug in your business logic, keeping flow mechanics decoupled from message processing
- **Two layers of timeout protection**: the flowing timeout bounds how long a message stays alive in the window, and the handle timeout caps the combined time a single message may spend in filtering and handling (a timeout actually cancels the in-flight work); timed-out messages are skipped without blocking the rest
- **Type-safe data structures**: messages and results are msgspec structs with built-in dict and JSON serialization, and generic parameters flow through from send to result
- **Layered dependencies**: the core (flowing window, orchestrator, keyword filter) depends only on a few packages such as anyio, msgspec, and pyahocorasick; the domain dependencies of duplicate interception via `SparseFilter` (fastembed, jieba, qdrant-client) ship as the optional `sparse` extra, and those of model judgment via `NeuroFilter` (autogen) ship as the optional `neuro` extra

## Installation

```bash
# uv
uv add bitongue

# pip
pip install bitongue
```

Python ≥ 3.12 is required. If the package is not yet published to PyPI, install it from source:

```bash
uv add git+https://github.com/Ahsen17/bitongue.git
```

Using the built-in duplicate-interception filter `SparseFilter` additionally
requires the optional `sparse` extra (pip users write
`pip install "bitongue[sparse]"`):

```bash
uv add "bitongue[sparse]"
```

Using the built-in model-judgment filter `NeuroFilter` additionally requires
the optional `neuro` extra (pip users write `pip install "bitongue[neuro]"`):

```bash
uv add "bitongue[neuro]"
```

## Quick start

Define a filter (drops empty text) and a handler (uppercases text), send two messages, and consume the result:

```python
from uuid import uuid4

import anyio

from bitongue.client import Bitongue, BitongueConfig
from bitongue.filter import BaseFilter
from bitongue.flow import BaseMessage
from bitongue.handler import BaseHandler, BaseResult


class UpperResult(BaseResult):
    """The handling result: uppercased text."""

    text: str


class NonEmptyFilter(BaseFilter[BaseMessage]):
    """A filter that drops messages with empty text."""

    async def filter(self, message: BaseMessage) -> bool:
        return bool(message.text)


class UpperHandler(BaseHandler[BaseMessage, UpperResult]):
    """A handler that uppercases the text."""

    async def handle(self, message: BaseMessage) -> UpperResult:
        return UpperResult(id=message.id, text=(message.text or "").upper())


async def main() -> None:
    config = BitongueConfig(
        flowing_size=16,       # flowing window capacity (bounded buffer size)
        flowing_timeout=30,    # seconds a message stays alive in the window
        handle_timeout=5.0,    # per-message filtering+handling timeout in seconds
        handle_concurrency=1,  # handling concurrency (reserved field)
    )
    client = Bitongue(config, handler=UpperHandler(), filters=[NonEmptyFilter()])

    await client.start()
    # The id is generated on the business side and passed through; real
    # applications typically reuse an identifier they already have.
    await client.send(BaseMessage(id=uuid4(), type="text", text="hello bitongue"))
    await client.send(BaseMessage(id=uuid4(), type="text", text=""))  # dropped by the filter

    async for result in client.result():
        print(result.text)  # HELLO BITONGUE
        break  # the demo ends here; keep consuming as needed in real usage

    await client.shutdown()


if __name__ == "__main__":
    anyio.run(main)
```

Output:

```text
HELLO BITONGUE
```

For a step-by-step walkthrough, see [Quick start](https://ahsen17.github.io/bitongue/en/guide/quickstart.html) in the documentation site.

## Architecture

```mermaid
flowchart LR
    P[Producer] -->|send| W[Flowing window<br>bounded buffer + lifetime clock]
    W -->|in order| D{Expiry check}
    D -->|expired| X[Dropped silently]
    D --> F[Filter chain<br>concurrent, all must pass]
    F -->|rejected| X
    F --> H[Handler<br>filtering+handling bounded by handle_timeout]
    H -->|yield results| C[Consumer result]
```

- **Production side**: `Bitongue.send()` wraps a message into an entry (recording its entry time and lifetime) and puts it into the bounded buffer; when the window is full the sender waits, creating backpressure.
- **Consumption side**: `Bitongue.result()` draws entries in order and first drops those past their lifetime; filters run concurrently and messages accepted by all of them go to the handler under the combined `handle_timeout` bound covering filtering and handling, while timed-out messages are skipped. Failures follow the scope of the fault: handler exceptions are wrapped as `MessageHandleError` and emitted in order as `MessageHandleFailure` envelopes without interrupting the stream, while filter exceptions are collected into one `ExceptionGroup` that terminates the stream.

For the full structure and the life of a message, see [Architecture and data flow](https://ahsen17.github.io/bitongue/en/guide/architecture.html).

## Development

```bash
make install     # initialize the virtual environment and install dependencies
make check       # lint + type checks + all tests
make coverage    # coverage report (fail_under = 80)
make docs-build  # build the bilingual documentation site
```

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/en/); see [CONTRIBUTING_en.md](CONTRIBUTING_en.md) for details.

## Documentation

The full bilingual documentation site (quick start, core concepts, architecture, configuration):

- 简体中文: <https://ahsen17.github.io/bitongue/>
- English: <https://ahsen17.github.io/bitongue/en/>

## Contributing

Issues are welcome for bug reports and feature requests, and pull requests for changes. AI-assisted coding contributions are accepted, but contributors are fully responsible for the code they submit — see the [contributing guide](CONTRIBUTING_en.md).

## License

[AGPL-3.0](LICENSE)
