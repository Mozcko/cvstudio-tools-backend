import logging
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError

from src.core.config import settings

logger = logging.getLogger(__name__)

security = HTTPBearer()

_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            f"{settings.CLERK_ISSUER}/.well-known/jwks.json",
            cache_keys=True,
            lifespan=3600,
        )
    return _jwks_client


def decode_clerk_token(token: str) -> Dict[str, Any]:
    """Verifies a Clerk session token and returns its claims."""
    signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=settings.CLERK_ISSUER,
        options={"require": ["exp", "iat", "sub"], "verify_aud": False},
        leeway=5,
    )
    azp = payload.get("azp")
    if azp and azp.rstrip("/") not in settings.authorized_parties:
        raise jwt.InvalidTokenError("Unauthorized party")
    return payload


# Plain `def` on purpose: the JWKS lookup is blocking, so FastAPI runs this in its threadpool.
def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    try:
        payload = decode_clerk_token(credentials.credentials)
    except PyJWKClientConnectionError:
        logger.exception("Could not reach the identity provider")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    return payload["sub"]
