# Changelog
All notable changes to the SEO Agent Team platform are documented in this file.

## [Unreleased] - 2026-11-13 (Accuracy & Hardening Brief)

### Added
- **A-01: Canonical URL Normalization Engine (`url_utils.py`):** Added `normalize_url()`, `urls_compare_equal()`, `canonical_url_key()`, `detect_trailing_slash_convention()`, and tracking parameters stripping (`utm_*`, `gclid`, `fbclid`).
- **A-02: Robust Sitemap Index Discovery (`sitemap_parser.py`):** Recursive sitemap index resolution, gzip `.xml.gz` decompression, WP core `/wp-sitemap.xml` detection, and zero-false-positive diffing when sitemap is 404/unreachable.
- **A-03: Theme Placeholder & Short Meta Detection (`issue_rules.py`):** High-severity detection of theme default placeholder meta descriptions (e.g., "IT Service WordPress Theme", "Just another WordPress site") and short descriptions (< 70 chars).
- **A-04 & A-05: Grouped Evidence Reproduction Trails (`issue_rules.py`, `reporter.py`):** Exact string grouping for duplicate titles and metas with `group_key`; per-URL evidence reproduction in PDF, CSV, and XLSX exports.
- **A-09: WordPress & Elementor Platform Adapter (`detector.py`, `templates.py`, `code_agent.py`):** Full detection of WordPress generator, Elementor kit markers, and asset paths; deterministic generation of `FIX-INSTRUCTIONS.md`, `.htaccess`, and `functions.php` snippets; removal of Next.js fallback.
- **A-10 & A-11: Core Web Vitals 3-Band Standards & Metric Consistency:** Exact Google 3-band thresholds (Good, Needs Improvement, Poor) for LCP and CLS; `check_metric_consistency()` validation flagging implausible lab scores.
- **A-12 & A-13: Structural Detectors & Content-QA Advisory:** Detection of multiple H1 tags, missing image alt attributes, unmuted autoplay videos, empty hash links on legal/policy anchors, missing Schema.org markup, and advisory checks for slug/content typos and currency anomalies.
- **A-14: Internal Link Verification Guard:** Enforced existing link checks using `canonical_url_key` and source page `outlinks_list` to prevent suggesting redundant links.
- **A-15 & A-16: Crawl Notice, Page Inventory, and Report Lint Gate:** Informative crawl breakdown notice, complete page inventory table in report appendix, and automated pre-export QA lint gate (`report_linter.py`).
- **A-17: Continuous Section Numbering & Table Layout:** Dynamic section numbers avoiding missing section numbering jumps (e.g. 4 to 6 when competitors absent) and robust word-wrapping.
- **A-18: Generic Framework Support & Anti-Hardcoding:** Validated across Next.js and Shopify fixtures; test guard ensuring zero client-specific hardcoding in production application code.
