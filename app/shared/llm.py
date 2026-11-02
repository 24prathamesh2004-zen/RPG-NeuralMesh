"""Shared LLM factory — returns AzureChatOpenAI configured from settings."""
from __future__ import annotations

from langchain_openai import AzureChatOpenAI

from shared.config import get_settings


def get_llm(max_tokens: int = 512, streaming: bool = True) -> AzureChatOpenAI:
    settings = get_settings()
    # Strip deployment path if the user provided the full URL, e.g.
    # https://host.azure.com/openai/deployments/... -> https://host.azure.com
    endpoint = settings.azure_openai_endpoint
    if "/openai" in endpoint:
        endpoint = endpoint.split("/openai")[0]
    return AzureChatOpenAI(
        azure_endpoint=endpoint,
        azure_deployment=settings.azure_openai_deployment,
        openai_api_key=settings.azure_openai_api_key,
        openai_api_version=settings.azure_openai_api_version,
        max_tokens=max_tokens,
        # streaming=True lets OpenAIInstrumentor record a "First Token Stream
        # Event" span event, which Phoenix uses to compute TTFT.
        streaming=streaming,
    )
