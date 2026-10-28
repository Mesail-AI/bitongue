from typing import TYPE_CHECKING

import anyio
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import StructuredMessage
from autogen_core.model_context import BufferedChatCompletionContext
from autogen_core.models import SystemMessage, UserMessage
from pydantic import BaseModel

from bitongue.filter.protocols import BaseFilter, FilterLifecycle
from bitongue.flow import TextualMessage

from .provider import OpenAIClientProvider

if TYPE_CHECKING:
    from autogen_core.model_context import ChatCompletionContext
    from autogen_ext.models.openai import OpenAIChatCompletionClient

    from .policy import NeuroFilterPolicy


__all__ = ("NeuroTextualFilter",)


class _NeuroFilterResult(BaseModel):
    """Structured message result for neuro filter."""

    filtered: bool


class NeuroTextualFilter[T: TextualMessage](BaseFilter, FilterLifecycle):
    """Reject messages whose text violates caller-supplied rules, judged by a model.

    Every candidate is handed to an autogen ``AssistantAgent`` backed by
    any OpenAI-compatible chat endpoint: the filtering rules and the
    message text travel as one exchange, the model answers with a
    structured verdict, and a verdict of ``filtered=True`` rejects the
    message. Under the ``BaseFilter`` contract the outcome inverts — a
    model that considers the text clean releases it.

    The gate fails open only where no model call is involved: a message
    without a text payload and rules that normalize to nothing both
    release the message. Everything on the model-call path raises on
    failure — a response that does not match the verdict schema, a
    backend error, or a call that outlives the policy timeout (which
    surfaces as ``TimeoutError``, after which the client's own timeout
    contract skips the message silently). Errors are never swallowed
    here; every one propagates to the caller of :meth:`filter`.

    The conversation buffer is cleared after every verdict, so each
    message is judged in isolation and no text crosses over between
    messages. Calls on one instance are not safe to run concurrently;
    the client's single-consumer pipeline already serializes them.

    The constructor stores the policy and contacts nothing;
    :meth:`start` — called by a :class:`bitongue.client.Bitongue`
    client when the filter is handed to it — builds the agent and the
    model client, and :meth:`filter` raises :class:`RuntimeError`
    before that. Standalone use works the same way: call
    :meth:`start` once and :meth:`aclose` when done. The verdict type
    is a pydantic model because autogen's structured output requires
    one; this is the library's single deliberate exception to its
    msgspec convention.
    """

    def __init__(self, policy: "NeuroFilterPolicy") -> None:

        self._policy = policy

        self._context: ChatCompletionContext | None = None
        self._agent: AssistantAgent | None = None
        self._client: OpenAIChatCompletionClient | None = None

        self._running = False

    @property
    def running(self) -> bool:

        return self._running

    def _ensure_runtime(
        self,
    ) -> tuple[
        "ChatCompletionContext",
        "AssistantAgent",
    ]:

        if self._context is None:
            self._context = BufferedChatCompletionContext(buffer_size=10)

        if self._client is None:
            self._client = OpenAIClientProvider(
                base_url=self._policy.base_url,
                api_key=self._policy.api_key,
                model=self._policy.model,
            ).provide()

        if self._agent is None:
            self._agent = AssistantAgent(
                name="neuro_filter",
                description="An intelligent assistant designed to assist with filtering messages.",
                model_client=self._client,
                model_context=self._context,
                output_content_type=_NeuroFilterResult,
            )

        return self._context, self._agent

    async def start(self) -> None:

        if self._running:
            return

        self._ensure_runtime()

        self._running = True

    async def aclose(self) -> None:

        if not self._running:
            return

        if self._agent is not None:
            await self._agent.close()
            self._agent = None

        if self._context is not None:
            await self._context.clear()
            self._context = None

        if self._client is not None:
            await self._client.close()
            self._client = None

        self._running = False

    async def filter(self, message: "T") -> bool:
        """Judge the message against the policy rules with one model call.

        Returns:
            ``False`` when the model verdict marks the text as filtered;
            ``True`` when the message carries no text payload, the rules
            normalize to nothing, or the verdict releases it.

        Raises:
            RuntimeError: If the filter has not been started.
            ValueError: If the model response does not match the verdict
                schema.
            TimeoutError: If the model call outlives the policy timeout.
            Exception: Any other error from the model call propagates
                unchanged.
        """

        if not self._running:
            raise RuntimeError("NeuroTextualFilter is not running.")

        if message.type != "text" or not message.text:
            # Skip non-text messages
            return True

        if not (
            rules := (
                "\n".join(self._policy.rules)
                if isinstance(self._policy.rules, list)
                else self._policy.rules
            )
        ).strip():
            # Skip empty or whitespace-only rules
            return True

        context, agent = self._ensure_runtime()
        filtered = False

        try:
            await context.add_message(message=SystemMessage(content=rules))
            await context.add_message(
                message=UserMessage(
                    content="Output filtered conclusion follow instructions and rules: "
                    "`True` means rejected, `False` means released.",
                    source="system",
                )
            )
            await context.add_message(
                message=UserMessage(
                    content=message.text,
                    source="user",
                )
            )

            with anyio.fail_after(delay=self._policy.timeout):
                match (await agent.run()).messages[-1]:
                    case StructuredMessage() as result:
                        if isinstance(result.content, _NeuroFilterResult):
                            filtered = result.content.filtered
                    case _:
                        # Unexpected message type, handle failed, release.
                        filtered = False

        finally:
            # Clear message context after processing.
            await context.clear()

        return not filtered
