from datetime import UTC, datetime
from uuid import uuid4

import jwt
import pytest

from services.api.adapters.clock import FakeClock
from services.api.adapters.jwt_issuer import HmacTokenIssuer
from services.api.domain.errors import Unauthorized

UID = uuid4()
SECRET = "unit-test-secret-at-least-32-bytes-long"


def _issuer(ttl_seconds: int = 60) -> tuple[HmacTokenIssuer, FakeClock]:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    return HmacTokenIssuer(SECRET, ttl_seconds=ttl_seconds, clock=clock), clock


def test_issue_then_verify_roundtrip() -> None:
    issuer, _ = _issuer()
    assert issuer.verify(issuer.issue(UID)) == UID


def test_jwt_expired_raises_unauthorized() -> None:
    issuer, clock = _issuer(ttl_seconds=60)
    token = issuer.issue(UID)
    clock.advance(seconds=61)
    with pytest.raises(Unauthorized):
        issuer.verify(token)


def test_jwt_valid_just_before_expiry() -> None:
    issuer, clock = _issuer(ttl_seconds=60)
    token = issuer.issue(UID)
    clock.advance(seconds=59)
    assert issuer.verify(token) == UID


def test_jwt_tampered_signature_raises() -> None:
    issuer, _ = _issuer()
    token = issuer.issue(UID)
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload}.{sig[:-2]}xx"
    with pytest.raises(Unauthorized):
        issuer.verify(tampered)


def test_jwt_signed_with_other_secret_raises() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    other = HmacTokenIssuer("another-secret-at-least-32-bytes-long", ttl_seconds=60, clock=clock)
    issuer, _ = _issuer()
    with pytest.raises(Unauthorized):
        issuer.verify(other.issue(UID))


def test_jwt_garbage_raises() -> None:
    issuer, _ = _issuer()
    with pytest.raises(Unauthorized):
        issuer.verify("not-a-jwt")


def test_jwt_without_subject_raises() -> None:
    issuer, _ = _issuer()
    token = jwt.encode({"exp": 4102444800}, SECRET, algorithm="HS256")
    with pytest.raises(Unauthorized):
        issuer.verify(token)


def test_fake_clock_advance() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    clock.advance(seconds=90)
    assert clock.now() == datetime(2026, 1, 1, 0, 1, 30, tzinfo=UTC)
