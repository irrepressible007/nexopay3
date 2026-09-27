import logging

import requests
from django.conf import settings

from ..services import PaymentError

logger = logging.getLogger("apps.payments")


def call(method: str, url: str, *, provider: str, **kwargs) -> dict:
    """JSON request with a short timeout; any transport/HTTP/JSON problem becomes PaymentError."""
    kwargs.setdefault("timeout", settings.NEXOPAY["PAYMENT_HTTP_TIMEOUT"])
    try:
        response = requests.request(method, url, **kwargs)
    except requests.RequestException as exc:
        logger.warning("%s %s failed: %s", provider, url, exc)
        raise PaymentError(f"{provider}: could not reach the provider") from exc
    try:
        data = response.json()
    except ValueError as exc:
        logger.warning("%s %s returned non-JSON (%s): %.300s", provider, url, response.status_code, response.text)
        raise PaymentError(f"{provider}: unexpected response") from exc
    if response.status_code >= 500:
        raise PaymentError(f"{provider}: provider error {response.status_code}")
    return data


def env(name: str, default: str = "") -> str:
    from nexopay.settings.base import env as _env

    return _env(name, default=default)
