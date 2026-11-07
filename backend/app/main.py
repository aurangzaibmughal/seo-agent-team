from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes_jobs import router as jobs_router
from app.api.routes_google import router as google_router, auth_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Multi-agent SEO platform API - Milestone 1, 2 & 3",
    version="1.3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(google_router)
app.include_router(auth_router)

@app.get("/")
def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "milestone": "M1 - Crawler + Audit table",
        "version": "1.0.0"
    }
