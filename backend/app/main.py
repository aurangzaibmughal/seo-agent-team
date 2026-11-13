from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes_jobs import router as jobs_router
from app.api.routes_google import router as google_router, auth_router
from app.api.routes_review import router as review_router
from app.api.routes_comparator import router as comparator_router
from app.api.routes_asana import router as asana_router
from app.api.routes_auth import router as admin_auth_router
from app.core.db import DBManager, init_db
from app.core.security import verify_session_token
from fastapi import Request
from fastapi.responses import JSONResponse


def startup_recovery():
    # Milestone 6 Batch C: Secure by default secrets & configuration enforcement
    if settings.ENVIRONMENT not in ("development", "test"):
        missing_secrets = []
        if not settings.APP_ADMIN_PASSWORD_HASH:
            missing_secrets.append("APP_ADMIN_PASSWORD_HASH")
        if not settings.SESSION_SECRET:
            missing_secrets.append("SESSION_SECRET")
        if not settings.TOKEN_ENCRYPTION_KEY:
            missing_secrets.append("TOKEN_ENCRYPTION_KEY")
        if missing_secrets:
            raise RuntimeError(f"FATAL: Production mode refuses to start without required secrets: {', '.join(missing_secrets)}")

        # No wildcard CORS allowed in production/non-dev
        if "*" in settings.cors_origin_list:
            raise RuntimeError("FATAL: Wildcard '*' CORS origin is strictly forbidden in production mode. Specify explicit allowed origins.")

    init_db()
    interrupted_count = DBManager.mark_stuck_jobs_as_interrupted()
    if interrupted_count > 0:
        print(f"Startup recovery: marked {interrupted_count} stuck running job(s) as interrupted.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_recovery()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Multi-agent SEO platform API - Milestone 1, 2, 3, 4, 5 & 6",
    version="1.6.0",
    lifespan=lifespan
)


@app.middleware("http")
async def production_auth_middleware(request: Request, call_next):
    """Enforces authentication on all API routes unless explicitly in development or test environment."""
    if settings.ENVIRONMENT in ("development", "test"):
        return await call_next(request)

    path = request.url.path
    # Allow preflight, health checks, docs, and authentication endpoints
    if (
        request.method == "OPTIONS"
        or path in ("/", "/healthz", "/docs", "/openapi.json", "/redoc")
        or path.startswith("/api/auth/")
    ):
        return await call_next(request)

    # Check session cookie or Authorization header
    token = request.cookies.get("session_id")
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not token and auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    payload = verify_session_token(token) if token else None
    if not payload:
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required. Please authenticate via /api/auth/login."}
        )

    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(google_router)
app.include_router(auth_router)
app.include_router(admin_auth_router)
app.include_router(review_router)
app.include_router(comparator_router)
app.include_router(asana_router)

@app.get("/")
def root_info():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "version": "1.6.0"
    }

@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "environment": settings.ENVIRONMENT,
        "service": settings.PROJECT_NAME
    }
