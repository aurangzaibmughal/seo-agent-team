import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

BACKEND_ENV = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

class Settings(BaseSettings):
    PROJECT_NAME: str = "SEO Agent Team API"
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    
    # Supabase (optional for standalone local dev, required for full cloud state)
    SUPABASE_URL: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None
    SUPABASE_ANON_KEY: Optional[str] = None
    
    # Crawler Limits (Rule capped at 200)
    MAX_CRAWL_PAGES: int = 200
    CRAWL_CONCURRENCY: int = 5
    CRAWL_TIMEOUT_SECONDS: int = 15
    USER_AGENT: str = "Mozilla/5.0 (compatible; SEOAgentTeamBot/1.0; +https://seo-agent-team.local)"
    
    # PageSpeed Insights API (M2)
    PSI_API_KEY: Optional[str] = None
    PSI_MAX_PAGES: int = 5
    PSI_TIMEOUT_SECONDS: int = 25

    # LLM / Gemini (M2)
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODELS: str = "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.6-flash"
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"

    @property
    def gemini_model_list(self) -> list[str]:
        if self.GEMINI_MODELS:
            return [m.strip() for m in self.GEMINI_MODELS.split(",") if m and m.strip()]
        return [self.GEMINI_MODEL]

    # Google OAuth & APIs (M3)
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"
    TOKEN_ENCRYPTION_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=[BACKEND_ENV, ".env"],
        extra="ignore"
    )

settings = Settings()
