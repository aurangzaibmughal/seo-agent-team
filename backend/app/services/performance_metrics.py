import statistics
from typing import Dict, Any, List
from datetime import datetime, timezone

def calculate_pct_change(current: float, previous: float) -> float:
    """Safe percentage change with divide-by-zero protection."""
    if previous == 0:
        return 0.0 if current == 0 else 100.0
    return round(((current - previous) / previous) * 100.0, 1)

def compute_performance_metrics(
    curr_queries: List[Dict[str, Any]],
    prev_queries: List[Dict[str, Any]],
    curr_pages: List[Dict[str, Any]],
    prev_pages: List[Dict[str, Any]],
    curr_ga4: Dict[str, Any],
    prev_ga4: Dict[str, Any],
    min_impressions_threshold: int = 10
) -> Dict[str, Any]:
    """
    Deterministic Metrics Engine (Plain Python, No LLM).
    Computes period-over-period changes, striking distance queries,
    low-CTR opportunities, and declining pages.
    """
    # 1. Totals & Period-over-period
    curr_clicks = sum(q.get("clicks", 0) for q in curr_queries)
    prev_clicks = sum(q.get("clicks", 0) for q in prev_queries)
    clicks_change_abs = curr_clicks - prev_clicks
    clicks_change_pct = calculate_pct_change(curr_clicks, prev_clicks)

    curr_impressions = sum(q.get("impressions", 0) for q in curr_queries)
    prev_impressions = sum(q.get("impressions", 0) for q in prev_queries)
    impressions_change_abs = curr_impressions - prev_impressions
    impressions_change_pct = calculate_pct_change(curr_impressions, prev_impressions)

    curr_ctr = round((curr_clicks / curr_impressions * 100), 2) if curr_impressions > 0 else 0.0
    prev_ctr = round((prev_clicks / prev_impressions * 100), 2) if prev_impressions > 0 else 0.0
    ctr_change_abs = round(curr_ctr - prev_ctr, 2)

    curr_avg_pos = round(statistics.mean([q["position"] for q in curr_queries]), 1) if curr_queries else 0.0
    prev_avg_pos = round(statistics.mean([q["position"] for q in prev_queries]), 1) if prev_queries else 0.0
    pos_change_abs = round(curr_avg_pos - prev_avg_pos, 1)

    # GA4 Metrics
    curr_sessions = curr_ga4.get("sessions", 0)
    prev_sessions = prev_ga4.get("sessions", 0)
    sessions_change_abs = curr_sessions - prev_sessions
    sessions_change_pct = calculate_pct_change(curr_sessions, prev_sessions)

    curr_conversions = curr_ga4.get("key_events", 0)
    prev_conversions = prev_ga4.get("key_events", 0)
    conversions_change_abs = curr_conversions - prev_conversions
    conversions_change_pct = calculate_pct_change(curr_conversions, prev_conversions)

    # 2. Top Gaining and Top Losing Queries
    prev_query_map = {q["key"]: q for q in prev_queries}
    query_diffs = []
    for q in curr_queries:
        if q.get("impressions", 0) < min_impressions_threshold:
            continue
        p_q = prev_query_map.get(q["key"])
        p_clicks = p_q.get("clicks", 0) if p_q else 0
        diff = q.get("clicks", 0) - p_clicks
        query_diffs.append({
            "query": q["key"],
            "current_clicks": q.get("clicks", 0),
            "previous_clicks": p_clicks,
            "clicks_diff": diff,
            "current_impressions": q.get("impressions", 0),
            "current_ctr": q.get("ctr", 0.0),
            "current_position": q.get("position", 0.0)
        })

    top_gaining_queries = sorted([qd for qd in query_diffs if qd["clicks_diff"] > 0], key=lambda x: x["clicks_diff"], reverse=True)[:5]
    top_losing_queries = sorted([qd for qd in query_diffs if qd["clicks_diff"] < 0], key=lambda x: x["clicks_diff"])[:5]

    # 3. Striking-Distance Queries: position 8.0 - 20.0 with meaningful impressions
    striking_distance = [
        {
            "query": q["key"],
            "position": q.get("position", 0.0),
            "impressions": q.get("impressions", 0),
            "clicks": q.get("clicks", 0),
            "ctr": q.get("ctr", 0.0)
        }
        for q in curr_queries
        if 8.0 <= q.get("position", 0.0) <= 20.0 and q.get("impressions", 0) >= min_impressions_threshold
    ]
    striking_distance.sort(key=lambda x: x["impressions"], reverse=True)

    # 4. Low-CTR Opportunities: high impressions, CTR below median for similar positions
    median_impressions = statistics.median([q["impressions"] for q in curr_queries]) if curr_queries else 0
    all_ctrs = [q["ctr"] for q in curr_queries if q.get("impressions", 0) >= min_impressions_threshold]
    median_ctr = statistics.median(all_ctrs) if all_ctrs else 0.0

    low_ctr_opportunities = [
        {
            "query": q["key"],
            "impressions": q.get("impressions", 0),
            "ctr": q.get("ctr", 0.0),
            "median_ctr": round(median_ctr, 2),
            "position": q.get("position", 0.0),
            "clicks": q.get("clicks", 0)
        }
        for q in curr_queries
        if q.get("impressions", 0) > median_impressions and q.get("ctr", 0.0) < median_ctr
    ]
    low_ctr_opportunities.sort(key=lambda x: x["impressions"], reverse=True)

    # 5. Declining Pages: clicks down > 20% vs previous period
    prev_page_map = {p["key"]: p for p in prev_pages}
    declining_pages = []
    for p in curr_pages:
        p_prev = prev_page_map.get(p["key"])
        if p_prev and p_prev.get("clicks", 0) >= 10:  # minimum volume to avoid tiny-sample noise
            curr_c = p.get("clicks", 0)
            prev_c = p_prev.get("clicks", 0)
            drop_pct = calculate_pct_change(curr_c, prev_c)
            if drop_pct <= -20.0:
                declining_pages.append({
                    "url": p["key"],
                    "current_clicks": curr_c,
                    "previous_clicks": prev_c,
                    "change_pct": drop_pct,
                    "impressions": p.get("impressions", 0)
                })
    declining_pages.sort(key=lambda x: x["change_pct"])

    return {
        "summary_totals": {
            "clicks": curr_clicks,
            "previous_clicks": prev_clicks,
            "clicks_change_abs": clicks_change_abs,
            "clicks_change_pct": clicks_change_pct,
            "impressions": curr_impressions,
            "previous_impressions": prev_impressions,
            "impressions_change_abs": impressions_change_abs,
            "impressions_change_pct": impressions_change_pct,
            "ctr": curr_ctr,
            "previous_ctr": prev_ctr,
            "ctr_change_abs": ctr_change_abs,
            "avg_position": curr_avg_pos,
            "previous_avg_position": prev_avg_pos,
            "avg_position_change_abs": pos_change_abs,
            "organic_sessions": curr_sessions,
            "previous_organic_sessions": prev_sessions,
            "sessions_change_abs": sessions_change_abs,
            "sessions_change_pct": sessions_change_pct,
            "conversions": curr_conversions,
            "previous_conversions": prev_conversions,
            "conversions_change_abs": conversions_change_abs,
            "conversions_change_pct": conversions_change_pct,
        },
        "top_gaining_queries": top_gaining_queries[:5],
        "top_losing_queries": top_losing_queries[:5],
        "striking_distance_queries": striking_distance[:10],
        "low_ctr_opportunities": low_ctr_opportunities[:10],
        "declining_pages": declining_pages[:10],
        "computed_at": datetime.now(timezone.utc).isoformat()
    }
