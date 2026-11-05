"""Fixtures shared by the keyword-filter unit tests."""

from collections.abc import Callable
from pathlib import Path

import pytest

type MakeKeywordFile = Callable[..., Path]


@pytest.fixture
def make_keyword_file(tmp_path: Path) -> MakeKeywordFile:
    """Factory fixture: write a keyword list to a temp file, return its path."""

    def _make(*lines: str) -> Path:
        target = tmp_path / "keywords.txt"
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target

    return _make
