---
name: seo-agent-team
description: Autonomous multi-agent SEO engineering skill for Claude Code, Cursor, and AI agents. Deterministically crawls web applications, detects technical SEO and Core Web Vitals regressions, verifies empirical evidence without hallucinations, and generates drop-in Next.js/React code fixes (sitemaps, robots.ts, schema markup, and metadata).
version: 1.0.0
author: Aurangzaib Mughal
license: MIT
tags:
  - seo
  - aeo
  - technical-seo
  - nextjs
  - multi-agent
  - auditing
  - code-generator
---

# SEO Agent Team — Autonomous SEO Engineering & Remediation

`seo-agent-team` turns any AI agent into an expert Technical SEO Engineer & Remediation Architect. Rather than generating vague or hallucinatory advice, this skill enforces a **deterministic crawl-first, verify-second, code-third** workflow.

---

## When to Activate This Skill
Trigger this skill whenever the user asks to:
1. Audit a website or web application for Technical SEO, Core Web Vitals, or AEO (Answer Engine Optimization) readiness.
2. Find broken canonicals, missing sitemaps, missing OpenGraph cards, unoptimized titles, or trailing slash redirects.
3. Diagnose Core Web Vitals regressions (LCP, CLS, INP) on mobile and desktop viewports.
4. Generate production-ready Next.js 14/15+ metadata, `app/sitemap.ts`, `app/robots.ts`, or JSON-LD structured data.
5. Create an actionable developer sprint backlog (with task IDs and effort estimations) or export tasks to Asana/CSV.

---

## 4-Stage Autonomous Pipeline

### Stage 1: Deterministic Crawl & Safety Bounds
- Enforce strict SSRF protection (prevent internal IP range probes, RFC-1918, CGNAT, metadata endpoints).
- Parse `robots.txt` and `sitemap.xml` deterministically.
- Discover discrepancies between declared sitemaps and actual crawlable indexable URLs (e.g., orphan pages, stale 404 links in sitemaps).

### Stage 2: Empirical Verification (Zero Hallucination)
- Verify every claimed issue against actual HTTP response headers and raw DOM payloads.
- Filter out speculative suggestions: an issue is only reported if empirical proof exists in the crawl snapshot.
- Check Core Web Vitals using real mobile viewport benchmarks (LCP threshold $\le 2.5\text{s}$, CLS $\le 0.1$, INP $\le 200\text{ms}$).

### Stage 3: Strategic Prioritization
- Group findings into prioritized sprints:
  - **Critical (P0):** Blocked indexing, broken canonical loops, 404s on core navigational links, mobile LCP > 10s.
  - **High (P1):** Stale URLs in `sitemap.xml`, missing H1 tags, duplicate meta descriptions, missing `llms.txt`.
  - **Medium (P2):** Suboptimal title lengths (> 60 chars), unoptimized image aspect ratios, missing schema attributes.
- Assign developer effort estimates (e.g., 15m quick-win vs 2h architectural fix).

### Stage 4: Drop-In Code Fix Generation
Generate exact, copy-paste ready code tailored to modern frameworks (Next.js 14/15 App Router, React, Astro):

#### 1. Dynamic `app/sitemap.ts` (Next.js 14/15)
```typescript
import { MetadataRoute } from 'next';

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://example.com';
  
  // Static routes
  const staticRoutes = [
    '',
    '/about',
    '/services',
    '/contact',
  ].map((route) => ({
    url: `${baseUrl}${route}`,
    lastModified: new Date(),
    changeFrequency: 'weekly' as const,
    priority: route === '' ? 1.0 : 0.8,
  }));

  return [...staticRoutes];
}
```

#### 2. Clean `app/robots.ts`
```typescript
import { MetadataRoute } from 'next';

export default function robots(): MetadataRoute.Robots {
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://example.com';
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: ['/api/', '/admin/', '/private/'],
      },
      {
        userAgent: ['GPTBot', 'ChatGPT-User', 'ClaudeBot', 'PerplexityBot'],
        allow: '/',
      },
    ],
    sitemap: `${baseUrl}/sitemap.xml`,
  };
}
```

#### 3. Organization & LocalBusiness JSON-LD Schema
```typescript
export function OrganizationSchema() {
  const schema = {
    '@context': 'https://schema.org',
    '@type': 'ProfessionalService',
    name: 'Business Name',
    url: 'https://example.com',
    telephone: '+1-555-555-5555',
    address: {
      '@type': 'PostalAddress',
      addressLocality: 'City',
      addressRegion: 'Region',
      addressCountry: 'Country',
    },
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
    />
  );
}
```

---

## Output Quality Criteria
- **Provenance:** Every issue must cite the exact target URL, HTTP status, and DOM element selector.
- **Precision:** Title rewrites must never exceed 60 characters. Meta descriptions must never exceed 155 characters.
- **Production-Ready:** Code snippets must compile under TypeScript strict mode with no missing imports or type errors.
