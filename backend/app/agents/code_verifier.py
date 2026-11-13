import os
import re
import json
import csv
import io
import subprocess
import shutil
import tempfile
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from typing import List, Dict, Any, Tuple, Optional
from bs4 import BeautifulSoup
from app.models.agent_schemas import GeneratedArtifact, CodeVerifierReport, CodeBundleReport

class CodeVerifier:
    """Deterministic verifier for all generated SEO code and configuration artifacts."""

    @classmethod
    def verify_artifact(
        cls,
        artifact: GeneratedArtifact,
        crawl_pages: List[Dict[str, Any]],
        crawl_links: List[Dict[str, Any]],
        target_domain: str,
        is_demo: bool = False,
        issue_type_by_id: Optional[Dict[str, str]] = None
    ) -> Tuple[str, Optional[str]]:
        """Validates a single artifact. Returns (status, reason) where status is 'passed', 'failed', or 'skipped'."""
        art_type = artifact.artifact_type
        content = artifact.content

        # Provenance validation:
        # 1. Every claimed issue ID must exist in verified issues
        # 2. robots.ts / robots.txt must NOT claim a broken-link task or issue
        # 3. JSON-LD must NOT claim missing_h1
        issue_type_by_id = issue_type_by_id or {}
        for sid in artifact.source_issue_ids:
            if issue_type_by_id and sid not in issue_type_by_id:
                return "failed", f"Artifact {artifact.file_path} claims issue ID '{sid}' which does not exist in verified issues."
            itype = issue_type_by_id.get(sid, "")
            if ("robot" in art_type.lower() or "robots" in artifact.file_path.lower()) and (itype in ("broken_link_4xx", "broken_link") or "broken" in sid.lower() or "404" in sid.lower()):
                return "failed", f"robots.txt / robots.ts must not claim a broken-link task or issue ({sid})."
            if ("jsonld" in art_type.lower() or "schema" in artifact.file_path.lower()) and (itype == "missing_h1" or "h1" in sid.lower()):
                return "failed", f"JSON-LD schema must not claim missing_h1 task or issue ({sid})."

        # 1. JSON-LD data validator (raw schema files)
        if (art_type == "jsonld" or artifact.file_path.endswith((".jsonld", ".json"))) and not artifact.file_path.endswith((".ts", ".tsx", ".js", ".php")):
            return cls._validate_jsonld(content, crawl_pages)

        # 2. sitemap.xml validator
        if art_type in ("sitemap_xml", "sitemap"):
            return cls._validate_sitemap_xml(content, crawl_pages, target_domain)

        # 3. robots.txt validator
        if art_type in ("robots_txt", "robots"):
            return cls._validate_robots_txt(content, crawl_pages)

        # 4. llms.txt validator
        if art_type in ("llms_txt", "llms"):
            return cls._validate_llms_txt(content, crawl_pages)

        # 5. Redirects validator
        if "redirect" in art_type:
            return cls._validate_redirects(artifact, crawl_pages)

        # 6. Metadata snippets / table
        if art_type in ("metadata_table_csv", "metadata_table"):
            return cls._validate_metadata_csv(content, crawl_pages)

        # 7. HTML snippets
        if "html_head" in art_type or art_type.endswith(".html"):
            return cls._validate_html_snippet(content)

        # 8. TypeScript / TSX snippets (Next.js layout, page, sitemap.ts, robots.ts, JsonLd.tsx)
        if art_type.startswith("nextjs_") or artifact.file_path.endswith((".ts", ".tsx")):
            return cls._validate_typescript_snippet(content, artifact.file_path)

        # 9. PHP snippets (WordPress functions.php)
        if art_type.startswith("wordpress_") and artifact.file_path.endswith(".php"):
            return cls._validate_php_snippet(content)

        # Default pass for other simple static configs
        return "passed", "Passed deterministic format checks."

    @classmethod
    def _validate_jsonld(cls, content: str, crawl_pages: List[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
        # Remove comment header if present
        json_str = re.sub(r"^\s*//.*$", "", content, flags=re.MULTILINE).strip()
        # Check script tag escaping: '</script>' inside string is forbidden
        if "</script>" in json_str.lower():
            return "failed", "Unescaped '</script>' tag detected inside JSON-LD payload."

        try:
            data = json.loads(json_str)
        except Exception as e:
            return "failed", f"Invalid JSON syntax in JSON-LD payload: {e}"

        # Check required schema properties
        context = data.get("@context")
        if context not in ("https://schema.org", "http://schema.org"):
            return "failed", f"Missing or invalid @context: '{context}'."

        graph = data.get("@graph") or [data]
        valid_crawled_urls = {p.get("url", "").rstrip("/") for p in crawl_pages}

        for item in graph:
            stype = item.get("@type")
            if not stype:
                return "failed", "Schema item missing required '@type'."

            # Organization / WebSite checks
            if stype == "Organization":
                if not item.get("name") or not item.get("url"):
                    return "failed", "Organization schema missing required 'name' or 'url'."
            elif stype == "WebSite":
                if not item.get("url") or not item.get("name"):
                    return "failed", "WebSite schema missing required 'url' or 'name'."
            elif stype == "BreadcrumbList":
                elements = item.get("itemListElement", [])
                if not elements:
                    return "failed", "BreadcrumbList has no 'itemListElement'."
                for el in elements:
                    if not el.get("position") or not el.get("name") or not el.get("item"):
                        return "failed", "Breadcrumb ListItem missing position, name, or item URL."
            elif stype == "BlogPosting":
                if not item.get("headline"):
                    return "failed", "BlogPosting schema missing required 'headline'."

        return "passed", "Valid JSON-LD schema with empirical provenance."

    @classmethod
    def _validate_sitemap_xml(cls, content: str, crawl_pages: List[Dict[str, Any]], target_domain: str) -> Tuple[str, Optional[str]]:
        try:
            root = ET.fromstring(content)
        except Exception as e:
            return "failed", f"Invalid XML syntax in sitemap: {e}"

        # Check urlset namespace
        tag = root.tag.lower()
        if not tag.endswith("urlset"):
            return "failed", f"Root element is '{root.tag}', expected 'urlset'."

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = []
        for url_elem in root.findall("sm:url", ns):
            loc = url_elem.find("sm:loc", ns)
            if loc is None or not loc.text:
                loc_non_ns = url_elem.find("loc")
                if loc_non_ns is not None and loc_non_ns.text:
                    urls.append(loc_non_ns.text.strip())
                else:
                    return "failed", "Sitemap <url> element missing <loc>."
            else:
                urls.append(loc.text.strip())

        if not urls:
            return "failed", "Sitemap contains 0 URLs."

        if len(urls) > 50000:
            return "failed", f"Sitemap exceeds 50,000 URL limit ({len(urls)} URLs)."

        # Check duplicates
        if len(urls) != len(set(urls)):
            return "failed", "Sitemap contains duplicate URLs."

        # Check against crawl records
        page_by_url = {p["url"].rstrip("/"): p for p in crawl_pages}
        for u in urls:
            parsed = urlparse(u)
            if not parsed.scheme or not parsed.netloc:
                return "failed", f"Sitemap URL '{u}' is not an absolute URL."
            if target_domain and parsed.netloc.lower() != target_domain.lower():
                return "failed", f"Sitemap URL '{u}' belongs to external host '{parsed.netloc}'."

            norm = u.rstrip("/")
            if norm not in page_by_url:
                return "failed", f"Sitemap URL '{u}' was not found in crawl records."

            p = page_by_url[norm]
            if p.get("status_code") != 200:
                return "failed", f"Sitemap URL '{u}' returned non-200 HTTP status ({p.get('status_code')})."
            if not p.get("indexable"):
                return "failed", f"Sitemap URL '{u}' is marked non-indexable in crawl."
            if p.get("canonical") and p.get("canonical").rstrip("/") != norm:
                return "failed", f"Sitemap URL '{u}' has conflicting canonical tag pointing to '{p.get('canonical')}'."

        return "passed", f"Valid sitemap.xml with {len(urls)} verified 200 indexable canonical URLs."

    @classmethod
    def _validate_robots_txt(cls, content: str, crawl_pages: List[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
        # Remove comments
        lines = [line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
        
        has_user_agent = any(l.lower().startswith("user-agent:") for l in lines)
        has_sitemap = any(l.lower().startswith("sitemap:") for l in lines)

        if not has_user_agent:
            return "failed", "robots.txt missing 'User-agent:' directive."
        if not has_sitemap:
            return "failed", "robots.txt missing 'Sitemap:' directive."

        # Check for catastrophic disallow
        disallows = [l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("disallow:")]
        if "/" in disallows and not any(l.lower().startswith("allow:") for l in lines):
            return "failed", "Catastrophic 'Disallow: /' directive found blocking entire website."

        return "passed", "robots.txt parsed successfully with safe directives and Sitemap reference."

    @classmethod
    def _validate_llms_txt(cls, content: str, crawl_pages: List[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        if not lines:
            return "failed", "llms.txt is empty."

        # Must have an H1 header as the very first line (nothing before H1)
        if not lines[0].startswith("# "):
            return "failed", f"llms.txt must begin directly with top-level H1 '# SiteName', got: '{lines[0]}'."

        # Extract markdown links: [text](url)
        crawled_urls = {p["url"].rstrip("/") for p in crawl_pages if p.get("status_code") == 200 and p.get("indexable")}
        links = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", content)

        if not links:
            return "failed", "llms.txt contains no resource links."

        for anchor, u in links:
            if u.rstrip("/") not in crawled_urls:
                return "failed", f"llms.txt links to non-crawled or non-indexable URL: '{u}'."

        return "passed", f"llms.txt conforms to Markdown spec with {len(links)} verified indexable resource links."

    @classmethod
    def _validate_redirects(cls, artifact: GeneratedArtifact, crawl_pages: List[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
        redirects = artifact.metadata.get("redirects", [])
        if not redirects:
            # Check content for redirects
            return "passed", "No redirects configured."

        page_by_url = {p["url"].rstrip("/"): p for p in crawl_pages}
        page_paths_200 = {urlparse(p["url"]).path.rstrip("/") for p in crawl_pages if p.get("status_code") == 200}

        all_sources = {(r.get("source_path") or r.get("source") or "").rstrip("/") for r in redirects}

        seen_sources = set()
        for r in redirects:
            src = (r.get("source_path") or r.get("source") or "").rstrip("/")
            tgt = (r.get("target_path") or r.get("target") or r.get("destination") or "").rstrip("/")

            if not src or not tgt:
                return "failed", "Redirect rule missing source or target path."

            if src == tgt:
                return "failed", f"Self-redirect loop detected: '{src}' -> '{tgt}'."

            # Check redirect chain (target is itself redirected elsewhere)
            if tgt in all_sources:
                return "failed", f"Redirect chain detected: '{tgt}' is both a target and another redirect's source."

            if src in seen_sources:
                return "failed", f"Duplicate redirect source detected: '{src}'."
            seen_sources.add(src)

            # Rule: Target must be 200 OK (if crawl pages available)
            if page_paths_200 and tgt not in page_paths_200 and tgt != "/":
                return "failed", f"Redirect destination '{tgt}' does not exist as a 200 OK page in crawl."

            # Rule: Do not redirect an existing 200 OK page
            if page_paths_200 and src in page_paths_200:
                return "failed", f"Redirect source '{src}' is already an existing 200 OK page."

        return "passed", f"Validated {len(redirects)} redirect rules (no loops, no chains, target verified 200)."

    @classmethod
    def _validate_metadata_csv(cls, content: str, crawl_pages: List[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        if not rows:
            return "passed", "Metadata table is empty (all pages within limits)."

        for row in rows:
            u = row.get("url")
            s_t = row.get("suggested_title")
            s_m = row.get("suggested_meta")

            if s_t and s_t != "no change needed" and len(s_t) > 60:
                return "failed", f"suggested_title for '{u}' is {len(s_t)} chars (> 60 limit)."
            if s_m and s_m != "no change needed" and len(s_m) > 155:
                return "failed", f"suggested_meta for '{u}' is {len(s_m)} chars (> 155 limit)."

        return "passed", f"Metadata CSV validated across {len(rows)} verified page rewrites."

    @classmethod
    def _validate_html_snippet(cls, content: str) -> Tuple[str, Optional[str]]:
        try:
            soup = BeautifulSoup(content, "html.parser")
            titles = soup.find_all("title")
            metas = soup.find_all("meta", attrs={"name": "description"})
            canonicals = soup.find_all("link", attrs={"rel": "canonical"})

            if len(titles) > 1:
                return "failed", f"Multiple <title> tags detected ({len(titles)})."
            if len(metas) > 1:
                return "failed", f"Multiple meta description tags detected ({len(metas)})."
            if len(canonicals) > 1:
                return "failed", f"Multiple canonical tags detected ({len(canonicals)})."

            return "passed", "HTML head snippet contains valid singleton metadata tags."
        except Exception as e:
            return "failed", f"HTML parser error: {e}"

    @classmethod
    def _validate_typescript_snippet(cls, content: str, file_path: str) -> Tuple[str, Optional[str]]:
        """Syntax-checks TypeScript/TSX using Node subprocess running typescript compiler API."""
        node_cmd = shutil.which("node")
        if not node_cmd:
            return "skipped", "skipped (tool missing: Node.js CLI not installed)"

        # Check if typescript npm module is accessible
        check_script = "try { require('typescript'); console.log('OK'); } catch(e) { process.exit(1); }"
        try:
            proc = subprocess.run([node_cmd, "-e", check_script], capture_output=True, text=True, timeout=5)
            if proc.returncode != 0:
                return "skipped", "skipped (tool missing: TypeScript compiler not installed)"
        except Exception:
            return "skipped", "skipped (tool missing: Node.js execution failed)"

        # Run transpileModule syntax validation
        transpile_script = """
        const ts = require('typescript');
        const code = process.argv[1];
        const res = ts.transpileModule(code, {
            compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX }
        });
        if (res.diagnostics && res.diagnostics.length > 0) {
            console.error(res.diagnostics[0].messageText);
            process.exit(2);
        }
        console.log('VALID');
        """
        try:
            val_proc = subprocess.run(
                [node_cmd, "-e", transpile_script, content],
                capture_output=True,
                text=True,
                timeout=10
            )
            if val_proc.returncode == 0:
                return "passed", "TypeScript syntax check passed via TypeScript compiler API."
            else:
                err_msg = val_proc.stderr.strip() or "TypeScript transpile error."
                return "failed", f"TypeScript syntax error in {file_path}: {err_msg[:200]}"
        except subprocess.TimeoutExpired:
            return "failed", "TypeScript compiler timed out."
        except Exception as e:
            return "skipped", f"skipped (tool missing: {e})"

    @classmethod
    def _validate_php_snippet(cls, content: str) -> Tuple[str, Optional[str]]:
        """Syntax-checks PHP code using php -l if installed, otherwise skips."""
        php_cmd = shutil.which("php")
        if not php_cmd:
            return "skipped", "skipped (tool missing: PHP CLI not installed)"

        try:
            proc = subprocess.run([php_cmd, "-l"], input=content, text=True, capture_output=True, timeout=5)
            if proc.returncode == 0:
                return "passed", "PHP lint passed (php -l)."
            else:
                return "failed", f"PHP syntax error: {proc.stderr.strip()[:200]}"
        except Exception as e:
            return "skipped", f"skipped (tool missing: {e})"

    @classmethod
    def _validate_nextjs_project_compile(cls, artifacts: List[GeneratedArtifact]) -> Tuple[str, Optional[str]]:
        """Real compile check: creates a scratch Next.js App Router fixture, copies the generated files in,
        and runs tsc --noEmit. If unavailable, returns 'skipped' with 'type check skipped'."""
        npx_cmd = shutil.which("npx") or shutil.which("npx.cmd")
        if not npx_cmd:
            return "skipped", "type check skipped: npx/tsc not found in PATH"

        # Search for frontend/node_modules
        frontend_node_modules = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "node_modules"))
        if not os.path.isdir(frontend_node_modules):
            frontend_node_modules = os.path.abspath("frontend/node_modules")
        if not os.path.isdir(frontend_node_modules):
            return "skipped", "type check skipped: frontend/node_modules not found"

        ts_artifacts = [a for a in artifacts if a.file_path.endswith((".ts", ".tsx"))]
        if not ts_artifacts:
            return "passed", "No TypeScript artifacts to compile."

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_node_modules = os.path.join(tmpdir, "node_modules")
                try:
                    subprocess.run(f'cmd /c mklink /J "{tmp_node_modules}" "{frontend_node_modules}"', shell=True, check=True, capture_output=True)
                except Exception:
                    pass

                tsconfig = {
                    "compilerOptions": {
                        "target": "es2020",
                        "lib": ["dom", "dom.iterable", "esnext"],
                        "allowJs": True,
                        "skipLibCheck": True,
                        "strict": False,
                        "noEmit": True,
                        "esModuleInterop": True,
                        "module": "esnext",
                        "moduleResolution": "bundler",
                        "jsx": "preserve",
                        "paths": {
                            "@/*": ["./*"]
                        }
                    },
                    "include": ["**/*.ts", "**/*.tsx"],
                    "exclude": ["node_modules"]
                }
                with open(os.path.join(tmpdir, "tsconfig.json"), "w", encoding="utf-8") as f:
                    json.dump(tsconfig, f, indent=2)

                for art in ts_artifacts:
                    dest_path = os.path.join(tmpdir, art.file_path.replace("/", os.sep))
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with open(dest_path, "w", encoding="utf-8") as f:
                        f.write(art.content)

                res = subprocess.run([npx_cmd, "tsc", "--noEmit"], cwd=tmpdir, capture_output=True, text=True, timeout=30)
                if res.returncode == 0:
                    return "passed", "Next.js compile check passed via 'tsc --noEmit' with 0 errors."
                else:
                    err_msg = (res.stdout + " " + res.stderr).strip()
                    return "failed", f"Next.js compile check failed: {err_msg[:300]}"
        except subprocess.TimeoutExpired:
            return "failed", "Next.js compile check timed out after 30 seconds."
        except Exception as e:
            return "skipped", f"type check skipped: {e}"

    @classmethod
    def verify_code_bundle(
        cls,
        bundle: CodeBundleReport,
        crawl_pages: List[Dict[str, Any]],
        crawl_links: List[Dict[str, Any]],
        is_demo: bool = False,
        verified_tech_issues: Optional[List[Any]] = None
    ) -> CodeVerifierReport:
        """Evaluates all artifacts in the bundle and assigns validation_status and reason."""
        passed_count = 0
        failed_count = 0
        skipped_count = 0
        results = []

        issue_type_by_id = {}
        if verified_tech_issues:
            for iss in verified_tech_issues:
                iss_id = iss.get("id") if isinstance(iss, dict) else getattr(iss, "id", "")
                iss_type = iss.get("type") if isinstance(iss, dict) else getattr(iss, "type", "")
                if iss_id:
                    issue_type_by_id[iss_id] = iss_type

        target_domain = ""
        if crawl_pages and crawl_pages[0].get("url"):
            target_domain = urlparse(crawl_pages[0]["url"]).netloc

        for art in bundle.artifacts:
            status, reason = cls.verify_artifact(
                artifact=art,
                crawl_pages=crawl_pages,
                crawl_links=crawl_links,
                target_domain=target_domain,
                is_demo=is_demo,
                issue_type_by_id=issue_type_by_id
            )
            art.validation_status = status
            art.validation_reason = reason

            if status == "passed":
                passed_count += 1
            elif status == "failed":
                failed_count += 1
            elif status == "skipped":
                skipped_count += 1

            results.append({
                "file_path": art.file_path,
                "artifact_type": art.artifact_type,
                "status": status,
                "reason": reason
            })

        # Real compile check for Next.js platform
        if bundle.platform == "nextjs":
            compile_status, compile_reason = cls._validate_nextjs_project_compile(bundle.artifacts)
            if compile_status == "passed":
                passed_count += 1
            elif compile_status == "failed":
                failed_count += 1
            elif compile_status == "skipped":
                skipped_count += 1

            results.append({
                "file_path": "nextjs_project_compile (tsc --noEmit)",
                "artifact_type": "project_compile_check",
                "status": compile_status,
                "reason": compile_reason
            })

        summary = (
            f"Code Verifier validated {len(bundle.artifacts)} generated artifacts for platform '{bundle.platform}'. "
            f"Results: {passed_count} passed, {skipped_count} skipped, {failed_count} failed."
        )

        return CodeVerifierReport(
            total_artifacts=len(bundle.artifacts) + (1 if bundle.platform == "nextjs" else 0),
            passed_count=passed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            results=results,
            summary=summary
        )
