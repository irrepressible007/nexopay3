"""
The payment abstraction layer. Checkout and order code only ever talk to this
interface — never to a provider SDK — so adding or swapping a wallet is local
to its provider module.
"""
from dataclasses import dataclass, field

from django.conf import settings
from django.urls import reverse

from ..models import PaymentAttempt


@dataclass
class VerifyResult:
    status: str  # one of PaymentAttempt.Status
    provider_txn_id: str = ""
    payload: dict = field(default_factory=dict)


@dataclass
class RefundResult:
    ok: bool
    provider_refund_id: str = ""
    payload: dict = field(default_factory=dict)
    message: str = ""


class BasePaymentProvider:
    code = ""
    supports_refund_api = False

    def __init__(self, setting):
        self.setting = setting
        self.sandbox = setting.is_sandbox

    # --- URLs the provider sends the buyer / its servers back to --------------
    def return_url(self, attempt: PaymentAttempt, outcome: str = "") -> str:
        url = settings.SITE_URL + reverse("payments:return", kwargs={"provider": self.code})
        return f"{url}?tran_id={attempt.tran_id}" + (f"&outcome={outcome}" if outcome else "")

    def ipn_url(self) -> str:
        return settings.SITE_URL + reverse("payments:ipn", kwargs={"provider": self.code})

    # --- interface ------------------------------------------------------------
    def initiate(self, attempt: PaymentAttempt, request) -> str:
        """Create the payment at the provider; return the URL to send the buyer to."""
        raise NotImplementedError

    def handle_return(self, request) -> PaymentAttempt | None:
        """
        The buyer's browser came back from the provider. Implementations must
        verify server-side (never trust query parameters alone) and then call
        payments.services.mark_succeeded / mark_failed.
        """
        raise NotImplementedError

    def handle_ipn(self, request) -> PaymentAttempt | None:
        """Server-to-server notification. Same verification rules as handle_return."""
        return None

    def verify(self, attempt: PaymentAttempt) -> VerifyResult:
        """Ask the provider for the attempt's current state (used by reconciliation)."""
        raise NotImplementedError

    def refund(self, attempt: PaymentAttempt, amount, reason: str) -> RefundResult:
        return RefundResult(ok=False, message="Refund API not supported; refund manually.")

    @staticmethod
    def attempt_for(tran_id: str) -> PaymentAttempt | None:
        return PaymentAttempt.objects.select_related("order").filter(tran_id=tran_id).first()
