import httpx
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from app.services.google_auth import get_valid_access_token

def calculate_gsc_periods() -> Tuple[str, str, str, str]:
    """
    Returns (curr_start, curr_end, prev_start, prev_end).
    Current: last 90 days ending 3 days ago.
    Previous: 90 days immediately prior.
    """
    today = datetime.now(timezone.utc).date()
    curr_end = today - timedelta(days=3)
    curr_start = curr_end - timedelta(days=90)
    prev_end = curr_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=90)
    return (
        curr_start.isoformat(),
        curr_end.isoformat(),
        prev_start.isoformat(),
        prev_end.isoformat(),
    )

async def list_gsc_sites(access_token: str) -> List[Dict[str, str]]:
    """Lists verified Search Console properties."""
    url = "https://www.googleapis.com/webmasters/v3/sites"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"}, timeout=15.0)
        if resp.status_code == 200:
            entries = resp.json().get("siteEntry", [])
            return [{"siteUrl": e.get("siteUrl", ""), "permissionLevel": e.get("permissionLevel", "")} for e in entries]
        return []

async def list_ga4_properties(access_token: str) -> List[Dict[str, str]]:
    """Lists GA4 accounts and property summaries."""
    url = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"}, timeout=15.0)
        if resp.status_code == 200:
            summaries = resp.json().get("accountSummaries", [])
            props = []
            for acc in summaries:
                for p in acc.get("propertySummaries", []):
                    props.append({
                        "propertyId": p.get("property", "").replace("properties/", ""),
                        "displayName": p.get("displayName", ""),
                        "account": acc.get("displayName", "")
                    })
            return props
        return []

def parse_gsc_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parses raw GSC query or page rows into structured dicts."""
    parsed = []
    for r in rows:
        keys = r.get("keys", [])
        parsed.append({
            "key": keys[0] if keys else "",
            "clicks": int(r.get("clicks", 0)),
            "impressions": int(r.get("impressions", 0)),
            "ctr": round(float(r.get("ctr", 0.0)) * 100, 2),  # percentage
            "position": round(float(r.get("position", 0.0)), 1)
        })
    return parsed

def parse_ga4_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parses raw GA4 rows into structured dicts."""
    parsed = []
    for r in rows:
        dims = r.get("dimensionValues", [])
        metrics = r.get("metricValues", [])
        dim_val = dims[0].get("value") if dims else ""
        parsed.append({
            "dimension": dim_val,
            "sessions": int(metrics[0].get("value", 0)) if len(metrics) > 0 else 0,
            "engaged_sessions": int(metrics[1].get("value", 0)) if len(metrics) > 1 else 0,
            "active_users": int(metrics[2].get("value", 0)) if len(metrics) > 2 else 0,
            "key_events": int(metrics[3].get("value", 0)) if len(metrics) > 3 else 0,
        })
    return parsed
