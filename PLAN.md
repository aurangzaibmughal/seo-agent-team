# PLAN.md — SEO Agent Team (multi-agent SEO app)

> Give this file to Antigravity first. Build ONE milestone at a time. After each milestone, run the tests listed under it before moving on.

## 1. Goal
A web app where a user enters a website URL and a team of AI agents runs the full SEO workflow:
**crawl → audit → research → strategy → content/code fixes → verify → report.**

Separate product from SEO/AEO/GEO-FORGE (FORGE stays untouched). FORGE may later be called as an optional tool via API.

## 2. Core principle
- **Deterministic code collects data** (crawler, API calls). 
- **Agents reason over that data** (prioritise, explain, write fixes, write report).
- Never let an LLM do crawling or fetch numbers from memory.

## 3. Scope (v1)
1. Technical crawl and audit (Screaming Frog-style): status codes, redirects, titles, meta, headings, canonicals, duplicates, broken links, sitemap, robots, schema, indexability
2. Speed + mobile audit (PageSpeed Insights API / Lighthouse)
3. Keyword + competitor research
4. Strategy: prioritised 30-day plan
5. Content: briefs, on-page copy (title/meta/FAQ), internal linking suggestions from crawl graph
6. SEO code generator: meta tags, canonical, JSON-LD, sitemap.xml, robots.txt, llms.txt (Next.js and WordPress first)
7. Reporting from Google Search Console + GA4
8. Export: PDF / CSV / Excel report; optional tasks export to Asana

**Out of scope for v1:** auto-editing client sites, own backlink index, scraping Google results.

## 4. Stack
- Frontend: Next.js (App Router) + Tailwind
- Backend / agent worker: Python + FastAPI (long jobs run here, NOT in Vercel serverless)
- Agent framework: Google ADK (swappable; keep agents behind a thin interface)
- Model: current Gemini Flash model for bulk steps, stronger model for strategy/report (verify model names are still available)
- DB/Auth/Realtime: Supabase (Postgres, RLS, Realtime for live progress)
- Queue: simple jobs table + worker polling (upgrade to a queue later)
- Crawler: httpx + selectolax/BeautifulSoup; Playwright only for JS-rendered pages

## 5. Agents
| Agent | Role | Tools (code, not LLM) | Output |
|---|---|---|---|
| Orchestrator | Plans job, runs agents in order/parallel, handles failures | job table | job status |
| Crawler/Detector | Crawl site, detect platform (WordPress/Next.js/Shopify/HTML) | crawler | `crawl_data` |
| Technical | Interpret crawl + speed/mobile data, list issues by severity | PSI API, crawl_data | `tech_issues` |
| Research | Keywords, intent, competitors, content gaps | keyword API (DataForSEO/SEMrush/Ahrefs), GSC | `research` |
| Strategist | Prioritised 30-day plan (impact vs effort) | all prior outputs | `strategy` |
| Content | Briefs, titles/meta, FAQ, internal links | crawl graph, research | `content_plan` |
| Code Generator | Platform-specific SEO code | templates + validators | `code_bundle` |
| Verifier | Checks every claim and code block against data/validators | JSON-LD validator, HTML lint, crawl_data | `verified` / `rejected` + reasons |
| Monitor | Pulls GSC + GA4 trends | GSC API, GA4 API | `performance` |
| Reporter | Builds final report | all verified outputs | PDF/CSV/XLSX |

## 6. Agent-to-agent communication
Agents do NOT chat freely. They hand off **structured JSON through shared job state** in the database.

```json
{
  "job_id": "uuid",
  "agent": "technical",
  "status": "done",
  "inputs": ["crawl_data"],
  "output": { "issues": [{ "id": "T-001", "type": "missing_meta_description", "severity": "high", "urls": ["..."], "evidence": "crawl row ids", "fix_hint": "..." }] },
  "confidence": 0.9,
  "created_at": "iso8601"
}
```
Rule: every issue/claim must carry `evidence` pointing to real crawl/API data. Verifier rejects anything without it.

## 7. Database (Supabase)
- `projects` (id, user_id, url, platform, created_at)
- `jobs` (id, project_id, status, current_step, error, cost_usd, created_at)
- `agent_runs` (id, job_id, agent, status, input_ref, output_json, started_at, finished_at)
- `crawl_pages` (id, job_id, url, status_code, title, meta_desc, h1, canonical, word_count, links_out, indexable)
- `reports` (id, job_id, file_url, format)
- RLS on every table: users only see their own rows.

## 8. External APIs
- Google Search Console API + GA4 Data API (OAuth, read-only scopes)
- PageSpeed Insights API
- Keyword/backlink data: one paid provider (DataForSEO, SEMrush or Ahrefs). Backlinks and rank tracking for non-owned sites need this.
- Asana API (optional)
- Do not scrape Google search results.

## 9. Milestones (build in this order)
**M1 — Crawler + audit table**
Build: URL input page, jobs table, FastAPI crawler (limit 200 pages), `crawl_pages` stored, results table in UI with live progress.
Test: crawl a known small site; counts of 404s/missing titles match a manual check or Screaming Frog free version.

**M2 — Technical agent + Verifier**
Build: PSI integration, Technical agent produces `tech_issues` with evidence, Verifier rejects claims without evidence.
Test: seed a fake issue with no evidence; Verifier must reject it.

**M3 — GSC + GA4 connection + Monitor + Reporter**
Build: Google OAuth, pull 90 days of GSC queries/pages + GA4 sessions, Reporter exports PDF/CSV.
Test: numbers in the report match the GSC/GA4 dashboards.

**M4 — Research + Strategist + Content**
Build: keyword/competitor research via chosen API, 30-day plan, briefs, internal link suggestions from crawl graph.
Test: every internal link suggestion points to a real crawled URL.

**M5 — Code Generator**
Build: meta/canonical/OG, JSON-LD, sitemap, robots, llms.txt for Next.js and WordPress; ZIP download + step guide.
Test: JSON-LD passes validator; generated HTML passes lint.

**M6 — Orchestrator polish, credits/limits, Asana export**
Build: parallel agent runs, retries, per-job cost cap, usage limits per user.

## 10. Rules for the coding agent
1. Implement one milestone at a time; stop and run its tests.
2. Keep secrets in environment variables; never commit keys.
3. Cap crawl size, tokens per job and cost per job.
4. Cache API responses per job.
5. Every agent output must validate against a Pydantic schema.
6. Write unit tests for the crawler parsing and the Verifier.
7. If something is ambiguous, list the question in `OPEN_QUESTIONS.md` instead of guessing.

## 11. Open questions (decide before M4)
- Which keyword/backlink API and budget?
- Agent framework final choice (ADK vs OpenAI Agents SDK vs Claude Agent SDK)?
- Product name and whether it will be sold or used for a portfolio/case study first?
