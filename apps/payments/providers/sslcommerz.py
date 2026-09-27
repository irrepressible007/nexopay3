"""
SSLCommerz (payment aggregator) — used for Visa/Mastercard/Amex so card-scheme
PCI-DSS compliance stays with the aggregator. API v4.

Flow: session init → redirect buyer to GatewayPageURL → buyer returns to our
success/fail/cancel URL (browser POST) and SSLCommerz also POSTs the IPN →
we *always* re-validate with the Validation API before trusting anything.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from ..models import PaymentAttempt
from ..services import PaymentError, mark_failed, mark_succeeded
from .base import BasePaymentProvider, Credential, RefundResult, VerifyResult
from .http import call

SANDBOX = "https://sandbox.sslcommerz.com"
LIVE = "https://securepay.sslcommerz.com"


class SSLCommerzProvider(BasePaymentProvider):
    code = "sslcommerz"
    supports_refund_api = True
    CREDENTIALS = [
        Credential("store_id", "Store ID"),
        Credential("store_password", "Store password", secret=True),
        Credential("multi_card_name", "Limit to methods (optional)", required=False,
                   help="e.g. visacard,mastercard,amexcard to show cards only. Empty = all methods."),
    ]

    @property
    def base(self):
        return SANDBOX if self.sandbox else LIVE

    @property
    def creds(self):
        store_id, password = self.cred("store_id"), self.cred("store_password")
        if not store_id or not password:
            raise PaymentError("SSLCommerz credentials are not configured")
        return {"store_id": store_id, "store_passwd": password}

    def initiate(self, attempt, request) -> str:
        order = attempt.order
        payload = {
            **self.creds,
            "total_amount": f"{attempt.amount:.2f}",
            "currency": "BDT",
            "tran_id": attempt.tran_id,
            "success_url": self.return_url(attempt, "success"),
            "fail_url": self.return_url(attempt, "fail"),
            "cancel_url": self.return_url(attempt, "cancel"),
            "ipn_url": self.ipn_url(),
            "cus_name": order.buyer_name[:50],
            "cus_email": order.delivery_email,
            "cus_phone": order.buyer_phone,
            "cus_add1": "N/A",
            "cus_city": order.event.city or "Dhaka",
            "cus_country": "Bangladesh",
            "shipping_method": "NO",
            "product_name": order.event.title[:250],
            "product_category": "Event ticket",
            "product_profile": "non-physical-goods",
            "num_of_item": order.ticket_count,
            "value_a": order.reference,
        }
        cards_only = self.cred("multi_card_name")
        if cards_only:
            payload["multi_card_name"] = cards_only  # e.g. "visacard,mastercard,amexcard"
        data = call("POST", f"{self.base}/gwprocess/v4/api.php", provider=self.code, data=payload)
        attempt.log("init", {k: v for k, v in data.items() if k in ("status", "failedreason", "sessionkey")})
        if data.get("status") != "SUCCESS" or not data.get("GatewayPageURL"):
            attempt.save(update_fields=["raw", "updated_at"])
            raise PaymentError(f"SSLCommerz init failed: {data.get('failedreason', 'unknown')}")
        attempt.provider_ref = data.get("sessionkey", "")
        attempt.save(update_fields=["provider_ref", "raw", "updated_at"])
        return data["GatewayPageURL"]

    def _validate(self, val_id: str) -> dict:
        return call(
            "GET",
            f"{self.base}/validator/api/validationserverAPI.php",
            provider=self.code,
            params={"val_id": val_id, **self.creds, "format": "json"},
        )

    def _apply_validation(self, attempt: PaymentAttempt, data: dict) -> None:
        ok = (
            data.get("status") in ("VALID", "VALIDATED")
            and data.get("tran_id") == attempt.tran_id
            and Decimal(str(data.get("amount", "0"))) == attempt.amount
            and data.get("currency_type", data.get("currency", "BDT")) == "BDT"
        )
        if ok:
            mark_succeeded(attempt, data.get("bank_tran_id") or data.get("val_id"), _safe(data))
        elif data.get("status") in ("FAILED", "INVALID_TRANSACTION"):
            mark_failed(attempt, payload=_safe(data))

    def handle_return(self, request):
        params = request.POST or request.GET
        attempt = self.attempt_for(params.get("tran_id") or request.GET.get("tran_id", ""))
        if attempt is None:
            return None
        outcome = request.GET.get("outcome")
        val_id = params.get("val_id")
        if outcome == "success" and val_id:
            self._apply_validation(attempt, self._validate(val_id))
        elif outcome == "cancel":
            mark_failed(attempt, PaymentAttempt.Status.CANCELLED, _safe(dict(params.items())))
        elif outcome == "fail":
            mark_failed(attempt, payload=_safe(dict(params.items())))
        return attempt

    def handle_ipn(self, request):
        attempt = self.attempt_for(request.POST.get("tran_id", ""))
        val_id = request.POST.get("val_id")
        if attempt is None or not val_id:
            raise PaymentError("IPN without a known tran_id / val_id")
        self._apply_validation(attempt, self._validate(val_id))
        return attempt

    def verify(self, attempt) -> VerifyResult:
        data = call(
            "GET",
            f"{self.base}/validator/api/merchantTransIDvalidationAPI.php",
            provider=self.code,
            params={"tran_id": attempt.tran_id, **self.creds, "format": "json"},
        )
        for element in data.get("element", []) or []:
            if element.get("status") in ("VALID", "VALIDATED") and Decimal(str(element.get("amount", 0))) == attempt.amount:
                return VerifyResult(PaymentAttempt.Status.SUCCEEDED, element.get("bank_tran_id", ""), _safe(element))
        if data.get("no_of_trans_found") in (0, "0") and attempt.created_at < timezone.now() - timedelta(hours=2):
            return VerifyResult(PaymentAttempt.Status.CANCELLED, payload=_safe(data))
        return VerifyResult(PaymentAttempt.Status.INITIATED, payload=_safe(data))

    def refund(self, attempt, amount, reason) -> RefundResult:
        data = call(
            "GET",
            f"{self.base}/validator/api/merchantTransIDvalidationAPI.php",
            provider=self.code,
            params={
                "bank_tran_id": attempt.provider_txn_id,
                "refund_amount": f"{amount:.2f}",
                "refund_remarks": reason[:250] or "Refund",
                "refe_id": attempt.tran_id,
                **self.creds,
                "format": "json",
            },
        )
        ok = data.get("APIConnect") == "DONE" and data.get("status") in ("success", "processing")
        return RefundResult(ok=ok, provider_refund_id=data.get("refund_ref_id", ""), payload=_safe(data),
                            message=data.get("errorReason", ""))


def _safe(data: dict) -> dict:
    """Drop anything credential-like before storing provider payloads."""
    return {k: v for k, v in data.items() if "passwd" not in k and "password" not in k and k != "store_id"}
