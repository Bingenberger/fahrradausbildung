"""Passwort-Hashing (argon2id) und Token-Erzeugung."""

import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher(type=Type.ID)

# 32 Byte = 256 Bit Zufall, URL-sicher kodiert (Spezifikation 9: mindestens 128 Bit).
TOKEN_BYTES = 32


def passwort_hashen(passwort: str) -> str:
    return _hasher.hash(passwort)


def passwort_pruefen(passwort_hash: str, passwort: str) -> bool:
    try:
        return _hasher.verify(passwort_hash, passwort)
    except (VerificationError, InvalidHashError):
        return False


def passwort_braucht_rehash(passwort_hash: str) -> bool:
    return _hasher.check_needs_rehash(passwort_hash)


def neues_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)
