from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import (
    verify_password,
    create_session_token,
    verify_session_token,
    get_client_ip,
    login_rate_limiter,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    """Authenticates owner password against APP_ADMIN_PASSWORD_HASH and issues secure session cookie with rate limiting."""
    client_ip = get_client_ip(request)
    allowed, retry_after = login_rate_limiter.is_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Please retry after {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)}
        )

    expected_hash = settings.APP_ADMIN_PASSWORD_HASH
    if not expected_hash:
        raise HTTPException(
            status_code=500,
            detail="Server authentication misconfigured: APP_ADMIN_PASSWORD_HASH must be configured in environment."
        )

    if not verify_password(payload.password, expected_hash):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    token = create_session_token({"role": "admin", "sub": "site_owner"})
    is_dev = settings.ENVIRONMENT in ("development", "test")
    response.set_cookie(
        key="session_id",
        value=token,
        httponly=True,
        samesite="lax",
        secure=not is_dev,
        max_age=86400 * 7
    )
    return {"status": "success", "message": "Successfully authenticated"}


@router.post("/logout")
async def logout(response: Response):
    """Clears the session cookie."""
    response.delete_cookie(key="session_id")
    return {"status": "success", "message": "Logged out successfully"}


@router.get("/status")
async def auth_status(request: Request):
    """Returns current auth status and whether production security mode is active."""
    cookie = request.cookies.get("session_id")
    auth_header = request.headers.get("Authorization")
    token = cookie
    if not token and auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    payload = verify_session_token(token) if token else None
    return {
        "authenticated": bool(payload),
        "production_mode": settings.ENVIRONMENT == "production",
        "environment": settings.ENVIRONMENT
    }
