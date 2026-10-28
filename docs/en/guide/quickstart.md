# Quick start

This page takes you from installation to a complete first example: send two messages, pass them through a filter and a handler, and consume the result.

## Prerequisites

- Python 3.12 or later;
- Optional: [uv](https://docs.astral.sh/uv/) (the recommended package manager).

## Installation

With uv:

```bash
uv add bitongue
```

Or with pip:

```bash
pip install bitongue
```

If the package is not yet published to PyPI, install it from source:

```bash
uv add git+https://github.com/Ahsen17/bitongue.git
```

The built-in `SparseTextualFilter` depends on fastembed, jieba, and qdrant-client,
published as the optional `sparse` extra; install it if you need that filter
(pip users write `pip install "bitongue[sparse]"`):

```bash
uv add "bitongue[sparse]"
```

The built-in `NeuroTextualFilter` depends on the autogen packages, published as the
optional `neuro` extra; install it if you need that filter (pip users write
`pip install "bitongue[neuro]"`):

```bash
uv add "bitongue[neuro]"
```

## Your first example

Developing with Bitongue means "implement three parts and hand them to an orchestrator":

1. Define a **result type** (inherit from `BaseResult`);
2. Implement a **handler** (inherit from `BaseHandler`, containing your business logic);
3. Optionally implement one or more **filters** (inherit from `BaseFilter`, deciding which messages pass);
4. Create the `Bitongue` orchestrator with a `BitongueConfig` and those parts; after `start`, you can `send` messages and consume `result`.

The complete runnable example (save as `demo.py`):

```python
from uuid import uuid4

import anyio

from bitongue.client import Bitongue, BitongueConfig
from bitongue.filter import BaseFilter
from bitongue.flow import TextualMessage
from bitongue.handler import BaseHandler, BaseResult


class UpperResult(BaseResult):
    """The handling result: uppercased text."""

    text: str


class NonEmptyFilter(BaseFilter[TextualMessage]):
    """A filter that drops messages with empty text."""

    async def filter(self, message: TextualMessage) -> bool:
        return bool(message.text)


class UpperHandler(BaseHandler[TextualMessage, UpperResult]):
    """A handler that uppercases the text."""

    async def handle(self, message: TextualMessage) -> UpperResult:
        return UpperResult(id=message.id, text=(message.text or "").upper())


async def main() -> None:
    config = BitongueConfig(
        flowing_size=16,       # flowing window capacity (bounded buffer size)
        flowing_timeout=30,    # seconds a message stays alive in the window
        handle_timeout=5.0,    # per-message filtering+handling timeout in seconds
    )
    client = Bitongue(config, handler=UpperHandler(), filters=[NonEmptyFilter()])

    await client.start()
    # The id is generated on the business side and passed through; real
    # applications typically reuse an identifier they already have.
    await client.send(TextualMessage(id=uuid4(), text="hello bitongue"))
    await client.send(TextualMessage(id=uuid4(), text=""))  # dropped by the filter

    async for result in client.result():
        print(result.text)  # HELLO BITONGUE
        break  # the demo ends here; keep consuming as needed in real usage

    await client.shutdown()


if __name__ == "__main__":
    anyio.run(main)
```

Run it:

```bash
uv run demo.py
```

Output:

```text
HELLO BITONGUE
```

## What just happened

1. `client.send(...)` wrapped each message into an entry that records its entry time and timeout, then put it into the flowing window's bounded buffer; the empty-text message entered the buffer too.
2. `client.result()` consumes entries in send order: messages that stayed in the window longer than `flowing_timeout` are dropped as expired; here the empty-text message is rejected by `NonEmptyFilter` and dropped silently, producing no result.
3. The message that passed the filter is handed to `UpperHandler.handle`; the combined filtering and handling must finish within `handle_timeout` seconds and produces an `UpperResult` (the result mirrors the source message's `id`).
4. `result()` yields the results one by one; the example stops at the first one.

## Using the built-in filters

Instead of implementing `BaseFilter` yourself, `bitongue.filter` ships two
ready-to-use filters. Taking the keyword blocklist as an example, just swap
the filter collection:

```python
from bitongue.filter import KeywordsFilter

client = Bitongue(
    config,
    handler=UpperHandler(),
    filters=[KeywordsFilter(["spam", "违禁词"])],  # any hit rejects the message
)
```

The other built-in filter, `SparseTextualFilter`, intercepts near-duplicates via
qdrant sparse retrieval: given a reference corpus, messages similar to it are
rejected while unrelated ones pass — a good fit for duplicate-content
admission. It requires the optional `sparse` extra (see the installation
section above) and is imported from the sparse subpackage:

```python
from bitongue.filter.sparse import SparseTextualFilter
```

The third built-in filter, `NeuroTextualFilter`, hands natural-language rules and
the message text to a large language model for judgment — a good fit for
semantic admission that keywords cannot enumerate (for example, "reject
abusive content"). It requires the optional `neuro` extra (see the
installation section above), is imported from its own subpackage, and must
be started first — handing it to an orchestrator covers this through
`client.start()`:

```python
from bitongue.filter.neuro import NeuroTextualFilter, NeuroFilterPolicy

neuro = NeuroTextualFilter(
    NeuroFilterPolicy(
        base_url="https://api.example.com/v1",
        api_key="<your-api-key>",
        model="<model-name>",
        rules="Reject messages containing abuse or profanity.",
    ),
)
client = Bitongue(config, handler=UpperHandler(), filters=[neuro])
```

For the full semantics, configuration, and boundary behavior
of all three (including how to think about the threshold), see the "Built-in
filters" section of [Core concepts](concepts.md).

## Next steps

- Understand each part's responsibilities → [Core concepts](concepts.md)
- Tune buffering and timeouts → [Configuration](configuration.md)
- See the big picture and message lifecycle → [Architecture and data flow](architecture.md)
- Look up public objects and imports → [API reference](../api)
