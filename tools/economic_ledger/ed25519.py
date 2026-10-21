"""Pure Python implementation of Ed25519 signature verification and signing (RFC 8032).

Zero external dependencies; standard library integer arithmetic and hashlib only.
"""
from __future__ import annotations

import hashlib

# ─────────────────────────────────────────────────────────────────────────────
# Curve Parameters for Ed25519
# ─────────────────────────────────────────────────────────────────────────────
p = 2**255 - 19
q = 2**252 + 27742317777372353535851937790883648493


def _inv(x: int) -> int:
    return pow(x, p - 2, p)


d = (-121665 * _inv(121666)) % p
I = pow(2, (p - 1) // 4, p)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(d * y * y + 1)
    x = pow(xx, (p + 3) // 8, p)
    if (x * x - xx) % p != 0:
        x = (x * I) % p
    if x % 2 != 0:
        x = p - x
    return x


_By = (4 * _inv(5)) % p
_Bx = _xrecover(_By)
B = (_Bx, _By)


def _edwards_add(P: tuple[int, int], Q: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + d * x1 * x2 * y1 * y2) % p
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - d * x1 * x2 * y1 * y2) % p
    return (x3, y3)


def _scalarmult(P: tuple[int, int], e: int) -> tuple[int, int]:
    if e == 0:
        return (0, 1)
    Q = _scalarmult(P, e // 2)
    Q = _edwards_add(Q, Q)
    if e & 1:
        Q = _edwards_add(Q, P)
    return Q


def _encodepoint(P: tuple[int, int]) -> bytes:
    x, y = P
    bits = [(y >> i) & 1 for i in range(255)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(32))


def _decodepoint(s: bytes) -> tuple[int, int]:
    y = sum(2**i * ((s[i // 8] >> (i % 8)) & 1) for i in range(255))
    x = _xrecover(y)
    if (x & 1) != ((s[31] >> 7) & 1):
        x = p - x
    return (x, y)


def _hint(m: bytes) -> int:
    h = hashlib.sha512(m).digest()
    return int.from_bytes(h, "little")


def public_key_from_secret(secret_key: bytes) -> bytes:
    """Derives a 32-byte Ed25519 public key from a 32-byte private seed."""
    if len(secret_key) != 32:
        raise ValueError("Secret key seed must be exactly 32 bytes")
    h = hashlib.sha512(secret_key).digest()
    a = 2**254 + sum(2**i * ((h[i // 8] >> (i % 8)) & 1) for i in range(3, 254))
    A = _scalarmult(B, a)
    return _encodepoint(A)


def sign(message: bytes, secret_key: bytes, public_key: bytes) -> bytes:
    """Produces a 64-byte Ed25519 signature."""
    if len(secret_key) != 32 or len(public_key) != 32:
        raise ValueError("Secret key and public key must be 32 bytes each")
    h = hashlib.sha512(secret_key).digest()
    a = 2**254 + sum(2**i * ((h[i // 8] >> (i % 8)) & 1) for i in range(3, 254))
    r = _hint(h[32:] + message)
    R = _scalarmult(B, r)
    R_bytes = _encodepoint(R)
    k = _hint(R_bytes + public_key + message)
    S = (r + k * a) % q
    return R_bytes + S.to_bytes(32, "little")


def verify(signature: bytes, message: bytes, public_key: bytes) -> bool:
    """Verifies a 64-byte Ed25519 signature against a message and 32-byte public key."""
    if len(signature) != 64 or len(public_key) != 32:
        return False
    try:
        R = _decodepoint(signature[:32])
        A = _decodepoint(public_key)
        S = int.from_bytes(signature[32:], "little")
        if S >= q:
            return False
        k = _hint(signature[:32] + public_key + message)
        v1 = _scalarmult(B, S)
        v2 = _edwards_add(R, _scalarmult(A, k))
        return v1 == v2
    except Exception:
        return False
