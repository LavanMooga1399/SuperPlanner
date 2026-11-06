"""T-P1 (M6-DESIGN 9): RFC 8291 appendix A test vector - identical body; VAPID header shape."""

from __future__ import annotations

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from superplanner.push import ece, vapid
from superplanner.push.vapid import b64u, b64u_decode as d

PLAIN = b"When I grow up, I want to be a watermelon"
AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
UA_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
SALT = "DGv6ra1nlYgDCS1FRnbzlw"
BODY = ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEq"
        "KK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


def _priv(s: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(d(s), "big"), ec.SECP256R1())


def test_rfc8291_appendix_a_vector():
    body = ece.encrypt(PLAIN, d(UA_PUBLIC), d(AUTH), salt=d(SALT), as_private=_priv(AS_PRIVATE))
    assert b64u(body) == BODY
    assert ece.decrypt(d(BODY), _priv(UA_PRIVATE), d(AUTH)) == PLAIN


def test_random_round_trip_and_size_limit():
    ua = ec.generate_private_key(ec.SECP256R1())
    pub = ua.public_key().public_bytes(ece.serialization.Encoding.X962,
                                       ece.serialization.PublicFormat.UncompressedPoint)
    body = ece.encrypt(b'{"title":"x"}', pub, b"0123456789abcdef")
    assert ece.decrypt(body, ua, b"0123456789abcdef") == b'{"title":"x"}'
    try:
        ece.encrypt(b"x" * 4000, pub, b"0123456789abcdef")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_vapid_authorization_header():
    pem = vapid.generate_private_key_pem()
    pem = vapid.check_private_key(pem.replace("\n", "\\n"))     # env-style escaped newlines are accepted
    h = vapid.authorization(pem, "mailto:ops@hbl.example", "https://fcm.googleapis.com/fcm/send/abc", now=1000.0)
    assert h.startswith("vapid t=") and f", k={vapid.public_key(pem)}" in h
    token = h[len("vapid t="):h.index(",")]
    key = vapid._key(pem).public_key()
    claims = jwt.decode(token, key, algorithms=["ES256"], audience="https://fcm.googleapis.com",
                        options={"verify_exp": False})
    assert claims == {"aud": "https://fcm.googleapis.com", "exp": 1000 + 12 * 3600, "sub": "mailto:ops@hbl.example"}
    assert len(d(vapid.public_key(pem))) == 65
