"""Jieba-backed search-mode tokenizer."""

from typing import cast

import jieba  # type: ignore[import-untyped]

from bitongue.filter.utils import Normalizer

__all__ = ("JiebaTokenizer",)


class JiebaTokenizer:
    """Tokenize text with jieba's search-engine segmentation mode.

    The text is normalized (casefold, punctuation folding, NFKC) before
    segmentation, so the tokens returned are already in canonical form.
    """

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """Split text into search-oriented tokens.

        Args:
            text: Text to tokenize.

        Returns:
            Tokens produced by ``jieba.cut_for_search`` over the
            normalized text.
        """

        normalized = Normalizer.normalize(text)

        return cast(
            "list[str]",
            list(jieba.cut_for_search(normalized[0])),
        )
