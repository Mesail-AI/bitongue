# Quick start

This page walks you from installation to a first complete example: send two events, pass them through a filter, and consume the survivors.

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

The built-in `SparseTextFilter` depends on fastembed, jieba, and qdrant-client, shipped as the optional `sparse` extra (pip users write `pip install "bitongue[sparse]"`):

```bash
uv add "bitongue[sparse]"
```

## A first example

Developing with Bitongue means "define the event, implement filters, consume what passes":

1. Define a **business event type** (subclass `Event`, adding your payload fields);
2. Implement **filters** (satisfying the `Filter` Protocol — return `True` on a match);
3. Create the `Bitongue` orchestrator from a `BitongueConfig` and your filters; after `start`, `send` and `receive` become available;
4. Handle the business logic inside the `receive()` consume loop.

A complete runnable example (save as `demo.py`):

```python
from uuid import uuid4

import anyio

from bitongue.client import Bitongue, BitongueConfig
from bitongue.flow import Event


class TextEvent(Event):
    """A business event: identity plus a text payload."""

    type: str = "text"
    text: str = ""


class EmptyTextFilter:
    """A filter that flags empty text (returning True rejects the event)."""

    async def filter(self, event: TextEvent) -> bool:
        return not event.text


async def main() -> None:
    config = BitongueConfig(
        buffer_size=16,   # flowing window capacity (bounded buffer size)
        event_timeout=30,  # seconds an event stays alive in the window
    )
    client = Bitongue(config, EmptyTextFilter())
    await client.start()

    async def consume() -> None:
        async for event in client.receive():
            print(event.text.upper())  # business logic: uppercase the text
            break  # the demo ends here; keep consuming as needed in real usage

    async with anyio.create_task_group() as tg:
        tg.start_soon(consume)
        # The id is generated on the business side and passed through; real
        # applications typically reuse an identifier they already have.
        await client.send(TextEvent(id=uuid4(), text="hello bitongue"))
        await client.send(TextEvent(id=uuid4(), text=""))  # rejected by the filter

    await client.close()


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

## What happened

1. `client.send(...)` wrapped each event into an entry carrying its entry time and timeout marker, and put it into the bounded buffer; the empty-text event entered the buffer too.
2. `client.receive()` consumed entries in send order: first dropping entries that stayed longer than `event_timeout`; in this example the empty-text event was flagged by `EmptyTextFilter` (returned `True`), dropped silently, and never yielded.
3. Events that passed the filter are yielded one by one by `receive()`; the business logic (uppercasing) runs inside the consume loop.
4. The example stops after the first event.

## Using the built-in filters

Besides implementing the `Filter` Protocol yourself, `bitongue` ships two ready-made filters.
Take the keyword blocklist as an example — just swap the filter set (any keyword match rejects the event):

```python
from bitongue.filter.keyword import KeywordFilter

client = Bitongue(config, KeywordFilter("spam", "banned word"))
```

The other built-in filter, `SparseTextFilter`, does duplicate interception over qdrant sparse retrieval: given a reference corpus, events similar to the corpus are rejected and unrelated ones pass — a good fit for near-duplicate admission. It requires the optional `sparse` extra (see Installation above) and is imported from the sparse subpackage:

```python
from bitongue.filter.sparse import SparseTextFilter
```

For the full semantics, configuration, and edge behavior of both filters (including threshold tuning intuition), see the "Built-in filters" section in [Core concepts](concepts.md).

## Next steps

- Responsibilities and boundaries of each part → [Core concepts](concepts.md)
- Tuning buffering and timeout behavior → [Configuration](configuration.md)
- The overall structure and the life of an event → [Architecture and data flow](architecture.md)
- Public objects and import paths → [API reference](../api)
