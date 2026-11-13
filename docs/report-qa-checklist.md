# SEO Audit Report QA Checklist

Use this pre-flight verification checklist before sending any audit deliverable to a client or stakeholder:

---

## 1. Crawl & Discovery Health
- [ ] **Trailing Slash Convention:** Verified against site's actual convention; canonical tags match live URL casing and slashes.
- [ ] **Sitemap Resolution:** If sitemap returned 404 or was unreadable, ensure the report specifies "could not verify" or emits exactly 1 sitemap warning rather than flagging all 200 OK pages as missing from sitemap.
- [ ] **Crawl Completeness:** Check whether the crawl notice states exact page counts (e.g. `13 HTML pages crawled (limit: 100)`).

---

## 2. Technical Findings Accuracy
- [ ] **Evidence Reproduction Trail:** Every issue listed contains the specific affected URLs, found value, and expected value.
- [ ] **Duplicate Grouping:** Duplicate titles and meta descriptions show their shared string value and the exact URLs grouped together.
- [ ] **Canonicals:** Self-referencing canonical tags on indexable pages are passed; missing canonicals on custom post types or archives are isolated.
- [ ] **Theme Placeholders:** Any boilerplate text (e.g. "IT Service WordPress Theme", "Just another WordPress site") is flagged as placeholder metadata.

---

## 3. Core Web Vitals (CWV)
- [ ] **3-Band Thresholds:** LCP categorized as Good (≤2.5s), Needs Improvement (2.5–4.0s), or Poor (>4.0s). CLS categorized as Good (≤0.1), Needs Improvement (0.1–0.25), or Poor (>0.25).
- [ ] **Score Consistency:** Ensure high Lighthouse scores (e.g. >80) do not coincide with 10s+ LCP times.
- [ ] **Lab Data Label:** PSI scores are labeled as "lab data (Lighthouse)".

---

## 4. Strategic & Content Deliverables
- [ ] **Action Plan Completeness:** The 30-day action plan has non-empty, prioritized tasks distributed across Weeks 1 to 4 even if Search Console is not connected.
- [ ] **On-Page Rewrites:** Suggested titles are strictly 50–60 characters; suggested meta descriptions are strictly 120–155 characters. No hardcoded brand names from other projects.
- [ ] **Internal Links:** Recommended links do not already exist on the source page.

---

## 5. Implementation Code Package
- [ ] **Platform Match:** Ensure code fixes match detected CMS (WordPress generates `functions.php`, `.htaccess`, and `FIX-INSTRUCTIONS.md`).
- [ ] **Zero-Artifact Prevention:** "Download full bundle" is never shown if 0 artifacts were generated.
- [ ] **Section Numbering:** Contiguous numbering (1..N) without skipping numbers.
