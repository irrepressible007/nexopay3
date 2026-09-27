import base64
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.test import RequestFactory
from django.utils import timezone

from apps.orders.models import Order
from apps.orders.services import start_checkout
from apps.payments.models import PaymentAttempt, PaymentProviderSetting, Refund
from apps.payments.reconcile import reconcile_pending
from apps.payments.refunds import cancel_event, mark_refunded_manually, process_refund, request_refund
from apps.payments.registry import get_provider
from apps.payments.services import new_attempt
from apps.tickets.models import Ticket

from .conftest import checkout_kwargs
from .factories import TicketTypeFactory

pytestmark = pytest.mark.django_db
rf = RequestFactory()


class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._data


@pytest.fixture
def fake_http(monkeypatch):
    """Route provider HTTP calls to handlers: routes[(METHOD, url-substring)] = fn(kwargs) -> dict."""
    routes, calls = {}, []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        for (m, fragment), handler in routes.items():
            if m == method and fragment in url:
                return FakeResponse(handler(kwargs))
        raise AssertionError(f"Unexpected call {method} {url}")

    monkeypatch.setattr("apps.payments.providers.http.requests.request", request)
    return routes, calls


@pytest.fixture
def creds(monkeypatch):
    values = {
        "SSLCOMMERZ_STORE_ID": "teststore", "SSLCOMMERZ_STORE_PASSWORD": "secret",
        "BKASH_APP_KEY": "k", "BKASH_APP_SECRET": "s", "BKASH_USERNAME": "u", "BKASH_PASSWORD": "p",
        "NAGAD_MERCHANT_ID": "683002007104225", "NAGAD_MERCHANT_NUMBER": "01711428036",
    }
    monkeypatch.setattr("apps.payments.providers.http.env", lambda name, default="": values.get(name, default))
    for mod in ("sslcommerz", "bkash", "nagad"):
        monkeypatch.setattr(f"apps.payments.providers.{mod}.env", lambda name, default="": values.get(name, default))
    PaymentProviderSetting.objects.filter(provider__in=["sslcommerz", "bkash", "nagad"]).update(is_enabled=True)
    return values


@pytest.fixture
def pending_order(buyer, event):
    tt = TicketTypeFactory(event=event, price=Decimal("500"), allow_quantity=True, stock=5)
    return start_checkout(**checkout_kwargs(buyer, event, {tt.pk: 2}))


# --- SSLCommerz ---------------------------------------------------------------
class TestSSLCommerz:
    def test_full_flow_with_server_side_validation(self, fake_http, creds, pending_order):
        routes, calls = fake_http
        provider = get_provider("sslcommerz")
        attempt = new_attempt(pending_order, "sslcommerz")
        routes[("POST", "gwprocess/v4/api.php")] = lambda kw: {
            "status": "SUCCESS", "GatewayPageURL": "https://sandbox.sslcommerz.com/pay/x", "sessionkey": "SK1"}
        assert provider.initiate(attempt, rf.get("/")) == "https://sandbox.sslcommerz.com/pay/x"
        sent = calls[-1][2]["data"]
        assert sent["total_amount"] == "1000.00" and sent["tran_id"] == attempt.tran_id

        routes[("GET", "validationserverAPI.php")] = lambda kw: {
            "status": "VALID", "tran_id": attempt.tran_id, "amount": "1000.00", "currency_type": "BDT",
            "bank_tran_id": "BANK123", "val_id": kw["params"]["val_id"]}
        request = rf.post(f"/payments/sslcommerz/return/?tran_id={attempt.tran_id}&outcome=success",
                          {"tran_id": attempt.tran_id, "val_id": "V1", "status": "VALID"})
        provider.handle_return(request)
        pending_order.refresh_from_db()
        assert pending_order.status == Order.Status.PAID
        assert pending_order.tickets.count() == 2

        # The IPN for the same transaction arrives afterwards: no duplicate tickets.
        provider.handle_ipn(rf.post("/payments/sslcommerz/ipn/", {"tran_id": attempt.tran_id, "val_id": "V1"}))
        assert pending_order.tickets.count() == 2

    def test_amount_mismatch_is_not_accepted(self, fake_http, creds, pending_order):
        routes, _ = fake_http
        provider = get_provider("sslcommerz")
        attempt = new_attempt(pending_order, "sslcommerz")
        routes[("GET", "validationserverAPI.php")] = lambda kw: {
            "status": "VALID", "tran_id": attempt.tran_id, "amount": "10.00", "currency_type": "BDT", "bank_tran_id": "B"}
        provider.handle_return(rf.post(f"/x/?tran_id={attempt.tran_id}&outcome=success",
                                       {"tran_id": attempt.tran_id, "val_id": "V"}))
        pending_order.refresh_from_db()
        assert pending_order.status == Order.Status.PENDING_PAYMENT

    def test_query_params_alone_never_mark_paid(self, fake_http, creds, pending_order):
        routes, _ = fake_http
        attempt = new_attempt(pending_order, "sslcommerz")
        routes[("GET", "validationserverAPI.php")] = lambda kw: {"status": "INVALID_TRANSACTION"}
        get_provider("sslcommerz").handle_return(
            rf.post(f"/x/?tran_id={attempt.tran_id}&outcome=success", {"tran_id": attempt.tran_id, "val_id": "FAKE", "status": "VALID"}))
        pending_order.refresh_from_db()
        assert pending_order.status == Order.Status.PENDING_PAYMENT


