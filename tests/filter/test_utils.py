"""Tests for bitongue.filter.utils."""

import pytest

from bitongue.filter import Normalizer


class TestNormalize:
    """The pipeline: casefold, fold non-word runs to single spaces, collapse
    whitespace, then NFKC."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            pytest.param("ABC", "abc", id="casefold"),
            pytest.param("a-b_c!", "a b c", id="non-word-folded-to-space"),
            pytest.param("a   b", "a b", id="whitespace-collapsed"),
            pytest.param("  pad  ", "pad", id="ends-stripped"),
            pytest.param("①", "1", id="nfkc-compatibility"),
            pytest.param("½", "1⁄2", id="nfkc-may-reintroduce-non-word"),  # noqa: RUF001
            pytest.param("", "", id="empty-input"),
        ],
    )
    def test_pipeline(self, raw: str, expected: str) -> None:
        (out,) = Normalizer.normalize(raw)
        assert out == expected

    def test_multi_input_order_preserved(self) -> None:
        assert Normalizer.normalize("B", "a") == ["b", "a"]
