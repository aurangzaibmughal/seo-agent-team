import io
import json
import zipfile
import csv
from typing import List, Dict, Any
from app.models.agent_schemas import GeneratedArtifact

class CodePackager:
    """Packages validated SEO code artifacts into a standardized downloadable ZIP bundle."""

    @classmethod
    def generate_zip(
        cls,
        job_id: str,
        domain: str,
        platform: str,
        artifacts: List[GeneratedArtifact],
        validation_results: List[Dict[str, Any]],
        is_demo: bool = False,
        include_unreviewed: bool = False
    ) -> bytes:
        """Generates the downloadable ZIP bundle as in-memory bytes, filtering for approved/edited artifacts by default."""
        from app.core.db import DBManager
        reviews = DBManager.get_review_items(job_id, item_type="code_artifact")
        if reviews:
            rev_map = {r["item_ref"]: r for r in reviews}
            filtered_artifacts = []
            for art in artifacts:
                rev = rev_map.get(art.file_path)
                if not rev:
                    filtered_artifacts.append(art)
                    continue
                if rev.get("status") in ("approved", "edited"):
                    filtered_artifacts.append(art)
                elif include_unreviewed:
                    art_copy = art.model_copy(deep=True) if hasattr(art, "model_copy") else art
                    art_copy.title = f"[UNREVIEWED] {art.title}"
                    art_copy.status = "[UNREVIEWED] pending"
                    filtered_artifacts.append(art_copy)
            artifacts = filtered_artifacts

        zip_buffer = io.BytesIO()
        watermark = "\n> [!CAUTION]\n> **DEMO DATA WATERMARK**: This archive contains synthetic fixtures generated in demo mode. Review and verify before applying to production.\n" if is_demo else ""

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. README_APPLY.md
            readme_content = cls._generate_readme(domain, platform, artifacts, is_demo, watermark)
            zf.writestr("README_APPLY.md", readme_content)

            # 2. CHANGES.csv
            changes_content = cls._generate_changes_csv(artifacts, validation_results, is_demo)
            zf.writestr("CHANGES.csv", changes_content)

            # 3. provenance.json
            provenance_content = cls._generate_provenance_json(artifacts)
            zf.writestr("provenance.json", provenance_content)

            # 4. validation_report.md
            val_report_content = cls._generate_validation_report(validation_results, is_demo)
            zf.writestr("validation_report.md", val_report_content)

            # 5. Generated code files (only passed and skipped artifacts included)
            for art in artifacts:
                if art.validation_status in ("passed", "skipped"):
                    zip_entry_path = f"files/{platform}/{art.file_path.lstrip('/')}"
                    zf.writestr(zip_entry_path, art.content)

        zip_buffer.seek(0)
        return zip_buffer.getvalue()

    @classmethod
    def _generate_readme(cls, domain: str, platform: str, artifacts: List[GeneratedArtifact], is_demo: bool, watermark: str) -> str:
        passed_arts = [a for a in artifacts if a.validation_status in ("passed", "skipped")]
        return f"""# SEO Code Implementation Guide for {domain}

**Detected / Target Platform:** `{platform}`  
**Generated Files:** {len(passed_arts)}  
{watermark}

---

## 1. Before You Start (Critical Best Practices)
1. **Never edit directly in production.** Create a dedicated git feature branch:
   ```bash
   git checkout -b chore/seo-meta-and-schema-fixes
   ```
2. **MERGE, Do Not Overwrite:** For Next.js, metadata files are provided as snippets (`*.metadata.snippet.tsx`). Merge the `export const metadata` blocks into your existing `layout.tsx` or `page.tsx` files. Never replace entire existing components.
3. **Take a full backup** of your existing codebase and database configuration.
4. Work in your local development or staging environment before opening a Pull Request.

---

## 2. File Placement & Instructions

| Generated File | Destination in Project | Purpose |
| :--- | :--- | :--- |
""" + "\n".join(
            f"| `{a.file_path}` | `files/{platform}/{a.file_path}` | {a.title} |"
            for a in passed_arts
        ) + f"""

### Specific Platform Steps ({platform})
""" + cls._get_platform_specific_instructions(platform) + """

---

## 3. How to Test & Validate Locally
1. **Local Server:** Launch your development server (`npm run dev` or local server) and verify pages load without console errors.
2. **Schema Validation:**
   - Copy the rendered HTML or schema output and test on [Schema.org Validator](https://validator.schema.org/).
   - Test rich snippet eligibility on [Google's Rich Results Test](https://search.google.com/test/rich-results).
3. **Robots & Sitemap:**
   - Verify `/robots.txt` displays valid directives and points to `/sitemap.xml`.
   - Verify `/sitemap.xml` returns 200 OK with clean, canonical-only URLs.

---

## 4. Search Console & Verification
1. **Submit Sitemap in Google Search Console:**
   - Navigate to **Google Search Console > Sitemaps > Add a new sitemap**.
   - Enter `/sitemap.xml` and click **Submit**.
   - Verify that Google reports a 'Success' status and shows discovered URLs.
2. Run a re-crawl in this application to confirm that technical issues (`T-xxx`) are resolved and zero 4xx/canonical/duplicate errors remain.

---

## 5. Rollback Procedure
If regressions or build failures occur on your feature branch:
```bash
git checkout main
git branch -D chore/seo-meta-and-schema-fixes
```
If changes were already merged to `main`:
```bash
git revert <commit-hash>
git push origin main
```
"""

    @classmethod
    def _get_platform_specific_instructions(cls, platform: str) -> str:
        if platform == "nextjs":
            return """- **Next.js App Router (Single Recommended Approach):**
  - **Sitemap & Robots (Post-Fix Coverage)**: Next.js App Router dynamically serves sitemaps and robots via TypeScript route handlers. Place `app/sitemap.ts` and `app/robots.ts` into your `app/` folder. Next.js will automatically serve `/sitemap.xml` and `/robots.txt`.
    - **Included now**: 200 OK, indexable, self-canonical pages.
    - **Included after fix**: Pages whose only problem is `canonical_to_other` (`/portfolio`, `/calculator`, `/track`), assuming the generated per-page self-referential canonical fix is applied.
    - Note: In production, we recommend generating this sitemap directly from your site's own data source (database, CMS API, or MDX files). Do NOT combine with static XML/TXT files in `public/`.
  - **Metadata Snippets**: MERGE the `export const metadata` snippet from `app/layout.metadata.snippet.tsx` into your root `app/layout.tsx`.
  - **Per-Page Metadata**: MERGE snippet contents (`app/.../page.metadata.snippet.tsx`) into their respective `page.tsx` files.
  - **Dynamic Route Skeleton**: For `/blog/[slug]`, MERGE the `generateMetadata` skeleton from `app/blog/[slug]/page.metadata.snippet.tsx` into `app/blog/[slug]/page.tsx`. Per-post SEO metadata is documented in `metadata_table.csv`.
  - **Structured Data**: Import and use `components/JsonLd.tsx` to safely inject JSON-LD without XSS risk.
  - **Static AI Discovery**: Place `public/llms.txt` in your `public/` folder so AI crawlers can access it at `/llms.txt`.
  - **Redirects**: Append the `async redirects()` block to your existing `next.config.js`."""
        elif platform == "wordpress":
            return """- **WordPress Theme Functions / Must-Use Plugin:**
  - Place the `functions.php` snippet into your child theme or as an `mu-plugins/seo-schema.php` file.
  - Upload `robots.txt` and `llms.txt` to your site root directory.
  - Add the `.htaccess` rules to your Apache `.htaccess` file or import the CSV into the **Redirection** WordPress plugin."""
        elif platform == "plain_html":
            return """- **Static HTML Sites:**
  - Paste the `<head>` snippets inside the `<head>` of each corresponding HTML file.
  - Place `sitemap.xml`, `robots.txt`, and `llms.txt` in the root public web directory.
  - Deploy `_redirects` for Netlify, `vercel.json` for Vercel, or `.htaccess` for Apache."""
        else:
            return """- **Shopify / Other:**
  - Use `metadata_table.csv` for updating title and meta description fields in your admin panel.
  - Upload `sitemap.xml` and `robots.txt` according to your platform specifications."""

    @classmethod
    def _generate_changes_csv(cls, artifacts: List[GeneratedArtifact], validation_results: List[Dict[str, Any]], is_demo: bool) -> str:
        output = io.StringIO()
        if is_demo:
            output.write("# DEMO DATA — SYNTHETIC BENCHMARK FIXTURE — REVIEW REQUIRED\n")
        writer = csv.writer(output)
        writer.writerow(["file_path", "title", "artifact_type", "platform", "issues_addressed", "tasks_addressed", "validation_status", "validation_reason", "status"])
        for art in artifacts:
            art_status = art.status
            if "[UNREVIEWED]" in art.title and not art_status.startswith("[UNREVIEWED]"):
                art_status = f"[UNREVIEWED] {art_status}"
            writer.writerow([
                art.file_path,
                art.title,
                art.artifact_type,
                art.platform,
                ";".join(art.source_issue_ids),
                ";".join(art.source_task_ids),
                art.validation_status,
                art.validation_reason or "",
                art_status
            ])
        return output.getvalue()

    @classmethod
    def _generate_provenance_json(cls, artifacts: List[GeneratedArtifact]) -> str:
        data = {
            "generator": "SEO Agent Team Code Generator",
            "version": "1.0.0",
            "artifacts": [
                {
                    "file_path": a.file_path,
                    "artifact_type": a.artifact_type,
                    "platform": a.platform,
                    "source_issue_ids": a.source_issue_ids,
                    "source_task_ids": a.source_task_ids,
                    "metadata": a.metadata,
                    "validation_status": a.validation_status
                }
                for a in artifacts
            ]
        }
        return json.dumps(data, indent=2)

    @classmethod
    def _generate_validation_report(cls, validation_results: List[Dict[str, Any]], is_demo: bool) -> str:
        passed = [r for r in validation_results if r.get("status") == "passed"]
        skipped = [r for r in validation_results if r.get("status") == "skipped"]
        failed = [r for r in validation_results if r.get("status") == "failed"]

        watermark = "\n> [!CAUTION]\n> **DEMO DATA**: Validations run on synthetic demo fixtures.\n" if is_demo else ""

        lines = [
            f"# Code Artifacts Validation Report\n{watermark}",
            f"**Total Artifacts Evaluated:** {len(validation_results)}",
            f"- **Passed:** {len(passed)}",
            f"- **Skipped (tool missing):** {len(skipped)}",
            f"- **Failed:** {len(failed)}\n",
            "## Summary Table\n",
            "| Artifact | Type | Status | Details / Reason |",
            "| :--- | :--- | :--- | :--- |"
        ]

        for r in validation_results:
            st = r.get("status", "unknown").upper()
            lines.append(f"| `{r.get('file_path')}` | `{r.get('artifact_type')}` | **{st}** | {r.get('reason') or 'Passed all deterministic checks.'} |")

        if failed:
            lines.append("\n## Failed Artifacts (Excluded from ZIP)")
            for f in failed:
                lines.append(f"- **`{f.get('file_path')}`**: {f.get('reason')}")

        if skipped:
            lines.append("\n## Skipped Artifacts (External tool not installed)")
            for s in skipped:
                lines.append(f"- **`{s.get('file_path')}`**: {s.get('reason')}")

        return "\n".join(lines)
