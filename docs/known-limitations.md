# Known Limitations & Audit Boundaries

This document details known limitations, boundary conditions, and dependencies of the SEO Agent Team platform.

---

## 1. External Service & API Dependencies
- **Google Search Console & GA4:** When Google credentials are not linked or OAuth is absent, performance metrics (organic impressions, CTR, queries) and query-based content briefs are marked as *"Not connected (requires Google Search Console)"*. Deterministic title/meta rewrites and 30-day technical action plans run autonomously without GSC.
- **PageSpeed Insights API Quota / Retries:** PSI API calls are subject to Google Cloud rate limits. If a fetch fails with `FAILED_DOCUMENT_REQUEST`, the engine retries once after 5 seconds. If unrecoverable, status is marked "partial" and unaffected pages continue.

---

## 2. Crawler & JavaScript Rendering Boundaries
- **Static vs. JS-Rendered DOM:** The fast asynchronous crawler parses server-rendered HTML. Single Page Applications (SPAs) that require client-side JavaScript execution (e.g. CSR React/Vue without SSR or SSG) may have unrendered client content unless pre-rendered.
- **Bot Mitigation & Cloudflare:** Sites behind aggressive anti-bot challenges (Cloudflare Turnstile, CAPTCHAs, Akamai bot manager) may block automated crawler requests, resulting in HTTP 403/503. The crawler logs failed fetches rather than fabricating results.

---

## 3. Platform Detection Heuristics
- **CMS Disguising:** Websites using custom headless architectures or reverse proxies that strip all WordPress/Next.js/Shopify headers and meta generator tags will be categorized as `plain_html`. Code generation produces generic HTML snippets and standard XML/txt files in these instances.
