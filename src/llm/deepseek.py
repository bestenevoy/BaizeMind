from langchain_openai import ChatOpenAI

from config.settings import settings
from src.llm.cached_wrapper import wrap_with_cache


def get_chat_llm(temperature: float | None = None, model: str | None = None) -> ChatOpenAI:
    base = ChatOpenAI(
        model=model or settings.deepseek_chat_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=temperature if temperature is not None else settings.agent_temperature,
    )
    return wrap_with_cache(base)


def get_reasoner_llm(temperature: float | None = None) -> ChatOpenAI:
    base = ChatOpenAI(
        model=settings.deepseek_reasoner_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=temperature if temperature is not None else settings.agent_temperature,
    )
    return wrap_with_cache(base)
