from app.core.config import Settings
from app.ml.base import MLClient, MLClientError
from app.ml.http import HttpMLClient
from app.ml.mock import MockMLClient


def build_ml_client(settings: Settings) -> MLClient:
    if settings.ml_provider == "http":
        if not settings.ml_service_url:
            raise RuntimeError("ML_SERVICE_URL is required when ML_PROVIDER=http")
        return HttpMLClient(
            settings.ml_service_url,
            timeout_s=settings.ml_timeout_s,
            max_retries=settings.ml_max_retries,
        )
    return MockMLClient(delay_s=settings.ml_mock_delay_s)


__all__ = ["HttpMLClient", "MLClient", "MLClientError", "MockMLClient", "build_ml_client"]
