"""A fake gateway for local development and staging demos. Never enabled in production."""
from django.urls import reverse

from ..models import PaymentAttempt
from ..services import mark_failed, mark_succeeded
from .base import BasePaymentProvider, VerifyResult


class MockProvider(BasePaymentProvider):
    code = "mock"

    def return_url(self, attempt, outcome: str = "") -> str:
        # Relative, so the browser stays on whatever host it is using (dev/staging).
        url = reverse("payments:return", kwargs={"provider": self.code})
        return f"{url}?tran_id={attempt.tran_id}" + (f"&outcome={outcome}" if outcome else "")

    def initiate(self, attempt, request) -> str:
        return reverse("payments:mock_gateway", kwargs={"tran_id": attempt.tran_id})

    def handle_return(self, request):
        attempt = self.attempt_for(request.GET.get("tran_id", ""))
        if not attempt:
            return None
        if request.GET.get("outcome") == "success":
            mark_succeeded(attempt, f"MOCK-{attempt.tran_id}", {"mock": True})
        else:
            mark_failed(attempt, PaymentAttempt.Status.CANCELLED, {"mock": True})
        return attempt

    def verify(self, attempt):
        return VerifyResult(status=attempt.status)
