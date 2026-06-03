"""LLM singleton — shared across all agent nodes."""
from functools import lru_cache

from langchain_anthropic import ChatAnthropic

from finance_analytics.config import get_settings


@lru_cache
def get_llm() -> ChatAnthropic:
    settings = get_settings()
    return ChatAnthropic(
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
    )
