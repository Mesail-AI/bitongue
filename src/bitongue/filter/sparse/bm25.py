"""Local Chinese BM25 sparse embedding on top of fastembed."""

import os
import re
from collections import defaultdict
from collections.abc import Iterable
from multiprocessing import get_all_start_methods
from typing import TYPE_CHECKING, Any, Self

import mmh3
import numpy as np
from fastembed.common.utils import (
    iter_batch,
    remove_non_alphanumeric,
)
from fastembed.parallel_processor import (
    ParallelWorkerPool,
    Worker,
)
from fastembed.sparse.bm25 import Bm25
from fastembed.sparse.sparse_embedding_base import (
    SparseEmbedding,
    SparseTextEmbeddingBase,
)

from bitongue.filter.utils import Normalizer

from .tokenizer import JiebaTokenizer

if TYPE_CHECKING:
    from pathlib import Path

    from fastembed.sparse.bm25 import Stemmer


__all__ = (
    "Bm25",
    "Bm25CN",
)


class Bm25CN(SparseTextEmbeddingBase):
    """Local BM25 sparse embedding for Chinese text.

    Documents are tokenized with :class:`JiebaTokenizer` in search mode,
    filtered through punctuation, stopword, and length rules, then
    mapped to stable token IDs with ``mmh3``. Document-side vectors
    carry BM25 term-frequency weights (:meth:`embed`); query-side
    vectors are binary token sets (:meth:`query_embed`), the shape
    qdrant's IDF modifier expects on the query.

    Everything runs locally — jieba's dictionary ships with the
    package — so construction needs no network access.

    Attributes:
        language: Embedding language; kept for introspection only, this
            implementation always applies Chinese-oriented rules.
        k: BM25 term-frequency saturation parameter (k1).
        b: BM25 length-normalization parameter.
        avg_len: Assumed average document length.
        token_max_length: Tokens longer than this are dropped.
        punctuation_regex: Pattern whose matches count as punctuation
            and are dropped from tokens.
        disable_stemmer: Whether stemming is disabled.
        stopwords: Stopword set applied during stemming.
        stemmer: Optional custom stemmer applied to lowercase tokens.
        tokenizer: Tokenizer class producing the input tokens.
    """

    def __init__(
        self,
        k: float = 1.2,
        b: float = 0.75,
        avg_len: float = 256.0,
        language: str = "chinese",
        token_max_length: int = 40,
        disable_stemmer: bool = False,
        stemmer: "Stemmer | None" = None,
        stopwords: set[str] | None = None,
        stopwords_filepath: "Path | None" = None,
    ) -> None:

        if disable_stemmer and stemmer is not None:
            raise ValueError(
                "stemmer cannot be supplied with disable_stemmer=True",
            )

        self.language = language

        self._custom_stemmer = stemmer
        self._custom_stopwords = (
            {word.lower() for word in stopwords} if stopwords is not None else None
        )
        self._custom_stopwords_filepath = stopwords_filepath

        self.k = k
        self.b = b
        self.avg_len = avg_len

        self.token_max_length = token_max_length
        self.punctuation_regex = re.compile(
            r"[^\u4e00-\u9fffa-zA-Z0-9+\-#_.@&%/\s]",
        )
        self.disable_stemmer = disable_stemmer

        self.stopwords: set[str]
        if self._custom_stopwords is not None:
            self.stopwords = self._custom_stopwords
        elif disable_stemmer:
            self.stopwords = set()
        else:
            self.stopwords = set(
                self._load_stopwords(
                    self._custom_stopwords_filepath,
                ),
            )

        self.stemmer = stemmer
        self.tokenizer = JiebaTokenizer

    @classmethod
    def _load_stopwords(cls, filepath: "Path | None") -> list[str]:
        """Load normalized stopwords from a file, one entry per line."""

        if filepath is None:
            return []

        return Normalizer.normalize(
            *filepath.read_text(encoding="utf-8").splitlines(),
        )

    def _embed_documents(
        self,
        documents: str | Iterable[str],
        batch_size: int = 256,
        parallel: int | None = None,
    ) -> Iterable["SparseEmbedding"]:

        is_small = False

        if isinstance(documents, str):
            documents = [documents]
            is_small = True

        if isinstance(documents, list) and len(documents) < batch_size:
            is_small = True

        if parallel is None or is_small:
            for batch in iter_batch(documents, batch_size):
                yield from self.raw_embed(batch)

        else:
            if parallel == 0:
                parallel = os.cpu_count()

            start_method = (
                "forkserver" if "forkserver" in get_all_start_methods() else "spawn"
            )

            params = {
                "k": self.k,
                "b": self.b,
                "avg_len": self.avg_len,
                "language": self.language,
                "token_max_length": self.token_max_length,
                "disable_stemmer": self.disable_stemmer,
                "stemmer": self._custom_stemmer,
                "stopwords": self._custom_stopwords,
                "stopwords_filepath": self._custom_stopwords_filepath,
            }

            pool = ParallelWorkerPool(
                num_workers=parallel or 1,
                worker=self._get_worker_class(),
                start_method=start_method,
            )

            for batch in pool.ordered_map(
                iter_batch(documents, batch_size),
                **params,
            ):
                yield from batch

    def embed(
        self,
        documents: str | Iterable[str],
        batch_size: int = 256,
        parallel: int | None = None,
        **kwargs: Any,
    ) -> Iterable["SparseEmbedding"]:
        """Embed documents with BM25 term-frequency weights.

        Args:
            documents: A single document or an iterable of documents.
            batch_size: Number of documents per embedding batch.
            parallel: Number of worker processes; ``None`` embeds
                in-process.
            kwargs: Accepted for signature compatibility with the
                fastembed base class; ignored.

        Yields:
            One sparse embedding per input document, in input order.
        """

        yield from self._embed_documents(
            documents=documents,
            batch_size=batch_size,
            parallel=parallel,
        )

    def _stem(self, tokens: list[str]) -> list[str]:
        """Apply the punctuation, stopword, length, and stemming rules.

        Args:
            tokens: Raw tokens to filter and stem.

        Returns:
            Surviving tokens, lowercased and stemmed where a stemmer is
            configured.
        """

        stemmed_tokens: list[str] = []

        for token in tokens:
            lower_token = token.lower()

            if not self.punctuation_regex.sub(" ", token).strip():
                continue

            if lower_token in self.stopwords:
                continue

            if len(token) > self.token_max_length:
                continue

            stemmed_token = (
                self.stemmer.stem_word(
                    lower_token,
                )
                if self.stemmer
                else token
            )

            if stemmed_token:
                stemmed_tokens.append(stemmed_token)

        return stemmed_tokens

    def raw_embed(self, documents: list[str]) -> list["SparseEmbedding"]:
        """Embed documents one by one, in-process.

        Args:
            documents: Documents to embed.

        Returns:
            Exactly one sparse embedding per input document, in input
            order. Documents that normalize to no usable token produce
            an empty embedding — callers that seed a collection should
            skip those.
        """

        embeddings: list[SparseEmbedding] = []

        for document in documents:
            document = remove_non_alphanumeric(document)
            tokens = self.tokenizer.tokenize(document)
            stemmed_tokens = self._stem(tokens)
            token_id2value = self._term_frequency(stemmed_tokens)
            embeddings.append(SparseEmbedding.from_dict(token_id2value))

        return embeddings

    def token_count(self, texts: str | Iterable[str], **kwargs: Any) -> int:
        """Count tokenizer tokens across texts.

        Args:
            texts: A single text or an iterable of texts.
            kwargs: Accepted for signature compatibility with the
                fastembed base class; ignored.

        Returns:
            Total number of tokens produced by the tokenizer.
        """

        token_num = 0

        for text in [texts] if isinstance(texts, str) else texts:
            document = remove_non_alphanumeric(text)
            tokens = self.tokenizer.tokenize(document)
            token_num += len(tokens)

        return token_num

    def _term_frequency(self, tokens: list[str]) -> dict[int, float]:
        """Calculate the term frequency part of the BM25 formula.

        (
            f(q_i, d) * (k + 1)
        ) / (
            f(q_i, d) + k * (1 - b + b * (|d| / avg_len))
        )

        Args:
            tokens: The list of tokens in the document.

        Returns:
            The token_id to term frequency mapping.
        """

        tf_map: dict[int, float] = {}
        counter: defaultdict[str, int] = defaultdict(int)

        for stemmed_token in tokens:
            counter[stemmed_token] += 1

        doc_len = len(tokens)
        for stemmed_token in counter:
            token_id = self.compute_token_id(stemmed_token)
            num_occurrences = counter[stemmed_token]
            tf_map[token_id] = num_occurrences * (self.k + 1)
            tf_map[token_id] /= num_occurrences + self.k * (
                1 - self.b + self.b * doc_len / self.avg_len
            )

        return tf_map

    @classmethod
    def compute_token_id(cls, token: str) -> int:
        """Map a token to its stable sparse-vector dimension id."""

        return abs(mmh3.hash(token))

    def query_embed(
        self,
        query: str | Iterable[str],
        **kwargs: Any,
    ) -> Iterable["SparseEmbedding"]:
        """Embed queries as binary token sets.

        Unlike :meth:`embed`, query vectors carry no term-frequency
        weights — every surviving token contributes ``1`` — which is the
        query shape qdrant's IDF modifier expects.

        Args:
            query: A single query or an iterable of queries.
            kwargs: Accepted for signature compatibility with the
                fastembed base class; ignored.

        Yields:
            One sparse embedding per input query, in input order.
        """

        for text in [query] if isinstance(query, str) else query:
            text = remove_non_alphanumeric(text)
            tokens = self.tokenizer.tokenize(text)
            stemmed_tokens = self._stem(tokens)
            token_ids = np.array(
                list({self.compute_token_id(token) for token in stemmed_tokens}),
                dtype=np.int64,
            )
            values = np.ones_like(token_ids)

            yield SparseEmbedding(indices=token_ids, values=values)

    @classmethod
    def _get_worker_class(cls) -> type["Bm25CNWorker"]:

        return Bm25CNWorker


class Bm25CNWorker(Worker):
    """Parallel-pool worker embedding batches with a private model."""

    def __init__(self, **kwargs: Any) -> None:

        self.model = self.init_embedding(**kwargs)

    @classmethod
    def start(cls, **kwargs: Any) -> Self:

        return cls(**kwargs)

    def process(
        self,
        items: Iterable[tuple[int, Any]],
    ) -> Iterable[tuple[int, list["SparseEmbedding"]]]:

        for idx, batch in items:
            onnx_output = self.model.raw_embed(batch)
            yield idx, onnx_output

    @staticmethod
    def init_embedding(**kwargs: Any) -> "Bm25CN":
        """Instantiate a :class:`Bm25CN` from pooled keyword args."""

        return Bm25CN(**kwargs)
