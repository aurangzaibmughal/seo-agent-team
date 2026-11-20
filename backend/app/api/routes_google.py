from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from app.core.config import settings
from app.core.db import DBManager
from app.services.google_auth import (
    get_google_auth_url,
    exchange_code_for_tokens,
    get_valid_access_token
)
from app.services.google_data import list_gsc_sites, list_ga4_properties

router = APIRouter(prefix="/api/google", tags=["Google OAuth & Analytics"])
auth_router = APIRouter(prefix="/api/auth/google", tags=["Google OAuth & Analytics"])

@router.get("/auth-url")
def get_auth_url(user_id: str = "default_user"):
    """Returns the Google OAuth consent URL."""
    url = get_google_auth_url(user_id)
    return {"auth_url": url, "configured": bool(settings.GOOGLE_CLIENT_ID)}

@auth_router.get("/callback")
@router.get("/callback")
async def oauth_callback(code: str = Query(...), state: str = Query("default_user")):
    """Handles Google OAuth callback code."""
    try:
        result = await exchange_code_for_tokens(code=code, user_id=state)
        email = result.get("email", "")
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Google Account Connected</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #0f172a; color: #f8fafc; }}
                .card {{ background: #1e293b; padding: 2.5rem; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); text-align: center; max-width: 450px; border: 1px solid #334155; }}
                h2 {{ color: #10b981; margin-bottom: 0.5rem; font-size: 1.5rem; }}
                p {{ color: #94a3b8; font-size: 0.95rem; line-height: 1.5; }}
                .email {{ color: #38bdf8; font-weight: 600; font-family: monospace; background: #0f172a; padding: 0.25rem 0.5rem; border-radius: 4px; }}
                .btn {{ margin-top: 1.5rem; display: inline-block; background: #3b82f6; color: white; padding: 0.6rem 1.2rem; border-radius: 6px; text-decoration: none; font-weight: 500; cursor: pointer; border: none; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h2>&#10004; Google Account Connected!</h2>
                <p>Successfully authorized: <span class="email">{email}</span></p>
                <p>Google Search Console & Google Analytics 4 permissions granted.</p>
                <button class="btn" onclick="window.close()">Close this tab</button>
                <p style="font-size: 0.8rem; margin-top: 1rem; color: #64748b;">You can close this tab and return to the SEO Agent Team dashboard.</p>
            </div>
            <script>
                setTimeout(function() {{
                    window.close();
                }}, 3000);
            </script>
        </body>
        </html>
        """
        return HTMLResponse(content=html, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {str(e)}")

@router.get("/status")
def get_connection_status(user_id: str = "default_user"):
    """Checks whether the user has an active Google connection."""
    conn = DBManager.get_google_connection(user_id)
    if not conn:
        return {"connected": False, "email": None}
    return {
        "connected": True,
        "email": conn.get("google_email"),
        "created_at": conn.get("created_at"),
        "scopes": conn.get("scopes", [])
    }

@router.post("/disconnect")
def disconnect_google(user_id: str = "default_user"):
    """Revokes and disconnects Google connection."""
    DBManager.revoke_google_connection(user_id)
    return {"status": "success", "message": "Google account disconnected"}

@router.get("/sites")
async def get_gsc_sites(user_id: str = "default_user"):
    """Lists available Search Console sites for the connected user."""
    token = await get_valid_access_token(user_id)
    if not token:
        # Dev fallback when Google OAuth is not configured
        return [
            {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"}
        ]
    sites = await list_gsc_sites(token)
    return sites

@router.get("/properties")
async def get_ga4_properties(user_id: str = "default_user"):
    """Lists available GA4 properties for the connected user."""
    token = await get_valid_access_token(user_id)
    if not token:
        # Dev fallback
        return [
            {"propertyId": "987654321", "displayName": "Example Production", "account": "Example LLC"}
        ]
    props = await list_ga4_properties(token)
    return props
