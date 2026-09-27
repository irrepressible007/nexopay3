"""
Encryption for secrets stored in the database (payment credentials, SMTP password).

Key: FIELD_ENCRYPTION_KEY if set, otherwise derived from SECRET_KEY. Changing
SECRET_KEY without setting FIELD_ENCRYPTION_KEY means re-entering those secrets.
"""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    raw = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(f"nexopay-fields:{raw}".encode()).digest())
    return Fernet(key)


def encrypt_str(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt_str(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


def encrypt_json(data: dict) -> str:
    return encrypt_str(json.dumps(data)) if data else ""


def decrypt_json(token: str) -> dict:
    value = decrypt_str(token)
    return json.loads(value) if value else {}
