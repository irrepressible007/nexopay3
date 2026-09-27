"""
Pathao Pay.

Pathao Pay's merchant checkout API is only published to onboarded merchants,
so its request/response contract cannot be implemented faithfully yet. This
provider keeps the slot in the payment abstraction (admin toggle, checkout
option, routing) and fails loudly — never silently — until the official
document is available. Implementing it means filling in `initiate`,
`handle_return` and `verify` like the other providers; nothing else changes.
"""
from ..services import PaymentError
from .base import BasePaymentProvider, VerifyResult


class PathaoPayProvider(BasePaymentProvider):
    code = "pathaopay"

    def initiate(self, attempt, request) -> str:
        raise PaymentError("Pathao Pay is not available yet (awaiting merchant API onboarding)")

    def handle_return(self, request):
        return None

    def verify(self, attempt) -> VerifyResult:
        return VerifyResult(status=attempt.status)
