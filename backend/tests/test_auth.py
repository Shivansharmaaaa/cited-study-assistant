SECRET = "test-secret-key-that-is-long-enough-1234"
import time

import jwt

from app.security import LoginThrottle, create_token, decode_token, hash_password, verify_password
from tests.conftest import register_and_login


def test_password_hash_roundtrip_and_salting():
    h1, h2 = hash_password("s3cret-pass"), hash_password("s3cret-pass")
    assert h1 != h2  # per-hash random salt
    assert verify_password("s3cret-pass", h1)
    assert not verify_password("wrong", h1)
    assert not verify_password("x", "garbage")


def test_register_rejects_duplicate_and_weak_input(client):
    assert client.post("/auth/register", json={"email": "a@example.com", "password": "longenough1"}).status_code == 201
    dup = client.post("/auth/register", json={"email": "A@Example.com", "password": "longenough1"})
    assert dup.status_code == 409  # emails are case-insensitive
    assert client.post("/auth/register", json={"email": "b@example.com", "password": "short"}).status_code == 422
    assert client.post("/auth/register", json={"email": "not-an-email", "password": "longenough1"}).status_code == 422


def test_login_wrong_password_and_unknown_email_look_identical(client):
    client.post("/auth/register", json={"email": "a@example.com", "password": "longenough1"})
    bad_pw = client.post("/auth/login", json={"email": "a@example.com", "password": "nope-nope-1"})
    unknown = client.post("/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-1"})
    assert bad_pw.status_code == unknown.status_code == 401
    assert bad_pw.json() == unknown.json()


def test_login_throttle_blocks_after_repeated_failures(client):
    client.post("/auth/register", json={"email": "a@example.com", "password": "longenough1"})
    for _ in range(5):
        assert client.post("/auth/login", json={"email": "a@example.com", "password": "bad-bad-bad"}).status_code == 401
    blocked = client.post("/auth/login", json={"email": "a@example.com", "password": "longenough1"})
    assert blocked.status_code == 429


def test_throttle_window_expires():
    now = [0.0]
    t = LoginThrottle(max_failures=2, window_s=10, clock=lambda: now[0])
    t.record_failure("k"); t.record_failure("k")
    assert t.is_blocked("k")
    now[0] = 11.0
    assert not t.is_blocked("k")


def test_protected_routes_require_valid_token(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    headers = register_and_login(client)
    assert client.get("/me", headers=headers).json()["email"] == "a@example.com"


def test_token_signed_with_other_key_or_expired_is_rejected():
    forged = create_token(1, "other-secret-that-is-long-enough-123456", 5)
    assert decode_token(forged, SECRET) is None
    expired = jwt.encode({"sub": "1", "exp": int(time.time()) - 10}, SECRET, algorithm="HS256")
    assert decode_token(expired, SECRET) is None
    none_alg = jwt.encode({"sub": "1"}, key=None, algorithm="none")
    assert decode_token(none_alg, SECRET) is None  # alg=none must not be accepted
