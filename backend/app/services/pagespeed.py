import httpx
import asyncio
import random
import statistics
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from app.core.config import settings
from app.core.db import DBManager

PSI_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

def compute_median_psi_results(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Given multiple successful PSI runs for the same URL & strategy,
    computes the median values for performance_score, lcp_ms, cls, fcp_ms, ttfb_ms.
    """
    valid_runs = [r for r in runs if r.get("performance_score") is not None]
    if not valid_runs:
        return runs[0] if runs else {}
    if len(valid_runs) == 1:
        return valid_runs[0]

    base = dict(valid_runs[0])
    scores = [r["performance_score"] for r in valid_runs if r.get("performance_score") is not None]
    lcps = [r["lcp_ms"] for r in valid_runs if r.get("lcp_ms") is not None]
    clss = [r["cls"] for r in valid_runs if r.get("cls") is not None]
    fcps = [r["fcp_ms"] for r in valid_runs if r.get("fcp_ms") is not None]
    ttfbs = [r["ttfb_ms"] for r in valid_runs if r.get("ttfb_ms") is not None]

    base["performance_score"] = int(statistics.median(scores)) if scores else None
    base["lcp_ms"] = round(statistics.median(lcps), 1) if lcps else None
    base["cls"] = round(statistics.median(clss), 3) if clss else None
    base["fcp_ms"] = round(statistics.median(fcps), 1) if fcps else None
    base["ttfb_ms"] = round(statistics.median(ttfbs), 1) if ttfbs else None
    base["runs_count"] = len(valid_runs)
    return base

def check_metric_consistency(
    performance_score: Optional[int],
    lcp_ms: Optional[float],
    cls: Optional[float]
) -> Dict[str, Any]:
    """Sanity check whether performance score and core metrics are mutually consistent.
    In Lighthouse scoring curves, LCP has 25% weight. If LCP > 8000ms, LCP sub-score is ~0.
    If LCP >= 8000ms, score cannot exceed 70.
    """
    if performance_score is None:
        return {"is_consistent": True, "reason": ""}
    
    if lcp_ms is not None and lcp_ms >= 8000.0 and performance_score >= 70:
        return {
            "is_consistent": False,
            "reason": f"LCP of {lcp_ms/1000:.1f}s is inconsistent with a Lighthouse score of {performance_score} (likely stale cache or run glitch)."
        }
    
    return {"is_consistent": True, "reason": ""}

async def run_psi_for_url(
    client: httpx.AsyncClient,
    job_id: str,
    url: str,
    strategy: str = "mobile",
    max_retries: int = 3,
    ignore_cache: bool = False
) -> Dict[str, Any]:
    """Runs PageSpeed Insights for a URL & strategy, with 24hr cache, sequential delays,
    and automatic retry with backoff and jitter on 429 / 5xx errors.
    """
    # 1. Check 24-hour cache first (unless ignore_cache is True)
    if not ignore_cache:
        cached = DBManager.get_psi_cached(url, strategy)
        if cached:
            cached["job_id"] = job_id
            cached["is_cached"] = True
            cached["cached_measured_at"] = cached.get("fetched_at")
            DBManager.save_psi_result(cached)
            return cached

    result: Dict[str, Any] = {
        "job_id": job_id,
        "url": url,
        "strategy": strategy,
        "performance_score": None,
        "lcp_ms": None,
        "cls": None,
        "inp_or_tbt_ms": None,
        "fcp_ms": None,
        "ttfb_ms": None,
        "raw_json": None,
        "error": None,
        "is_cached": False,
        "cached_measured_at": None,
        "fetched_at": datetime.now(timezone.utc).isoformat()
    }

    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance",
    }
    has_key = bool(settings.PSI_API_KEY and settings.PSI_API_KEY.strip())
    if has_key:
        params["key"] = settings.PSI_API_KEY.strip()

    base_delays = [2.0, 4.0, 8.0]

    for attempt in range(max_retries + 1):
        try:
            resp = await client.get(PSI_API_URL, params=params, timeout=settings.PSI_TIMEOUT_SECONDS)

            if resp.status_code == 200:
                data = resp.json()
                lh = data.get("lighthouseResult", {})
                runtime_err = lh.get("runtimeError", {}).get("code", "")
                if "FAILED_DOCUMENT_REQUEST" in runtime_err:
                    if attempt < 1:
                        print(f"[PSI] FAILED_DOCUMENT_REQUEST on {url} ({strategy}). Retrying once after 5.0s...")
                        await asyncio.sleep(5.0)
                        continue
                    result["error"] = "FAILED_DOCUMENT_REQUEST"
                    break

                cats = lh.get("categories", {})
                perf = cats.get("performance", {})
                score = int(perf.get("score", 0) * 100) if perf.get("score") is not None else None

                audits = lh.get("audits", {})
                lcp = audits.get("largest-contentful-paint", {}).get("numericValue")
                cls_val = audits.get("cumulative-layout-shift", {}).get("numericValue")
                tbt = audits.get("total-blocking-time", {}).get("numericValue")
                fcp = audits.get("first-contentful-paint", {}).get("numericValue")
                ttfb = audits.get("server-response-time", {}).get("numericValue")

                result["performance_score"] = score
                result["lcp_ms"] = round(lcp, 1) if lcp is not None else None
                result["cls"] = round(cls_val, 3) if cls_val is not None else None
                result["inp_or_tbt_ms"] = round(tbt, 1) if tbt is not None else None
                result["fcp_ms"] = round(fcp, 1) if fcp is not None else None
                result["ttfb_ms"] = round(ttfb, 1) if ttfb is not None else None
                result["raw_json"] = {
                    "fetchTime": lh.get("fetchTime"),
                    "environment": lh.get("environment"),
                    "audits_summary": {k: audits[k].get("displayValue") for k in audits if "displayValue" in audits[k]}
                }
                result["error"] = None
                break

            # Check for FAILED_DOCUMENT_REQUEST specifically: retry once after 5s
            if "FAILED_DOCUMENT_REQUEST" in resp.text:
                if attempt < 1:
                    print(f"[PSI] FAILED_DOCUMENT_REQUEST on {url} ({strategy}). Retrying once after 5.0s...")
                    await asyncio.sleep(5.0)
                    continue
                result["error"] = "FAILED_DOCUMENT_REQUEST"
                break

            # On 429 or 5xx, retry with exponential backoff and jitter
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                jitter = random.uniform(0.1, 1.0)
                wait_time = base_delays[min(attempt, len(base_delays) - 1)] + jitter
                print(f"[PSI] HTTP {resp.status_code} on {url} ({strategy}). Retrying {attempt + 1}/{max_retries} in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
                continue

            # Retries exhausted or non-retryable status
            if resp.status_code == 429:
                if not has_key:
                    result["error"] = "key missing (anonymous quota exceeded)"
                else:
                    result["error"] = "quota exceeded / rate limited"
            elif resp.status_code in (401, 403):
                err_text = resp.text.lower()
                if "not enabled" in err_text or "not been used" in err_text or "disabled" in err_text:
                    result["error"] = "API not enabled in Google Cloud project"
                elif not has_key:
                    result["error"] = "key missing"
                else:
                    result["error"] = f"API auth error (HTTP {resp.status_code})"
            else:
                result["error"] = f"HTTP {resp.status_code}: {resp.text[:100]}"
            break

        except httpx.TimeoutException:
            if attempt < max_retries:
                jitter = random.uniform(0.1, 1.0)
                wait_time = base_delays[min(attempt, len(base_delays) - 1)] + jitter
                print(f"[PSI] Timeout on {url} ({strategy}). Retrying {attempt + 1}/{max_retries} in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
                continue
            result["error"] = "timeout (PageSpeed API did not respond)"
            break
        except Exception as e:
            if attempt < max_retries:
                jitter = random.uniform(0.1, 1.0)
                wait_time = base_delays[min(attempt, len(base_delays) - 1)] + jitter
                print(f"[PSI] Network error on {url}. Retrying {attempt + 1}/{max_retries} in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
                continue
            result["error"] = f"network error: {str(e)[:100]}"
            break

    DBManager.save_psi_result(result)
    return result

async def run_pagespeed_pipeline(job_id: str, target_url: str, ignore_cache: bool = False):
    """Orchestrates PSI for homepage + up to 4 top inlink pages for mobile and desktop sequentially."""
    DBManager.update_job(job_id, {
        "status": "pagespeed",
        "current_step": "pagespeed"
    })

    # Pick target pages: homepage + up to 4 top inlink pages (max 5 pages total)
    all_pages = DBManager.get_crawl_pages(job_id)
    pages_to_test = [target_url]

    # Sort remaining 200 OK pages by inlinks_count descending
    sorted_others = sorted(
        [p for p in all_pages if p["url"] != target_url and p.get("status_code") == 200],
        key=lambda x: x.get("inlinks_count", 0),
        reverse=True
    )
    for p in sorted_others[:4]:
        if p["url"] not in pages_to_test:
            pages_to_test.append(p["url"])
    pages_to_test = pages_to_test[:5]

    results_status = []
    async with httpx.AsyncClient() as client:
        for idx, url in enumerate(pages_to_test):
            if idx > 0:
                # 2 second sequential delay between pages
                await asyncio.sleep(2.0)

            # Mobile strategy
            m_res = await run_psi_for_url(client, job_id, url, strategy="mobile", ignore_cache=ignore_cache)
            results_status.append(m_res)

            # 2 second sequential delay between mobile and desktop calls
            await asyncio.sleep(2.0)

            # Desktop strategy
            d_res = await run_psi_for_url(client, job_id, url, strategy="desktop", ignore_cache=ignore_cache)
            results_status.append(d_res)

    success_cnt = sum(1 for r in results_status if r.get("performance_score") is not None)
    total_cnt = len(results_status)
    has_key = bool(settings.PSI_API_KEY and settings.PSI_API_KEY.strip())

    failed_items = [r for r in results_status if r.get("error")]
    fdr_failed = next((r for r in results_status if r.get("error") == "FAILED_DOCUMENT_REQUEST"), None)

    if total_cnt == 0:
        psi_status = "failed: no pages"
    elif success_cnt == total_cnt:
        low_scores = [r for r in results_status if (r.get("performance_score") or 100) < 90]
        if not low_scores:
            psi_status = "ran (no speed issues found)"
            print("PSI ran, no speed issues found")
        else:
            psi_status = "ran"
    elif fdr_failed is not None:
        # If one call fails with FAILED_DOCUMENT_REQUEST, set status to partial and show failed URL and reason
        psi_status = f"partial ({fdr_failed['url']}: {fdr_failed['error']})"
    elif success_cnt > 0:
        if failed_items:
            f = failed_items[0]
            psi_status = f"partial ({f['url']}: {f['error']})"
        else:
            psi_status = "partial"
    else:
        errors = [r.get("error") for r in results_status if r.get("error")]
        first_err = errors[0] if errors else "unavailable"
        if not has_key:
            psi_status = "failed: key missing"
        elif "API not enabled" in first_err:
            psi_status = "failed: API not enabled"
        elif "quota" in first_err.lower() or "rate limit" in first_err.lower():
            psi_status = "failed: quota exceeded"
        elif "timeout" in first_err.lower():
            psi_status = "failed: timeout"
        else:
            psi_status = f"failed: {first_err}"

    DBManager.update_job(job_id, {"psi_status": psi_status})
