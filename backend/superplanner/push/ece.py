"""RFC 8291 message encryption for Web Push (`Content-Encoding: aes128gcm`, RFC 8188 single record).

`encrypt(plaintext, ua_public, auth_secret)` -> body (header + ciphertext); `salt` and `as_private` are only given by
the test vectors (RFC 8291 appendix A). `decrypt` exists for tests and the local push-service stub."""

from __future__ import annotations

import os
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hmac import HMAC

RECORD_SIZE = 4096
MAX_PLAINTEXT = 3993          # one record: 4096 - 86 header - 16 tag - 1 delimiter


def _hmac(key: bytes, data: bytes) -> bytes:
    h = HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize()


def _expand(prk: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand for length <= 32 (one block)."""
    return _hmac(prk, info + b"\x01")[:length]


def _public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _keys(ecdh: bytes, auth_secret: bytes, ua_public: bytes, as_public: bytes, salt: bytes) -> tuple[bytes, bytes]:
    prk_key = _hmac(auth_secret, ecdh)                                    # HKDF-Extract(auth_secret, ecdh_secret)
    ikm = _expand(prk_key, b"WebPush: info\x00" + ua_public + as_public, 32)
    prk = _hmac(salt, ikm)                                                # HKDF-Extract(salt, IKM)
    return _expand(prk, b"Content-Encoding: aes128gcm\x00", 16), _expand(prk, b"Content-Encoding: nonce\x00", 12)


def encrypt(plaintext: bytes, ua_public: bytes, auth_secret: bytes, *, salt: bytes | None = None,
            as_private: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    if len(plaintext) > MAX_PLAINTEXT:
        raise ValueError("push payload too large")
    if len(auth_secret) != 16 or len(ua_public) != 65 or ua_public[0] != 4:
        raise ValueError("invalid subscription keys")
    salt = salt if salt is not None else os.urandom(16)
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    as_public = _public_bytes(as_private.public_key())
    ecdh = as_private.exchange(ec.ECDH(), ua_key)
    cek, nonce = _keys(ecdh, auth_secret, ua_public, as_public, salt)
    ct = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    return salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public + ct


def decrypt(body: bytes, ua_private: ec.EllipticCurvePrivateKey, auth_secret: bytes) -> bytes:
    salt, (rs, idlen) = body[:16], struct.unpack("!IB", body[16:21])
    as_public = body[21:21 + idlen]
    ct = body[21 + idlen:]
    ua_public = _public_bytes(ua_private.public_key())
    as_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    ecdh = ua_private.exchange(ec.ECDH(), as_key)
    cek, nonce = _keys(ecdh, auth_secret, ua_public, as_public, salt)
    padded = AESGCM(cek).decrypt(nonce, ct, None)
    end = padded.rstrip(b"\x00")
    if not end.endswith(b"\x02"):
        raise ValueError("bad padding delimiter")
    del rs
    return end[:-1]
