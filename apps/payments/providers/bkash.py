"""
bKash Tokenized Checkout (v1.2.0-beta).

Flow: grant token → create payment (get bkashURL) → buyer approves in bKash →
bKash redirects to our callback with paymentID & status → we *execute* the
payment server-side; only a Completed execute response counts as paid.
"""
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from ..models import PaymentAttempt
from ..services import PaymentError, mark_failed, mark_succeeded
from .base import BasePaymentProvider, Credential, RefundResult, VerifyResult
from .http import call

SANDBOX = "https://tokenized.sandbox.bka.sh/v1.2.0-beta"
LIVE = "https://tokenized.pay.bka.sh/v1.2.0-beta"


class BkashProvider(BasePaymentProvider):
    code = "bkash"
    supports_refund_api = True
    CREDENTIALS = [
        Credential("app_key", "App key"),
        Credential("app_secret", "App secret", secret=True),
        Credential("username", "Username"),
        Credential("password", "Password", secret=True),
        Credential("base_url", "API base URL (optional)", required=False,
                   help="Only if bKash gives you a different URL. Empty = standard sandbox/live URL."),
    ]

    @property
    def base(self):
        return self.cred("base_url") or (SANDBOX if self.sandbox else LIVE)

    def _app_key(self):
        key = self.cred("app_key")
        if not key:
            raise PaymentError("bKash credentials are not configured")
        return key

    def _token(self) -> str:
        cache_key = f"bkash:id_token:{'sb' if self.sandbox else 'live'}"
        token = cache.get(cache_key)
        if token:
            return token
        data = call(
            "POST",
            f"{self.base}/tokenized/checkout/token/grant",
            provider=self.code,
            headers={"username": self.cred("username"), "password": self.cred("password"), "Accept": "application/json"},
            json={"app_key": self._app_key(), "app_secret": self.cred("app_secret")},
        )
        token = data.get("id_token")
        if not token:
            raise PaymentError(f"bKash token grant failed: {data.get('statusMessage') or data.get('msg')}")
        cache.set(cache_key, token, max(int(data.get("expires_in", 3600)) - 300, 60))
        return token

    def _post(self, path: str, body: dict) -> dict:
        return call(
            "POST",
            f"{self.base}{path}",
            provider=self.code,
            headers={"Authorization": self._token(), "X-APP-Key": self._app_key(), "Accept": "application/json"},
            json=body,
        )

    def callback_url(self) -> str:
        # bKash appends ?paymentID=…&status=… itself, so no query string here.
        return settings.SITE_URL + reverse("payments:return", kwargs={"provider": self.code})

    def initiate(self, attempt, request) -> str:
        data = self._post(
            "/tokenized/checkout/create",
            {
                "mode": "0011",
                "payerReference": attempt.order.buyer_phone.replace("+88", ""),
                "callbackURL": self.callback_url(),
                "amount": f"{attempt.amount:.2f}",
                "currency": "BDT",
                "intent": "sale",
                "merchantInvoiceNumber": attempt.tran_id,
            },
        )
        attempt.log("create", data)
        if data.get("statusCode") != "0000" or not data.get("bkashURL"):
            attempt.save(update_fields=["raw", "updated_at"])
            raise PaymentError(f"bKash create failed: {data.get('statusMessage')}")
        attempt.provider_ref = data["paymentID"]
        attempt.save(update_fields=["provider_ref", "raw", "updated_at"])
        return data["bkashURL"]

    def _attempt_by_payment_id(self, payment_id):
        if not payment_id:
            return None
        return PaymentAttempt.objects.select_related("order").filter(provider=self.code, provider_ref=payment_id).first()

    def _apply(self, attempt, data):
        completed = (
            data.get("transactionStatus") == "Completed"
            and data.get("merchantInvoiceNumber", attempt.tran_id) == attempt.tran_id
            and Decimal(str(data.get("amount", "0"))) == attempt.amount
        )
        if completed and data.get("trxID"):
            mark_succeeded(attempt, data["trxID"], data)
            return True
        return False

    def handle_return(self, request):
        attempt = self._attempt_by_payment_id(request.GET.get("paymentID"))
        if attempt is None:
            return None
        status = request.GET.get("status")
        if status == "success":
            data = self._post("/tokenized/checkout/execute", {"paymentID": attempt.provider_ref})
            if not self._apply(attempt, data):
                # Execute can time out even though bKash completed it — ask again.
                query = self._post("/tokenized/checkout/payment/status", {"paymentID": attempt.provider_ref})
                if not self._apply(attempt, query):
                    mark_failed(attempt, payload={"execute": data, "query": query})
        elif status == "cancel":
            mark_failed(attempt, PaymentAttempt.Status.CANCELLED, dict(request.GET.items()))
        else:
            mark_failed(attempt, payload=dict(request.GET.items()))
        return attempt

    def verify(self, attempt) -> VerifyResult:
        if not attempt.provider_ref:
            return VerifyResult(PaymentAttempt.Status.CANCELLED)
        data = self._post("/tokenized/checkout/payment/status", {"paymentID": attempt.provider_ref})
        status = data.get("transactionStatus")
        if status == "Completed" and Decimal(str(data.get("amount", "0"))) == attempt.amount:
            return VerifyResult(PaymentAttempt.Status.SUCCEEDED, data.get("trxID", ""), data)
        if status == "Initiated":
            # Created but never executed: execute now if the buyer had approved it.
            executed = self._post("/tokenized/checkout/execute", {"paymentID": attempt.provider_ref})
            if executed.get("transactionStatus") == "Completed" and Decimal(str(executed.get("amount", "0"))) == attempt.amount:
                return VerifyResult(PaymentAttempt.Status.SUCCEEDED, executed.get("trxID", ""), executed)
        if status in ("Failed", "Cancelled", "Expired"):
            return VerifyResult(PaymentAttempt.Status.FAILED, payload=data)
        return VerifyResult(PaymentAttempt.Status.INITIATED, payload=data)

    def refund(self, attempt, amount, reason) -> RefundResult:
        data = self._post(
            "/tokenized/checkout/payment/refund",
            {
                "paymentID": attempt.provider_ref,
                "amount": f"{amount:.2f}",
                "trxID": attempt.provider_txn_id,
                "sku": attempt.order.reference,
                "reason": (reason or "Refund")[:255],
            },
        )
        ok = data.get("transactionStatus") == "Completed"
        return RefundResult(ok=ok, provider_refund_id=data.get("refundTrxID", ""), payload=data,
                            message=data.get("statusMessage", ""))
