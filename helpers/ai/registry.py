"""The single swap point for the model backend.

Adding a provider = one new file implementing `LLMProvider` + one entry here.
Nothing else in the app names a vendor.
"""

import os

from helpers.ai.provider import LLMProvider, ProviderError
from settings import get_settings

DEFAULT_PROVIDER = "gemini"


def _builders() -> dict[str, type[LLMProvider]]:
    """Registered provider constructors, keyed by their `ASSISTANT_PROVIDER` name.

    Returns:
        dict[str, type[LLMProvider]]: Provider name -> class implementing `LLMProvider`.
    """
    from helpers.ai.gemini import GeminiProvider

    return {"gemini": GeminiProvider}


def get_provider(name: str | None = None) -> LLMProvider:
    """Instantiate the configured (or requested) LLM provider. A PR preview always gets the
    scripted one: it holds no key, and no setting may point it at a real model.

    Args:
        name (str | None): Provider name to force; defaults to
            `ASSISTANT_PROVIDER` env var, then `DEFAULT_PROVIDER`.

    Returns:
        LLMProvider: A new instance of the resolved provider.
    """
    if get_settings().is_preview:
        from helpers.ai.scripted import ScriptedProvider

        return ScriptedProvider()
    key = (name or os.environ.get("ASSISTANT_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    builders = _builders()
    if key not in builders:
        raise ProviderError(
            f"Unknown ASSISTANT_PROVIDER {key!r}. Available: {', '.join(sorted(builders))}."
        )
    return builders[key]()
