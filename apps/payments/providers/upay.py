"""
Upay (UCB Fintech) merchant payment API.

NOTE: Upay shares its merchant API documentation only during merchant
onboarding. This implementation follows the commonly deployed v1 merchant flow
(auth → payment-init → redirect → single-payment-status). Base URL and paths
are overridable from the environment so they can be aligned with the official
document without code changes; verify against it before enabling in live mode.
"""
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from ..models import PaymentAttempt
from ..services import PaymentError, mark_failed, mark_succeeded
from .base import BasePaymentProvider, VerifyResult
from .http import call, env

SANDBOX = "https://uat-pg.upay.systems"
LIVE = "https://pg.upaysystem.com"


class UpayProvider(BasePaymentProvider):
    code = "upay"

    @property
    def base(self):
        return env("UPAY_BASE_URL") or (SANDBOX if self.sandbox else LIVE)

    def _token(self) -> str:
        merchant_id, key = env("UPAY_MERCHANT_ID"), env("UPAY_MERCHANT_KEY")
        if not merchant_id or not key:
            raise PaymentError("Upay credentials are not configured")
        cache_key = f"upay:token:{'sb' if self.sandbox else 'live'}"
        token = cache.get(cache_key)
        if token:
            return token
        data = call(
            "POST",
            f"{self.base}{env('UPAY_AUTH_PATH', '/payment/merchant-auth/')}",
            provider=self.code,
            json={"merchant_id": merchant_id, "merchant_key": key},
        )
        token = (data.get("data") or {}).get("token")
        if not token:
            raise PaymentError(f"Upay auth failed: {data.get('message')}")
        cache.set(cache_key, token, 50 * 60)
        return token

    def _headers(self):
        return {"Authorization": f"UPAY {self._token()}", "Content-Type": "application/json"}

    def initiate(self, attempt, request) -> str:
        redirect = settings.SITE_URL + reverse("payments:return", kwargs={"provider": self.code})
        data = call(
            "POST",
            f"{self.base}{env('UPAY_INIT_PATH', '/payment/merchant-payment-init/')}",
            provider=self.code,
            headers=self._headers(),
            json={
                "date": timezone.localdate().isoformat(),
                "txn_id": attempt.tran_id,
                "invoice_id": attempt.order.reference,
                "amount": float(attempt.amount),
                "merchant_id": env("UPAY_MERCHANT_ID"),
                "merchant_name": env("UPAY_MERCHANT_NAME", "Nexopay"),
                "merchant_code": env("UPAY_MERCHANT_CODE"),
                "merchant_country_code": "BD",
                "merchant_city": "Dhaka",
                "merchant_category_code": env("UPAY_MERCHANT_CATEGORY_CODE", "7922"),
                "merchant_mobile": env("UPAY_MERCHANT_MOBILE"),
                "transaction_currency_code": "BDT",
                "redirect_url": f"{redirect}?tran_id={attempt.tran_id}",
            },
        )
        attempt.log("init", data)
        url = (data.get("data") or {}).get("gateway_url")
        if not url:
            attempt.save(update_fields=["raw", "updated_at"])
            raise PaymentError(f"Upay init failed: {data.get('message')}")
        attempt.provider_ref = (data.get("data") or {}).get("session_id", "") or attempt.tran_id
        attempt.save(update_fields=["provider_ref", "raw", "updated_at"])
        return url

    def _status(self, attempt) -> dict:
        path = env("UPAY_STATUS_PATH", "/payment/single-payment-status/{txn_id}/").format(txn_id=attempt.tran_id)
        return call("GET", f"{self.base}{path}", provider=self.code, headers=self._headers())

    def verify(self, attempt) -> VerifyResult:
        data = self._status(attempt)
        info = data.get("data") or {}
        status = str(info.get("status", "")).lower()
        if status == "success" and Decimal(str(info.get("amount", "0"))) == attempt.amount:
            return VerifyResult(PaymentAttempt.Status.SUCCEEDED, str(info.get("trx_id") or info.get("txn_id")), data)
        if status in ("failed", "cancelled", "canceled", "expired"):
            return VerifyResult(PaymentAttempt.Status.FAILED, payload=data)
        return VerifyResult(PaymentAttempt.Status.INITIATED, payload=data)

    def handle_return(self, request):
        attempt = self.attempt_for(request.GET.get("tran_id", ""))
        if attempt is None:
            return None
        result = self.verify(attempt)
        if result.status == PaymentAttempt.Status.SUCCEEDED:
            mark_succeeded(attempt, result.provider_txn_id, result.payload)
        elif result.status == PaymentAttempt.Status.FAILED:
            mark_failed(attempt, payload=result.payload)
        return attempt
