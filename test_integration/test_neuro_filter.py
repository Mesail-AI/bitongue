"""NeuroTextualFilter integration tests against a real OpenAI-compatible endpoint.

Connection: ``BITONGUE_TEST_NEURO_BASE_URL``, ``BITONGUE_TEST_NEURO_API_KEY``
and ``BITONGUE_TEST_NEURO_MODEL`` must all be set; the suite skips
otherwise. Unlike qdrant there is no free liveness probe, so endpoint
reachability itself is part of what these tests exercise.
"""

import os
from uuid import uuid4

import pytest

from bitongue.client import Bitongue, BitongueConfig
from bitongue.filter.neuro import NeuroFilterPolicy, NeuroTextualFilter
from bitongue.flow import TextualMessage
from test_integration.conftest import ScriptedHandler

pytestmark = pytest.mark.integration


def _policy_from_env() -> NeuroFilterPolicy:
    return NeuroFilterPolicy(
        base_url=os.environ["BITONGUE_TEST_NEURO_BASE_URL"],
        api_key=os.environ["BITONGUE_TEST_NEURO_API_KEY"],
        model=os.environ["BITONGUE_TEST_NEURO_MODEL"],
        rules="Reject messages that contain profanity or abuse.",
        timeout=30,
    )


@pytest.fixture
def real_neuro_policy() -> NeuroFilterPolicy:
    required = (
        "BITONGUE_TEST_NEURO_BASE_URL",
        "BITONGUE_TEST_NEURO_API_KEY",
        "BITONGUE_TEST_NEURO_MODEL",
    )
    if not all(os.environ.get(name) for name in required):
        pytest.skip("neuro endpoint not configured (BITONGUE_TEST_NEURO_*)")
    return _policy_from_env()


class TestRealEndpoint:
    """A verdict round trip and client orchestration against the real
    endpoint; verdict content is the model's call, so only the contract
    shape is asserted."""

    async def test_filter_returns_a_bool_verdict(
        self,
        real_neuro_policy: NeuroFilterPolicy,
    ) -> None:
        sut: NeuroTextualFilter[TextualMessage] = NeuroTextualFilter(real_neuro_policy)
        await sut.start()
        try:
            verdict = await sut.filter(
                TextualMessage(id=uuid4(), text="A plain friendly hello."),
            )
        finally:
            await sut.aclose()
        assert isinstance(verdict, bool)

    async def test_client_orchestration_starts_and_closes(
        self,
        real_neuro_policy: NeuroFilterPolicy,
    ) -> None:
        sut: NeuroTextualFilter[TextualMessage] = NeuroTextualFilter(real_neuro_policy)
        config = BitongueConfig(
            flowing_size=8,
            flowing_timeout=30,
            handle_timeout=60,
        )
        client = Bitongue(config, handler=ScriptedHandler(), filters=[sut])
        await client.start()
        assert sut.running is True
        await client.shutdown()
        assert sut.running is False
