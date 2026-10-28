"""Tests for bitongue.filter.sparse.filter (qdrant ``:memory:``)."""

import math
from collections.abc import Iterator, Sequence
from uuid import uuid4

import anyio
import numpy as np
import pytest
from fastembed.sparse.sparse_embedding_base import SparseEmbedding
from pytest_mock import MockerFixture
from tests.conftest import MakeMessage
from tests.filter.sparse.conftest import MakeSparseTextualFilter

from bitongue.client import Bitongue, BitongueConfig
from bitongue.filter.sparse import Bm25Policy, QdrantPolicy, SparseTextualFilter
from bitongue.flow import TextualMessage
from bitongue.handler import BaseHandler, BaseResult


class _EchoResult(BaseResult):
    content: str


class _EchoHandler(BaseHandler[TextualMessage, _EchoResult]):
    async def handle(self, message: TextualMessage) -> _EchoResult:
        return _EchoResult(id=message.id, content=message.text or "")


class TestConstruction:
    """Construction-time validation: configuration errors raise at
    construction (collapsed exception surface)."""

    @pytest.mark.parametrize("threshold", [0.0, 1.0, -0.5, 1.5])
    async def test_invalid_threshold_rejected(self, threshold: float) -> None:
        with pytest.raises(ValueError, match="threshold"):
            SparseTextualFilter("c", ["d"], filter_threshold=threshold)

    @pytest.mark.parametrize("scale", [0.0, -1.0, math.inf, math.nan])
    async def test_invalid_scale_rejected(self, scale: float) -> None:
        with pytest.raises(ValueError, match="scale"):
            SparseTextualFilter("c", ["d"], normalize_scale=scale)


class TestScoreNormalize:
    """Similarity mapping: zero score maps to zero, monotonic, bounded [0, 1)."""

    def test_zero_score_maps_to_zero(self, in_memory_policy: QdrantPolicy) -> None:
        sut: SparseTextualFilter[TextualMessage] = SparseTextualFilter(
            "c",
            ["d"],
            qdrant_policy=in_memory_policy,
        )
        assert sut._score_normalize(0.0, scale=5.0) == 0.0

    def test_monotonically_increasing(self, in_memory_policy: QdrantPolicy) -> None:
        sut: SparseTextualFilter[TextualMessage] = SparseTextualFilter(
            "c",
            ["d"],
            qdrant_policy=in_memory_policy,
        )
        values = [sut._score_normalize(s, scale=5.0) for s in (0.01, 0.1, 1.0, 10.0)]
        assert values == sorted(values)

    def test_bounded_below_one(self, in_memory_policy: QdrantPolicy) -> None:
        sut: SparseTextualFilter[TextualMessage] = SparseTextualFilter(
            "c",
            ["d"],
            qdrant_policy=in_memory_policy,
        )
        assert sut._score_normalize(1e9, scale=5.0) < 1.0


class TestLifecycle:
    """Lifecycle: explicit start/aclose, idempotence, single build under
    concurrency, and client orchestration."""

    async def test_not_running_before_start(
        self,
        make_sparse_filter: MakeSparseTextualFilter,
    ) -> None:
        sut = make_sparse_filter(["文档一"])
        assert sut.running is False

    async def test_start_idempotent_builds_once(
        self,
        make_sparse_filter: MakeSparseTextualFilter,
        mocker: MockerFixture,
    ) -> None:
        sut = make_sparse_filter(["文档一"])
        spy = mocker.spy(SparseTextualFilter, "_build")
        await sut.start()
        await sut.start()
        assert sut.running is True
        assert spy.call_count == 1

    async def test_concurrent_first_use_builds_once(
        self,
        make_sparse_filter: MakeSparseTextualFilter,
        make_message: MakeMessage,
        mocker: MockerFixture,
    ) -> None:
        sut = make_sparse_filter(["文档一"])
        spy = mocker.spy(SparseTextualFilter, "_build")
        results: list[bool] = []

        async with anyio.create_task_group() as tg:

            async def call() -> None:
                results.append(await sut.filter(make_message("文档一 变体")))

            tg.start_soon(call)
            tg.start_soon(call)

        assert spy.call_count == 1
        assert results == [False, False]

    async def test_aclose_stops_and_lazy_rebuilds(
        self,
        make_sparse_filter: MakeSparseTextualFilter,
        make_message: MakeMessage,
    ) -> None:
        sut = make_sparse_filter(["文档一"])
        await sut.start()
        await sut.aclose()
        assert sut.running is False
        assert await sut.filter(make_message("无关消息")) is True
        assert sut.running is True  # Using the filter again rebuilds lazily.

    async def test_client_orchestration_starts_and_closes(
        self,
        make_sparse_filter: MakeSparseTextualFilter,
    ) -> None:
        sut = make_sparse_filter(["文档一"])
        config = BitongueConfig(
            flowing_size=8,
            flowing_timeout=30,
            handle_timeout=30,
        )
        client = Bitongue(config, handler=_EchoHandler(), filters=[sut])
        await client.start()
        assert sut.running is True
        await client.shutdown()
        assert sut.running is False


