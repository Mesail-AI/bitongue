"""Tests for bitongue.filter.keywords."""

from uuid import uuid4

from tests.conftest import MakeMessage
from tests.filter.conftest import MakeKeywordFile

from bitongue.filter import KeywordsFilter
from bitongue.flow import TextualMessage


class TestVerdict:
    """Verdict semantics: a keyword hit rejects (blocklist); a miss, empty
    text, or an empty keyword list releases."""

    async def test_hit_rejects(self, make_message: MakeMessage) -> None:
        sut: KeywordsFilter[TextualMessage] = KeywordsFilter(["违禁词"])
        assert await sut.filter(make_message("正文包含违禁词内容")) is False

    async def test_miss_releases(self, make_message: MakeMessage) -> None:
        sut: KeywordsFilter[TextualMessage] = KeywordsFilter(["违禁词"])
        assert await sut.filter(make_message("完全无关的内容")) is True

    async def test_substring_hit_rejects(self, make_message: MakeMessage) -> None:
        # Aho-Corasick matches substrings: the keyword firing as a text
        # fragment counts as a hit.
        sut: KeywordsFilter[TextualMessage] = KeywordsFilter(["违规"])
        assert await sut.filter(make_message("前缀违规后缀")) is False

    async def test_empty_text_releases(self) -> None:
        sut: KeywordsFilter[TextualMessage] = KeywordsFilter(["违禁词"])
        assert await sut.filter(TextualMessage(id=uuid4())) is True

    async def test_empty_keyword_list_releases_all(
        self,
        make_message: MakeMessage,
    ) -> None:
        # An empty keyword list has nothing to intercept; all is released.
        sut: KeywordsFilter[TextualMessage] = KeywordsFilter([])
        assert await sut.filter(make_message("任意内容")) is True


class TestNormalization:
    """Matching runs on normalized text; case and punctuation cannot hide a hit."""

    async def test_case_insensitive_hit(self, make_message: MakeMessage) -> None:
        sut: KeywordsFilter[TextualMessage] = KeywordsFilter(["BadWord"])
        assert await sut.filter(make_message("contains BADWORD here")) is False

    async def test_punctuated_text_hit(self, make_message: MakeMessage) -> None:
        sut: KeywordsFilter[TextualMessage] = KeywordsFilter(["bad word"])
        assert await sut.filter(make_message("Bad-WORD!!")) is False


class TestLoadFromFile:
    """load_from_file behaves identically to direct construction."""

    async def test_str_and_path_equivalent(
        self,
        make_keyword_file: MakeKeywordFile,
        make_message: MakeMessage,
    ) -> None:
        target = make_keyword_file("违禁词")
        from_str: KeywordsFilter[TextualMessage] = KeywordsFilter.load_from_file(
            str(target),
        )
        from_path: KeywordsFilter[TextualMessage] = KeywordsFilter.load_from_file(target)
        message = make_message("含违禁词的文本")
        assert await from_str.filter(message) is False
        assert await from_path.filter(message) is False

    async def test_blank_and_symbol_lines_dropped(
        self,
        make_keyword_file: MakeKeywordFile,
        make_message: MakeMessage,
    ) -> None:
        target = make_keyword_file("违禁词", "", "   ", "!!!")
        sut: KeywordsFilter[TextualMessage] = KeywordsFilter.load_from_file(target)
        # Symbol-only lines normalize to the empty string and are dropped.
        assert await sut.filter(make_message("!!!")) is True
        assert await sut.filter(make_message("违禁词")) is False

    async def test_file_keywords_normalized(
        self,
        make_keyword_file: MakeKeywordFile,
        make_message: MakeMessage,
    ) -> None:
        target = make_keyword_file("BAD word")
        sut: KeywordsFilter[TextualMessage] = KeywordsFilter.load_from_file(target)
        assert await sut.filter(make_message("bad word")) is False
