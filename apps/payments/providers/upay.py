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
from .base import BasePaymentProvider, Credential, VerifyResult
from .http import call

SANDBOX = "https://uat-pg.upay.systems"
LIVE = "https://pg.upaysystem.com"


class UpayProvider(BasePaymentProvider):
    code = "upay"
    CREDENTIALS = [
        Credential("merchant_id", "Merchant ID"),
        Credential("merchant_key", "Merchant key", secret=True),
        Credential("merchant_code", "Merchant code"),
        Credential("merchant_name", "Merchant name", required=False),
        Credential("merchant_mobile", "Merchant mobile", required=False),
        Credential("merchant_category_code", "Merchant category code", required=False, help="Default 7922"),
        Credential("base_url", "API base URL (optional)", required=False),
        Credential("auth_path", "Auth path (optional)", required=False),
        Credential("init_path", "Payment-init path (optional)", required=False),
        Credential("status_path", "Status path (optional)", required=False, help="Use {txn_id} where the id goes."),
    ]

    @property
    def base(self):
        return self.cred("base_url") or (SANDBOX if self.sandbox else LIVE)

    def _token(self) -> str:
        merchant_id, key = self.cred("merchant_id"), self.cred("merchant_key")
        if not merchant_id or not key:
            raise PaymentError("Upay credentials are not configured")
        cache_key = f"upay:token:{'sb' if self.sandbox else 'live'}"
        token = cache.get(cache_key)
        if token:
            return token
        data = call(
            "POST",
            f"{self.base}{self.cred('auth_path', '/payment/merchant-auth/')}",
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
            f"{self.base}{self.cred('init_path', '/payment/merchant-payment-init/')}",
            provider=self.code,
            headers=self._headers(),
            json={
                "date": timezone.localdate().isoformat(),
                "txn_id": attempt.tran_id,
                "invoice_id": attempt.order.reference,
                "amount": float(attempt.amount),
                "merchant_id": self.cred("merchant_id"),
                "merchant_name": self.cred("merchant_name", "Nexopay"),
                "merchant_code": self.cred("merchant_code"),
                "merchant_country_code": "BD",
                "merchant_city": "Dhaka",
                "merchant_category_code": self.cred("merchant_category_code", "7922"),
                "merchant_mobile": self.cred("merchant_mobile"),
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
        path = self.cred("status_path", "/payment/single-payment-status/{txn_id}/").format(txn_id=attempt.tran_id)
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
