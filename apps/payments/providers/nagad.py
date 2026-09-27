"""
Nagad Online Payment API (checkout, API version v-0.2.0).

Every request carries `sensitiveData` encrypted with Nagad's public key and a
SHA256withRSA `signature` made with our private key; Nagad's responses are
encrypted with our public key. Flow: initialize → complete (get redirect URL)
→ buyer pays in Nagad → callback with payment_ref_id → verify server-side.
"""
import base64
import json
import secrets
from decimal import Decimal

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from ..models import PaymentAttempt
from ..services import PaymentError, mark_failed, mark_succeeded
from .base import BasePaymentProvider, Credential, VerifyResult
from .http import call

SANDBOX = "http://sandbox.mynagad.com:10080/remote-payment-gateway-1.0/api/dfs"
LIVE = "https://api.mynagad.com/api/dfs"


def _pem(raw: str, kind: str) -> bytes:
    raw = raw.strip()
    if raw.startswith("-----BEGIN"):
        return raw.encode()
    body = "\n".join(raw[i : i + 64] for i in range(0, len(raw), 64))
    return f"-----BEGIN {kind}-----\n{body}\n-----END {kind}-----\n".encode()


class NagadProvider(BasePaymentProvider):
    code = "nagad"
    supports_refund_api = False  # refunds are processed manually via the Nagad merchant portal
    CREDENTIALS = [
        Credential("merchant_id", "Merchant ID"),
        Credential("merchant_number", "Merchant number"),
        Credential("public_key", "Nagad public key", secret=True, multiline=True,
                   help="The PG public key Nagad sends you (with or without BEGIN/END lines)."),
        Credential("private_key", "Your merchant private key", secret=True, multiline=True),
        Credential("base_url", "API base URL (optional)", required=False),
    ]

    @property
    def base(self):
        return self.cred("base_url") or (SANDBOX if self.sandbox else LIVE)

    @property
    def merchant_id(self):
        mid = self.cred("merchant_id")
        if not mid:
            raise PaymentError("Nagad credentials are not configured")
        return mid

    def _nagad_public_key(self):
        return serialization.load_pem_public_key(_pem(self.cred("public_key"), "PUBLIC KEY"))

    def _merchant_private_key(self):
        return serialization.load_pem_private_key(_pem(self.cred("private_key"), "PRIVATE KEY"), password=None)

    def _encrypt(self, payload: dict) -> str:
        data = json.dumps(payload, separators=(",", ":")).encode()
        return base64.b64encode(self._nagad_public_key().encrypt(data, padding.PKCS1v15())).decode()

    def _sign(self, payload: dict) -> str:
        data = json.dumps(payload, separators=(",", ":")).encode()
        return base64.b64encode(self._merchant_private_key().sign(data, padding.PKCS1v15(), hashes.SHA256())).decode()

    def _decrypt(self, value: str) -> dict:
        return json.loads(self._merchant_private_key().decrypt(base64.b64decode(value), padding.PKCS1v15()))

    def _headers(self, request=None):
        ip = (request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("REMOTE_ADDR")) if request else "127.0.0.1"
        return {"X-KM-Api-Version": "v-0.2.0", "X-KM-IP-V4": ip or "127.0.0.1", "X-KM-Client-Type": "PC_WEB",
                "Content-Type": "application/json"}

    @staticmethod
    def order_id(attempt) -> str:
        return attempt.tran_id.replace("-", "")  # Nagad order ids must be alphanumeric

    def initiate(self, attempt, request) -> str:
        order_id = self.order_id(attempt)
        now = timezone.localtime().strftime("%Y%m%d%H%M%S")
        challenge = secrets.token_hex(20)
        sensitive = {"merchantId": self.merchant_id, "datetime": now, "orderId": order_id, "challenge": challenge}
        init = call(
            "POST",
            f"{self.base}/check-out/initialize/{self.merchant_id}/{order_id}?locale=EN",
            provider=self.code,
            headers=self._headers(request),
            json={
                "accountNumber": self.cred("merchant_number"),
                "dateTime": now,
                "sensitiveData": self._encrypt(sensitive),
                "signature": self._sign(sensitive),
            },
        )
        if "sensitiveData" not in init:
            attempt.log("initialize", init)
            attempt.save(update_fields=["raw", "updated_at"])
            raise PaymentError(f"Nagad initialize failed: {init.get('message') or init.get('reason')}")
        decrypted = self._decrypt(init["sensitiveData"])
        payment_ref = decrypted["paymentReferenceId"]

        complete_data = {
            "merchantId": self.merchant_id,
            "orderId": order_id,
            "currencyCode": "050",
            "amount": f"{attempt.amount:.2f}",
            "challenge": decrypted["challenge"],
        }
        callback = settings.SITE_URL + reverse("payments:return", kwargs={"provider": self.code})
        complete = call(
            "POST",
            f"{self.base}/check-out/complete/{payment_ref}",
            provider=self.code,
            headers=self._headers(request),
            json={
                "sensitiveData": self._encrypt(complete_data),
                "signature": self._sign(complete_data),
                "merchantCallbackURL": callback,
                "additionalMerchantInfo": {"orderReference": attempt.order.reference},
            },
        )
        attempt.log("complete", complete)
        if complete.get("status") != "Success" or not complete.get("callBackUrl"):
            attempt.save(update_fields=["raw", "updated_at"])
            raise PaymentError(f"Nagad complete failed: {complete.get('message')}")
        attempt.provider_ref = payment_ref
        attempt.save(update_fields=["provider_ref", "raw", "updated_at"])
        return complete["callBackUrl"]

    def _verify_ref(self, payment_ref: str) -> dict:
        return call("GET", f"{self.base}/verify/payment/{payment_ref}", provider=self.code, headers=self._headers())

    def _apply(self, attempt, data) -> bool:
        ok = (
            data.get("status") == "Success"
            and data.get("orderId") == self.order_id(attempt)
            and Decimal(str(data.get("amount", "0"))) == attempt.amount
        )
        if ok:
            mark_succeeded(attempt, data.get("issuerPaymentRefNo") or data.get("paymentRefId"), data)
        return ok

    def handle_return(self, request):
        payment_ref = request.GET.get("payment_ref_id", "")
        attempt = (
            PaymentAttempt.objects.select_related("order").filter(provider=self.code, provider_ref=payment_ref).first()
            if payment_ref
            else None
        )
        if attempt is None:
            return None
        data = self._verify_ref(payment_ref)
        if not self._apply(attempt, data):
            cancelled = request.GET.get("status") == "Aborted"
            mark_failed(attempt, PaymentAttempt.Status.CANCELLED if cancelled else PaymentAttempt.Status.FAILED, data)
        return attempt

    def verify(self, attempt) -> VerifyResult:
        if not attempt.provider_ref:
            return VerifyResult(PaymentAttempt.Status.CANCELLED)
        data = self._verify_ref(attempt.provider_ref)
        if data.get("status") == "Success" and Decimal(str(data.get("amount", "0"))) == attempt.amount:
            return VerifyResult(PaymentAttempt.Status.SUCCEEDED, data.get("issuerPaymentRefNo", ""), data)
        if data.get("status") in ("Aborted", "Cancelled", "Failed", "InvalidRequest", "Fraud"):
            return VerifyResult(PaymentAttempt.Status.FAILED, payload=data)
        return VerifyResult(PaymentAttempt.Status.INITIATED, payload=data)