# --- bKash ----------------------------------------------------------------------
class TestBkash:
    @pytest.fixture
    def bkash(self, fake_http, creds):
        routes, calls = fake_http
        routes[("POST", "token/grant")] = lambda kw: {"id_token": "TOKEN", "expires_in": 3600}
        routes[("POST", "checkout/create")] = lambda kw: {
            "statusCode": "0000", "paymentID": "PAY1", "bkashURL": "https://sandbox.bka.sh/pay"}
        return routes, calls

    def test_execute_on_callback(self, bkash, pending_order):
        routes, calls = bkash
        provider = get_provider("bkash")
        attempt = new_attempt(pending_order, "bkash")
        assert provider.initiate(attempt, rf.get("/")) == "https://sandbox.bka.sh/pay"
        assert calls[-1][2]["json"]["amount"] == "1000.00"
        routes[("POST", "checkout/execute")] = lambda kw: {
            "transactionStatus": "Completed", "trxID": "TRX9", "amount": "1000.00",
            "merchantInvoiceNumber": attempt.tran_id, "statusCode": "0000"}
        provider.handle_return(rf.get("/payments/bkash/return/?paymentID=PAY1&status=success"))
        pending_order.refresh_from_db()
        assert pending_order.status == Order.Status.PAID
        assert PaymentAttempt.objects.get(pk=attempt.pk).provider_txn_id == "TRX9"

    def test_execute_timeout_falls_back_to_query(self, bkash, pending_order):
        routes, _ = bkash
        provider = get_provider("bkash")
        attempt = new_attempt(pending_order, "bkash")
        provider.initiate(attempt, rf.get("/"))
        routes[("POST", "checkout/execute")] = lambda kw: {"statusCode": "9999", "statusMessage": "timeout"}
        routes[("POST", "payment/status")] = lambda kw: {
            "transactionStatus": "Completed", "trxID": "TRX10", "amount": "1000.00", "merchantInvoiceNumber": attempt.tran_id}
        provider.handle_return(rf.get("/payments/bkash/return/?paymentID=PAY1&status=success"))
        pending_order.refresh_from_db()
        assert pending_order.status == Order.Status.PAID

    def test_cancel(self, bkash, pending_order):
        provider = get_provider("bkash")
        attempt = new_attempt(pending_order, "bkash")
        provider.initiate(attempt, rf.get("/"))
        provider.handle_return(rf.get("/payments/bkash/return/?paymentID=PAY1&status=cancel"))
        attempt.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.CANCELLED

    def test_reconcile_finds_completed_payment(self, bkash, pending_order):
        routes, _ = bkash
        provider = get_provider("bkash")
        attempt = new_attempt(pending_order, "bkash")
        provider.initiate(attempt, rf.get("/"))
        PaymentAttempt.objects.filter(pk=attempt.pk).update(created_at=timezone.now() - timedelta(minutes=10))
        routes[("POST", "payment/status")] = lambda kw: {"transactionStatus": "Completed", "trxID": "TRX11", "amount": "1000.00"}
        assert reconcile_pending()["succeeded"] == 1
        pending_order.refresh_from_db()
        assert pending_order.status == Order.Status.PAID

    def test_refund_releases_stock_and_voids_tickets(self, bkash, pending_order):
        routes, _ = bkash
        provider = get_provider("bkash")
        attempt = new_attempt(pending_order, "bkash")
        provider.initiate(attempt, rf.get("/"))
        routes[("POST", "checkout/execute")] = lambda kw: {
            "transactionStatus": "Completed", "trxID": "TRX12", "amount": "1000.00", "merchantInvoiceNumber": attempt.tran_id}
        provider.handle_return(rf.get("/x/?paymentID=PAY1&status=success"))
        routes[("POST", "payment/refund")] = lambda kw: {"transactionStatus": "Completed", "refundTrxID": "RF1"}

        one_ticket = pending_order.tickets.first()
        refund = process_refund(request_refund(order=pending_order, reason="Can't attend", tickets=[one_ticket]))
        assert refund.status == Refund.Status.SUCCEEDED and refund.amount == Decimal("500.00")
        pending_order.refresh_from_db()
        assert pending_order.status == Order.Status.PARTIALLY_REFUNDED
        one_ticket.refresh_from_db()
        assert one_ticket.status == Ticket.Status.REFUNDED
        tt = one_ticket.ticket_type
        tt.refresh_from_db()
        assert tt.sold_count == 1