class TestVerdict:
    """Duplicate interception: similar → rejected; unrelated, empty text,
    or empty-token messages → released."""

    async def test_exact_duplicate_rejected(
        self,
        make_sparse_filter: MakeSparseTextualFilter,
        make_message: MakeMessage,
    ) -> None:
        sut = make_sparse_filter(
            ["已知违规文案示例 alpha", "another known reference beta"],
        )
        assert await sut.filter(make_message("已知违规文案示例 alpha")) is False

    async def test_variant_duplicate_rejected(
        self,
        make_sparse_filter: MakeSparseTextualFilter,
        make_message: MakeMessage,
    ) -> None:
        sut = make_sparse_filter(
            ["已知违规文案示例 alpha", "another known reference beta"],
        )
        assert await sut.filter(make_message("已知违规文案示例 alpha 修改版")) is False

    async def test_unrelated_released(
        self,
        make_sparse_filter: MakeSparseTextualFilter,
        make_message: MakeMessage,
    ) -> None:
        sut = make_sparse_filter(
            ["已知违规文案示例 alpha", "another known reference beta"],
        )
        assert await sut.filter(make_message("completely unrelated gibberish")) is True

    async def test_empty_text_released_without_initialization(
        self,
        make_sparse_filter: MakeSparseTextualFilter,
    ) -> None:
        sut = make_sparse_filter(["文档一"])
        assert await sut.filter(TextualMessage(id=uuid4())) is True
        assert sut.running is False  # Empty text short-circuits before lazy init.

    async def test_punctuation_only_text_released(
        self,
        make_sparse_filter: MakeSparseTextualFilter,
        make_message: MakeMessage,
    ) -> None:
        sut = make_sparse_filter(["文档一"])
        await sut.start()
        assert await sut.filter(make_message("!!!")) is True  # Empty token vector.

    async def test_unusable_corpus_document_skipped(
        self,
        make_sparse_filter: MakeSparseTextualFilter,
        make_message: MakeMessage,
    ) -> None:
        # Symbol-only corpus documents are skipped on seeding and do not
        # affect startup or the verdicts of the remaining documents.
        sut = make_sparse_filter(["正常违规文案", "!!!"])
        await sut.start()
        assert sut.running is True
        assert await sut.filter(make_message("正常违规文案")) is False

    async def test_generator_documents_accepted(
        self,
        in_memory_policy: QdrantPolicy,
        make_message: MakeMessage,
    ) -> None:
        # Generator input is materialized at construction, so retries after
        # a failed initialization stay safe.
        sut: SparseTextualFilter[TextualMessage] = SparseTextualFilter(
            f"unit_{uuid4().hex}",
            (doc for doc in ["生成器语料文档"]),
            qdrant_policy=in_memory_policy,
        )
        await sut.start()
        assert await sut.filter(make_message("生成器语料文档")) is False


class TestNonChineseBranch:
    """Non-Chinese branch: model_name required; fastembed's Bm25 covered by a
    stub, never hitting the network."""

    async def test_missing_model_name_rejected(
        self,
        in_memory_policy: QdrantPolicy,
    ) -> None:
        sut: SparseTextualFilter[TextualMessage] = SparseTextualFilter(
            f"unit_{uuid4().hex}",
            ["doc"],
            embed_policy=Bm25Policy(language="english"),
            qdrant_policy=in_memory_policy,
        )
        with pytest.raises(ValueError, match="model_name"):
            await sut.start()

    async def test_builds_with_stubbed_fastembed_bm25(
        self,
        in_memory_policy: QdrantPolicy,
        make_message: MakeMessage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        indices = np.array([101, 102], dtype=np.int64)

        def stub_embedding() -> SparseEmbedding:
            return SparseEmbedding(indices=indices, values=np.ones_like(indices))

        class _StubBm25:
            def __init__(self, **_kwargs: object) -> None:
                return

            def embed(
                self,
                documents: Sequence[str],
                **_kwargs: object,
            ) -> Iterator[SparseEmbedding]:
                return (stub_embedding() for _ in documents)

            def query_embed(
                self,
                query: object,
                **_kwargs: object,
            ) -> Iterator[SparseEmbedding]:
                return iter([stub_embedding()])

        monkeypatch.setattr("bitongue.filter.sparse.filter.Bm25", _StubBm25)

        sut: SparseTextualFilter[TextualMessage] = SparseTextualFilter(
            f"unit_{uuid4().hex}",
            ["stub document"],
            embed_policy=Bm25Policy(model_name="stub/model", language="english"),
            qdrant_policy=in_memory_policy,
            filter_threshold=0.01,
        )
        # The query vector matches the corpus point exactly; a low threshold
        # must reject.
        assert await sut.filter(make_message("anything")) is False
