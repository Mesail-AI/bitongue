"""Tests for bitongue.filter.keyword.filter."""

from tests.conftest import MakeTextEvent
from tests.filter.keyword.conftest import MakeKeywordFile

from bitongue.filter.keyword import KeywordFilter
from bitongue.flow import TextEvent


class TestVerdict:
    """Verdict semantics: a keyword hit rejects (blocklist); a miss, empty
    text, or an empty keyword list releases."""

    async def test_hit_rejects(self, make_text_event: MakeTextEvent) -> None:
        sut: KeywordFilter[TextEvent] = KeywordFilter("违禁词")
        assert await sut.filter(make_text_event("正文包含违禁词内容")) is True

    async def test_miss_releases(self, make_text_event: MakeTextEvent) -> None:
        sut: KeywordFilter[TextEvent] = KeywordFilter("违禁词")
        assert await sut.filter(make_text_event("完全无关的内容")) is False

    async def test_substring_hit_rejects(self, make_text_event: MakeTextEvent) -> None:
        # Aho-Corasick matches substrings: the keyword firing as a text
        # fragment counts as a hit.
        sut: KeywordFilter[TextEvent] = KeywordFilter("违规")
        assert await sut.filter(make_text_event("前缀违规后缀")) is True

    async def test_empty_text_releases(self) -> None:
        sut: KeywordFilter[TextEvent] = KeywordFilter("违禁词")
        assert await sut.filter(TextEvent(type="text", text="")) is False

    async def test_empty_keyword_list_releases_all(
        self,
        make_text_event: MakeTextEvent,
    ) -> None:
        # An empty keyword list has nothing to intercept; all is released.
        sut: KeywordFilter[TextEvent] = KeywordFilter()
        assert await sut.filter(make_text_event("任意内容")) is False


class TestNormalization:
    """Matching runs on normalized text; case and punctuation cannot hide a hit."""

    async def test_case_insensitive_hit(self, make_text_event: MakeTextEvent) -> None:
        sut: KeywordFilter[TextEvent] = KeywordFilter("BadWord")
        assert await sut.filter(make_text_event("contains BADWORD here")) is True

    async def test_punctuated_text_hit(self, make_text_event: MakeTextEvent) -> None:
        sut: KeywordFilter[TextEvent] = KeywordFilter("bad word")
        assert await sut.filter(make_text_event("Bad-WORD!!")) is True


class TestLoadFromFile:
    """load_file behaves identically to direct construction."""

    async def test_str_and_path_equivalent(
        self,
        make_keyword_file: MakeKeywordFile,
        make_text_event: MakeTextEvent,
    ) -> None:
        target = make_keyword_file("违禁词")
        from_str: KeywordFilter[TextEvent] = KeywordFilter.load_file(str(target))
        from_path: KeywordFilter[TextEvent] = KeywordFilter.load_file(target)
        event = make_text_event("含违禁词的文本")
        assert await from_str.filter(event) is True
        assert await from_path.filter(event) is True

    async def test_blank_and_symbol_lines_dropped(
        self,
        make_keyword_file: MakeKeywordFile,
        make_text_event: MakeTextEvent,
    ) -> None:
        target = make_keyword_file("违禁词", "", "   ", "!!!")
        sut: KeywordFilter[TextEvent] = KeywordFilter.load_file(target)
        # Symbol-only lines normalize to the empty string and are dropped.
        assert await sut.filter(make_text_event("!!!")) is False
        assert await sut.filter(make_text_event("违禁词")) is True

    async def test_file_keywords_normalized(
        self,
        make_keyword_file: MakeKeywordFile,
        make_text_event: MakeTextEvent,
    ) -> None:
        target = make_keyword_file("BAD word")
        sut: KeywordFilter[TextEvent] = KeywordFilter.load_file(target)
        assert await sut.filter(make_text_event("bad word")) is True
