from bitongue.base import BaseStruct

__all__ = ("NeuroFilterPolicy",)


class NeuroFilterPolicy(BaseStruct):
    """Connection and rule configuration for :class:`NeuroTextualFilter`.

    Attributes:
        base_url: Base URL of an OpenAI-compatible chat endpoint.
        api_key: API key for the endpoint. The policy serializes with
            the ordinary ``BaseStruct`` helpers, so ``to_json`` carries
            the key — treat a serialized policy as secret material.
        model: Model name requested from the endpoint.
        rules: Rules the model judges message text against. A list is
            joined into one rule block with newlines; a single string is
            used verbatim. Rules that normalize to nothing release every
            message.
        timeout: Seconds allowed for one model verdict; a call that
            outlives it raises ``TimeoutError``. Defaults to 10.
    """

    base_url: str
    api_key: str
    model: str

    rules: str | list[str]
    timeout: float = 10.0
