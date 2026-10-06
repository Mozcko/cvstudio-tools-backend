import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from src.core import security
from src.core.config import settings

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch):
    client = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=PRIVATE_KEY.public_key()))
    monkeypatch.setattr(security, "_get_jwks_client", lambda: client)


def make_token(key=PRIVATE_KEY, algorithm="RS256", **overrides):
    now = int(time.time())
    claims = {
        "sub": "user_abc",
        "iss": settings.CLERK_ISSUER,
        "iat": now,
        "exp": now + 60,
        "azp": "http://localhost:4321",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=algorithm)


def authenticate(token):
    return security.get_current_user_id(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))


def test_valid_token_returns_subject():
    assert authenticate(make_token()) == "user_abc"


def test_token_without_azp_is_accepted():
    assert authenticate(make_token(azp=None)) == "user_abc"


@pytest.mark.parametrize(
    "token",
    [
        make_token(key=OTHER_KEY),  # signed by someone else
        make_token(exp=int(time.time()) - 120),  # expired
        make_token(iss="https://evil.example"),  # wrong issuer
        make_token(azp="https://evil.example"),  # wrong authorized party
        make_token(sub=None),  # no subject
        jwt.encode({"sub": "user_abc"}, "secret", algorithm="HS256"),  # wrong algorithm
        jwt.encode({"sub": "user_abc"}, None, algorithm="none"),  # unsigned
        "not-a-token",
    ],
)
def test_invalid_tokens_are_rejected(token):
    with pytest.raises(HTTPException) as exc:
        authenticate(token)
    assert exc.value.status_code == 401
