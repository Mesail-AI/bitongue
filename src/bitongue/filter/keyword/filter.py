"""Aho-Corasick keyword blacklist filter."""

from pathlib import Path
from typing import Self

from ahocorasick import Automaton

from bitongue.filter.protocols import Filter
from bitongue.filter.utils import Normalizer
from bitongue.flow import TextEvent

__all__ = ("KeywordFilter",)


StrPath = Path | str


class KeywordFilter[T: TextEvent](Filter):
    """Keyword blacklist filter backed by an Aho-Corasick automaton.

    Keywords are normalized once at construction; an event is rejected
    when its normalized text contains any keyword as a substring.
    Matching is case- and punctuation-insensitive by way of
    :class:`Normalizer`.

    Args:
        *keywords: Blacklist keywords.
    """

    def __init__(self, *keywords: str) -> None:

        self._keywords = Normalizer.normalize(*keywords)

        automaton = Automaton()

        for keyword in self._keywords:
            automaton.add_word(keyword, keyword)

        if self._keywords:
            automaton.make_automaton()

        self._automaton = automaton

    @classmethod
    def load_file(cls, filepath: "StrPath") -> Self:
        """Build a filter from a keyword file.

        Args:
            filepath: File with one keyword per line, read as UTF-8;
                blank lines are skipped.

        Returns:
            A filter loaded with the file's keywords.
        """

        if isinstance(filepath, str):
            filepath = Path(filepath)

        keywords = [
            line.rstrip()
            for line in filepath.read_text(encoding="utf-8").splitlines()
            if line and line.rstrip()
        ]

        return cls(*keywords)

    async def filter(self, event: "T") -> bool:
        """Reject the event when any keyword occurs in its text.

        Non-text events, empty text, and keyword-less filters pass
        through.

        Args:
            event: The candidate event.

        Returns:
            ``True`` when a keyword matched, ``False`` to pass.
        """

        if event.type != "text" or not event.text or not self._keywords:
            return False

        return any(
            self._automaton.iter(
                next(iter(Normalizer.normalize(event.text))),
            )
        )
