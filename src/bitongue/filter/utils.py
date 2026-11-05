"""Shared text normalization helpers."""

import re
from unicodedata import normalize

__all__ = ("Normalizer",)


class Normalizer:
    """Canonical text form used before any matching.

    Normalization pipeline: casefold, collapse runs of non-word
    characters (including underscores) to single spaces, squeeze
    whitespace, strip, then apply NFKC. Matching components across the
    library rely on this form, so free-text comparisons stay
    case- and punctuation-insensitive.
    """

    @staticmethod
    def normalize(*documents: str) -> list[str]:
        """Normalize each input document.

        Args:
            documents: Documents to normalize.

        Returns:
            One normalized document per input, in input order.
        """

        result: list[str] = []

        for doc in documents:
            doc = re.sub(r"[\W_]+", " ", doc.casefold())
            doc = re.sub(r"\s+", " ", doc).strip()
            doc = normalize("NFKC", doc)

            result.append(doc)

        return result
