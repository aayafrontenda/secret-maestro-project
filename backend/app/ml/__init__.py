from app.core.config import Settings
from app.ml.base import MLClient, MLClientError
from app.ml.http import HttpMLClient
from app.ml.mock import MockMLClient
from app.ml.openai import OpenAIChat, OpenAIMLClient


def build_llm_chat(settings: Settings) -> OpenAIChat | None:
    if not settings.llm_configured:
        return None
    return OpenAIChat(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        timeout_s=settings.openai_timeout_s,
        max_retries=settings.ml_max_retries,
        temperature=settings.openai_temperature,
        price_input_per_1m=settings.openai_price_input_per_1m,
        price_output_per_1m=settings.openai_price_output_per_1m,
    )


def build_ml_client(settings: Settings) -> MLClient:
    if settings.ml_provider == "http":
        if not settings.ml_service_url:
            raise RuntimeError("ML_SERVICE_URL is required when ML_PROVIDER=http")
        return HttpMLClient(
            settings.ml_service_url,
            timeout_s=settings.ml_timeout_s,
            max_retries=settings.ml_max_retries,
        )
    if settings.ml_provider == "openai":
        chat = build_llm_chat(settings)
        if chat is None:
            raise RuntimeError("OPENAI_API_KEY is required when ML_PROVIDER=openai")
        return OpenAIMLClient(
            chat, mask_pii=settings.pii_masking, language=settings.output_language
        )
    return MockMLClient(delay_s=settings.ml_mock_delay_s)


__all__ = [
    "HttpMLClient",
    "MLClient",
    "MLClientError",
    "MockMLClient",
    "OpenAIChat",
    "OpenAIMLClient",
    "build_llm_chat",
    "build_ml_client",
]
