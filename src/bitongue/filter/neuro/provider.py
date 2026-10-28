from autogen_ext.models.openai import OpenAIChatCompletionClient

__all__ = ("OpenAIClientProvider",)


class OpenAIClientProvider:
    """Build the OpenAI-compatible model client used by NeuroTextualFilter.

    The customization point for endpoints and backend quirks: each
    :meth:`provide` call builds a fresh ``OpenAIChatCompletionClient``
    from the configured base URL, API key, and model name. The built
    client claims vision, function calling, JSON output, and structured
    output support, because autogen needs those claims to request
    structured verdicts. When adapting to a backend whose model lacks
    any of them, declare the real capabilities here — a model that
    cannot answer with JSON-schema output fails at call time.
    """

    def __init__(self, base_url: str, api_key: str, model: str) -> None:

        self._base_url = base_url
        self._api_key = api_key
        self._model = model

    def provide(self) -> "OpenAIChatCompletionClient":

        return OpenAIChatCompletionClient(
            model=self._model,
            base_url=self._base_url,
            api_key=self._api_key,
            model_info={
                "vision": True,
                "function_calling": True,
                "json_output": True,
                "family": "unknown",
                "structured_output": True,
            },
        )
