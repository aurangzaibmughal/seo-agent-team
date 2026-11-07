# SEO Agent Team (Multi-Agent SEO Application)

An autonomous, multi-agent SEO engineering platform built according to [PLAN.md](PLAN.md).

> **Core Principle:** Deterministic code collects crawl & API data. Agents reason over that verified data. Every issue carries evidence; verifiers reject unsubstantiated claims.

---

## Architecture (Option 1: Full-Stack Monorepo)

- **Frontend:** Next.js (App Router, React 18, Tailwind CSS, Lucide icons)
- **Backend Worker:** Python (FastAPI + Pydantic v2 + httpx + BeautifulSoup4 / selectolax)
- **Database & Realtime:** Supabase Postgres schema (`supabase/schema.sql`) with automatic local SQLite fallback for standalone local development
- **Test Suite:** Pytest + Pytest-Asyncio unit test coverage for crawler parser and boundary limits

---

## Project Structure

```text
seo-agent-team/
├── PLAN.md                   # Source masterplan & milestone specifications
├── OPEN_QUESTIONS.md         # Open questions tracked per Rule 7
├── start-backend.bat         # 1-click startup for FastAPI backend (Port 8000)
├── start-frontend.bat        # 1-click startup for Next.js frontend (Port 3000)
├── supabase/
│   └── schema.sql            # Postgres DDL schema (projects, jobs, crawl_pages, agent_runs, reports)
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI entry point & CORS configuration
│   │   ├── core/
│   │   │   ├── config.py     # Environment settings & crawler parameters
│   │   │   └── db.py         # Supabase client + local SQLite fallback adapter
│   │   ├── models/
│   │   │   └── schemas.py    # Pydantic schemas (JobCreate, CrawlPage, CrawlStats)
│   │   ├── crawler/
│   │   │   ├── engine.py     # Asynchronous bounded crawler (max 200 pages safety cap)
│   │   │   └── parser.py     # HTML parser (title, meta, h1, canonical, word count, indexability)
│   │   └── api/
│   │       └── routes_jobs.py# REST endpoints (/api/jobs, /pages, /stats)
│   ├── tests/
│   │   ├── test_crawler_parser.py # Unit tests for SEO HTML element parsing
│   │   └── test_crawler_engine.py # Unit tests for max pages capping and async crawler
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/
    │   └── app/
    │       ├── layout.tsx
    │       ├── page.tsx      # Screaming Frog-style audit table, live metrics & inspector drawer
    │       └── globals.css
    ├── tailwind.config.ts
    └── package.json
```

---

## Milestone 1 Status & Test Verification

### Milestone 1 Goal:
- [x] URL input page
- [x] Jobs table with live progress tracking
- [x] FastAPI async crawler (hard-capped at 200 pages)
- [x] `crawl_pages` data stored in DB
- [x] Screaming Frog-style results table with live updates, tabs (All, Issues, 404s, Missing Meta, Non-Indexable), search, and technical page inspector drawer.
- [x] 100% passing unit tests for crawler parser and boundaries.

### Running Backend Unit Tests:
```powershell
cd backend
.\venv\Scripts\python.exe -m pytest tests
```

### Running the Application:
1. **Backend:**
   Double-click `start-backend.bat` or run:
   ```powershell
   cd backend
   .\venv\Scripts\activate.bat
   uvicorn app.main:app --reload --port 8000
   ```
2. **Frontend:**
   Double-click `start-frontend.bat` or run:
   ```powershell
   cd frontend
   npm run dev
   ```
3. Open `http://localhost:3000` in your browser.
