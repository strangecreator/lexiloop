import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    explicit = settings.TOKEN_ENCRYPTION_KEY.strip()
    if explicit:
        key = explicit.encode()
    else:
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(value: str | None) -> str:
    value = (value or '').strip()
    return _fernet().encrypt(value.encode()).decode() if value else ''


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ''
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError('Stored provider token cannot be decrypted. Check TOKEN_ENCRYPTION_KEY.') from exc
