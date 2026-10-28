from pathlib import Path
from typing import Any

from bitongue.base import BaseStruct

from .stemmer import Stemmer

__all__ = (
    "Bm25Policy",
    "QdrantPolicy",
)


class Bm25Policy(BaseStruct):
    """Runtime configuration for BM25 sparse embedding.

    These are runtime-only knobs: a policy is consumed when a
    :class:`SparseTextualFilter` builds its embedding and is never
    serialized — fields holding objects or paths (``stemmer``,
    ``stopwords``, ``stopwords_filepath``) sit outside the
    ``BaseStruct`` JSON contract, so ``to_json``/``from_json`` are not
    supported on this type.

    For ``language="chinese"`` the embedding is the local
    :class:`Bm25CN` implementation, which needs no model download and
    ignores ``model_name``, ``cache_dir``, and
    ``specific_model_path``. Any other language selects fastembed's
    ``Bm25``, which requires a valid ``model_name`` and downloads the
    model on first use.

    Attributes:
        model_name: fastembed BM25 model name; required for non-Chinese
            languages (empty means unset), ignored for ``"chinese"``.
        cache_dir: Model cache directory for fastembed downloads.
        k: BM25 term-frequency saturation parameter (k1).
        b: BM25 length-normalization parameter.
        avg_len: Assumed average document length.
        language: Embedding language; ``"chinese"`` selects the local
            implementation, anything else selects fastembed's ``Bm25``.
        token_max_length: Tokens longer than this are dropped.
        disable_stemmer: Disable stemming.
        specific_model_path: Local model file path (non-Chinese only).
        stemmer: Custom stemmer instance.
        stopwords: Stopword set overriding the built-in defaults.
        stopwords_filepath: File to load stopwords from, one per line.
    """

    model_name: str = ""
    cache_dir: str | None = None
    k: float = 1.2
    b: float = 0.75
    avg_len: float = 256.0
    language: str = "chinese"
    token_max_length: int = 40
    disable_stemmer: bool = False
    specific_model_path: str | None = None
    stemmer: Stemmer | None = None
    stopwords: set[str] | None = None
    stopwords_filepath: Path | None = None


class QdrantPolicy(BaseStruct):
    """Connection settings for the qdrant client.

    Field names mirror the ``AsyncQdrantClient`` constructor signature;
    the policy is expanded verbatim via ``to_dict`` when the client is
    built, so field names and qdrant-client upgrades must be kept in
    step.

    Exactly one of ``location``, ``url``, ``host``, ``path`` identifies
    the target — qdrant-client rejects combinations. The default
    ``host="localhost"`` yields a server client on ``localhost:6333``;
    for an in-memory client set ``location=":memory:"`` and leave the
    other identifiers unset (``host=None`` included).

    Attributes:
        host: Server host; must be ``None`` when ``location``, ``url``,
            or ``path`` is used.
        location: Target shorthand such as ``":memory:"``.
        path: Local persistence directory.
        url: Full qdrant server URL.
        port: REST port for host-based connections.
        grpc_port: gRPC port for host-based connections.
        prefer_grpc: Prefer the gRPC interface where available.
        https: Use TLS for host-based connections.
        api_key: Bearer credential for qdrant cloud or a secured server.
        prefix: URL path prefix in front of the REST API.
        timeout: REST request timeout in seconds.
        grpc_options: Extra options for the gRPC channel.
        pool_size: Connection pool size.
        headers: Extra HTTP headers for REST calls.
    """

    host: str | None = "localhost"
    location: str | None = None
    path: str | None = None
    url: str | None = None

    port: int = 6333
    grpc_port: int = 6334
    prefer_grpc: bool = False

    https: bool | None = None
    api_key: str | None = None
    prefix: str | None = None
    timeout: int | None = None
    grpc_options: dict[str, Any] | None = None
    pool_size: int | None = None
    headers: dict[str, str] | None = None
