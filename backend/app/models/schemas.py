from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

class JobCreate(BaseModel):
    url: str = Field(..., description="Target website URL to crawl and audit")
    max_pages: int = Field(default=50, ge=1, le=200, description="Max pages limit (Rule capped at 200)")
    competitor_domains: Optional[List[str]] = Field(default=None, description="Optional competitor domains (up to 3)")
    is_demo: bool = Field(default=False, description="Whether this is a demo job")
    project_id: Optional[str] = None

class CrawlPage(BaseModel):
    id: Optional[str] = None
    job_id: str
    url: str
    status_code: int
    title: Optional[str] = None
    meta_desc: Optional[str] = None
    h1: Optional[str] = None
    canonical: Optional[str] = None
    word_count: int = 0
    links_out: int = 0
    indexable: bool = True
    indexability_status: str = "indexable"
    redirect_url: Optional[str] = None
    content_type: str = "text/html"
    response_time_ms: int = 0
    outlinks_list: List[str] = []
    created_at: Optional[datetime] = None

class JobResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    target_url: str
    status: str
    current_step: str
    max_pages: int
    pages_crawled: int
    error: Optional[str] = None
    cost_usd: float = 0.0
    created_at: datetime
    updated_at: datetime

class CrawlStats(BaseModel):
    total_pages: int = 0
    status_200: int = 0
    status_3xx: int = 0
    status_4xx: int = 0
    status_5xx: int = 0
    missing_title: int = 0
    missing_meta: int = 0
    missing_h1: int = 0
    duplicate_titles: int = 0
    non_indexable: int = 0
    avg_response_time_ms: float = 0.0
