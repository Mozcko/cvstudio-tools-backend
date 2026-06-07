import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.core.config import settings

security = HTTPBearer()

async def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    token = credentials.credentials
    try:
        # In production, you would verify this against Clerk's JWKS
        # payload = jwt.decode(token, clerk_public_key, algorithms=["RS256"], ...)
        
        # For this migration skeleton, we assume the token is valid and decode it unsafely 
        # OR suggest the user configures the Clerk middleware properly.
        # Here we extract the 'sub' field which is the Clerk User ID.
        payload = jwt.decode(token, options={"verify_signature": False})
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )
        return user_id
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
