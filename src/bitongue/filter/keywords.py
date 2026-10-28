from pathlib import Path
from typing import Self

from ahocorasick import Automaton

from bitongue.flow import TextualMessage

from .protocols import BaseFilter
from .utils import Normalizer

__all__ = ("KeywordsFilter",)


class KeywordsFilter[T: TextualMessage](BaseFilter):
    """Reject messages whose text contains any of the known keywords.

    Matching runs on normalized text: keywords and message text are both
    passed through :class:`bitongue.filter.utils.Normalizer`, so case and
    punctuation differences cannot hide a hit. Under the ``BaseFilter``
    contract this is a blocklist gate — a keyword hit rejects the message,
    while a message with no hit is released. A message carrying no text
    payload is released as well, since there is nothing to match; with an
    empty keyword list nothing can be intercepted, so every message is
    released.

    Keyword normalization and automaton building happen eagerly in the
    constructor, so :meth:`filter` is a pure lookup with no first-call
    cost.

    Attributes:
        keywords: Keywords to build the automaton from. Every entry is
            normalized first; blank results are dropped. An empty list
            intercepts nothing and releases every message.
    """

    def __init__(self, keywords: list[str]) -> None:

        self._keywords = [
            keyword for keyword in Normalizer.normalize(*keywords) if keyword
        ]

        automaton = Automaton()

        for keyword in self._keywords:
            automaton.add_word(keyword, keyword)

        # pyahocorasick skips the trie-to-automaton conversion when no
        # word was added; the empty-keyword case is short-circuited in
        # `filter` instead.
        if self._keywords:
            automaton.make_automaton()

        self._automaton = automaton

    @classmethod
    def load_from_file(cls, filepath: "Path | str") -> Self:

        if isinstance(filepath, str):
            filepath = Path(filepath)

        keywords = [
            line.strip()
            for line in filepath.read_text(
                encoding="utf-8",
            ).splitlines()
            if line and line.strip()
        ]

        return cls(keywords)

    async def filter(self, message: "T") -> bool:

        if message.type != "text" or not message.text or not self._keywords:
            return True

        return not any(
            self._automaton.iter(
                next(iter(Normalizer.normalize(message.text))),
            )
        )