# --- Nagad (RSA) ------------------------------------------------------------------
def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_b64 = "".join(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        .decode().splitlines()[1:-1])
    public_b64 = "".join(
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode().splitlines()[1:-1])
    return key, private_b64, public_b64


def test_nagad_encrypted_flow(fake_http, creds, pending_order):
    routes, _ = fake_http
    nagad_key, _nagad_priv, nagad_pub = _keypair()
    merchant_key, merchant_priv, _merchant_pub = _keypair()
    creds.update({"NAGAD_PUBLIC_KEY": nagad_pub, "NAGAD_PRIVATE_KEY": merchant_priv})

    def initialize(kw):
        body = kw["json"]
        sensitive = json.loads(nagad_key.decrypt(base64.b64decode(body["sensitiveData"]), padding.PKCS1v15()))
        signed = json.dumps(sensitive, separators=(",", ":")).encode()
        merchant_key.public_key().verify(base64.b64decode(body["signature"]), signed, padding.PKCS1v15(), hashes.SHA256())
        reply = json.dumps({"paymentReferenceId": "REF77", "challenge": sensitive["challenge"]}).encode()
        return {"sensitiveData": base64.b64encode(merchant_key.public_key().encrypt(reply, padding.PKCS1v15())).decode(),
                "signature": "x"}

    def complete(kw):
        data = json.loads(nagad_key.decrypt(base64.b64decode(kw["json"]["sensitiveData"]), padding.PKCS1v15()))
        assert data["amount"] == "1000.00" and data["currencyCode"] == "050"
        return {"status": "Success", "callBackUrl": "https://sandbox.mynagad.com/pay/REF77"}

    routes[("POST", "check-out/initialize")] = initialize
    routes[("POST", "check-out/complete/REF77")] = complete
    provider = get_provider("nagad")
    attempt = new_attempt(pending_order, "nagad")
    assert provider.initiate(attempt, rf.get("/")) == "https://sandbox.mynagad.com/pay/REF77"

    routes[("GET", "verify/payment/REF77")] = lambda kw: {
        "status": "Success", "orderId": attempt.tran_id.replace("-", ""), "amount": "1000.00", "issuerPaymentRefNo": "NG55"}
    provider.handle_return(rf.get("/payments/nagad/return/?payment_ref_id=REF77&status=Success"))
    pending_order.refresh_from_db()
    assert pending_order.status == Order.Status.PAID

    # Nagad has no refund API here: the refund waits for manual processing, then is recorded.
    refund = process_refund(request_refund(order=pending_order, reason="Event moved"))
    assert refund.status == Refund.Status.APPROVED
    refund = mark_refunded_manually(refund, "NAGAD-MANUAL-1")
    pending_order.refresh_from_db()
    assert refund.status == Refund.Status.SUCCEEDED
    assert pending_order.status == Order.Status.REFUNDED


def test_cancel_event_refunds_everyone(buyer, event):
    tt = TicketTypeFactory(event=event, price=Decimal("0"))
    order = start_checkout(**checkout_kwargs(buyer, event, {tt.pk: 1}))
    assert cancel_event(event, reason="Venue unavailable") == 1
    order.refresh_from_db()
    event.refresh_from_db()
    assert event.status == "cancelled"
    assert order.status == Order.Status.REFUNDED
    assert order.tickets.get().status == Ticket.Status.REFUNDED
