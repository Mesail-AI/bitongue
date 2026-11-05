"""Tests for bitongue.client.config."""

from bitongue.client import BitongueConfig


class TestBitongueConfig:
    """Default knob values."""

    def test_event_timeout_defaults_to_none(self) -> None:
        config = BitongueConfig(buffer_size=8)

        assert config.event_timeout is None

    def test_fields_round_trip_through_serialization(self) -> None:
        config = BitongueConfig(buffer_size=4, event_timeout=1.5)

        assert BitongueConfig.from_json(config.to_json()) == config
