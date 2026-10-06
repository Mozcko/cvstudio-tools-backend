from openai import AsyncOpenAI

from src.core.config import settings

LANGUAGE_NAMES = {"es": "Spanish", "en": "English", "pt": "Portuguese"}


class AINotConfiguredError(RuntimeError):
    pass


class AIResponseError(RuntimeError):
    """The provider answered, but not with something we can use."""


_client: AsyncOpenAI | None = None


def get_ai_client() -> tuple[AsyncOpenAI, str]:
    global _client
    if not settings.OPENAI_API_KEY:
        raise AINotConfiguredError("OPENAI_API_KEY is not set")
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client, settings.OPENAI_MODEL
