import urllib.parse
import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from app.core.config import settings
from app.core.security import encrypt_token, decrypt_token
from app.core.db import DBManager

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
    "openid",
    "email",
    "profile"
]

def get_google_auth_url(user_id: str = "default_user") -> str:
    """Generates the Google OAuth consent URL with read-only scopes."""
    if not settings.GOOGLE_CLIENT_ID:
        # Development fallback auth URL
        return f"/api/auth/google/dev-connect?user_id={user_id}"

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": user_id
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

async def exchange_code_for_tokens(code: str, user_id: str = "default_user") -> Dict[str, Any]:
    """Exchanges authorization code for access & refresh tokens, encrypts and stores refresh token."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise ValueError("Google OAuth credentials not configured")

    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_ENDPOINT, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code"
        }, timeout=15.0)

        if resp.status_code != 200:
            raise Exception(f"OAuth token exchange failed: {resp.text[:150]}")

        token_data = resp.json()
        refresh_token = token_data.get("refresh_token")
        access_token = token_data.get("access_token")

        # Fetch user profile to get google_email
        email = "user@example.com"
        userinfo_resp = await client.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={
            "Authorization": f"Bearer {access_token}"
        })
        if userinfo_resp.status_code == 200:
            email = userinfo_resp.json().get("email", email)

        if refresh_token:
            encrypted_refresh = encrypt_token(refresh_token)
            DBManager.save_google_connection(
                user_id=user_id,
                email=email,
                encrypted_refresh_token=encrypted_refresh,
                scopes=SCOPES
            )

        return {
            "status": "connected",
            "email": email,
            "has_refresh_token": bool(refresh_token)
        }

async def get_valid_access_token(user_id: str = "default_user") -> Optional[str]:
    """Retrieves and decrypts refresh token, returns fresh access token."""
    conn = DBManager.get_google_connection(user_id)
    if not conn or not conn.get("encrypted_refresh_token"):
        return None

    decrypted_refresh = decrypt_token(conn["encrypted_refresh_token"])
    if not decrypted_refresh:
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_ENDPOINT, data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": decrypted_refresh,
            "grant_type": "refresh_token"
        }, timeout=15.0)

        if resp.status_code == 200:
            return resp.json().get("access_token")
        elif resp.status_code in (400, 401):
            # Token revoked or expired
            DBManager.revoke_google_connection(user_id)
            return None
        return None
