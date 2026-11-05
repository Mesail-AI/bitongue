"""Tests for bitongue.base.schemas."""

import pytest
from msgspec import DecodeError

from bitongue.base import BaseStruct


class SampleStruct(BaseStruct):
    """Sample struct exercising the serialization surface."""

    zeta: str
    alpha: int
    optional: str | None = None


class TestBaseStruct:
    """to_dict / to_json(b) / from_* round trips and field selection."""

    def test_to_dict_returns_plain_dict(self) -> None:
        sample = SampleStruct(zeta="v", alpha=1)

        assert sample.to_dict() == {"zeta": "v", "alpha": 1, "optional": None}

    def test_to_dict_includes_and_excludes(self) -> None:
        sample = SampleStruct(zeta="v", alpha=1)

        assert sample.to_dict(includes={"zeta"}) == {"zeta": "v"}
        assert sample.to_dict(excludes={"zeta"}) == {"alpha": 1, "optional": None}

    def test_to_dict_exclude_none_drops_none_fields(self) -> None:
        sample = SampleStruct(zeta="v", alpha=1)

        assert sample.to_dict(exclude_none=True) == {"zeta": "v", "alpha": 1}

    def test_from_dict_round_trips(self) -> None:
        sample = SampleStruct(zeta="v", alpha=1)

        assert SampleStruct.from_dict({"zeta": "v", "alpha": 1}) == sample

    def test_to_jsonb_encodes_sorted_bytes(self) -> None:
        sample = SampleStruct(zeta="v", alpha=1)

        assert sample.to_jsonb() == b'{"alpha":1,"optional":null,"zeta":"v"}'

    def test_to_json_sorts_keys(self) -> None:
        sample = SampleStruct(zeta="v", alpha=1)

        assert sample.to_json() == '{"alpha":1,"optional":null,"zeta":"v"}'

    def test_equal_structs_encode_identically(self) -> None:
        # Sorted-key encoding: equal structures produce identical payloads.
        first = SampleStruct(zeta="v", alpha=1)
        second = SampleStruct(zeta="v", alpha=1)

        assert first.to_jsonb() == second.to_jsonb()

    def test_from_json_round_trips(self) -> None:
        sample = SampleStruct(zeta="v", alpha=1)

        assert SampleStruct.from_json(sample.to_json()) == sample

    def test_from_jsonb_round_trips(self) -> None:
        sample = SampleStruct(zeta="v", alpha=1)

        assert SampleStruct.from_jsonb(sample.to_jsonb()) == sample

    def test_from_json_invalid_json_raises_decode_error(self) -> None:
        with pytest.raises(DecodeError):
            SampleStruct.from_json("{not json")

    def test_from_toml_decodes_document(self) -> None:
        text = 'zeta = "v"\nalpha = 1\noptional = "x"\n'

        assert SampleStruct.from_toml(text) == SampleStruct(
            zeta="v",
            alpha=1,
            optional="x",
        )

    def test_from_yaml_decodes_document(self) -> None:
        text = "zeta: v\nalpha: 1\noptional: x\n"

        assert SampleStruct.from_yaml(text) == SampleStruct(
            zeta="v",
            alpha=1,
            optional="x",
        )
