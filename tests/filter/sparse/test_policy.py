"""Tests for bitongue.filter.sparse.policy."""

from pathlib import Path

import pytest

from bitongue.filter.sparse import Bm25Policy, QdrantPolicy


class TestBm25Policy:
    """Runtime configuration record: defaults, field expansion, serialization."""

    def test_defaults(self) -> None:
        policy = Bm25Policy()
        assert policy.model_name == ""
        assert policy.language == "chinese"
        assert policy.k == 1.2
        assert policy.b == 0.75
        assert policy.disable_stemmer is False
        assert policy.stopwords is None

    def test_to_dict_expands_every_field(self) -> None:
        data = Bm25Policy().to_dict()
        assert set(data) == {
            "model_name",
            "cache_dir",
            "k",
            "b",
            "avg_len",
            "language",
            "token_max_length",
            "disable_stemmer",
            "specific_model_path",
            "stemmer",
            "stopwords",
            "stopwords_filepath",
        }
        assert data["language"] == "chinese"

    def test_to_json_round_trip_without_runtime_objects(self) -> None:
        # The JSON contract holds only while no runtime objects are present.
        policy = Bm25Policy(model_name="m", stopwords={"a", "b"})
        restored = Bm25Policy.from_json(policy.to_json())
        assert restored == policy

    def test_to_json_rejects_path_field(self) -> None:
        policy = Bm25Policy(stopwords_filepath=Path("stopwords.txt"))
        with pytest.raises(TypeError, match="PosixPath"):
            policy.to_json()


class TestQdrantPolicy:
    """Connection policy: defaults target localhost; memory mode needs host=None."""

    def test_defaults_target_localhost(self) -> None:
        policy = QdrantPolicy()
        assert policy.host == "localhost"
        assert policy.location is None
        assert policy.url is None
        assert policy.path is None
        assert policy.port == 6333

    def test_memory_mode_requires_host_none(self) -> None:
        policy = QdrantPolicy(location=":memory:", host=None)
        data = policy.to_dict()
        assert data["location"] == ":memory:"
        assert data["host"] is None
