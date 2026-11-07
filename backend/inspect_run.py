import sqlite3
import json

conn = sqlite3.connect('local_seo.db')
c = conn.cursor()
job_id = '98a924a6-7c42-420e-81cb-dee719989ded'

print('=== JOB INFO ===')
print(c.execute('SELECT id, target_url, status, pages_crawled, cost_usd, is_demo FROM jobs WHERE id = ?', (job_id,)).fetchone())

print('\n=== AGENT RUNS ===')
for r in c.execute('SELECT agent, mode, model, tokens_prompt, tokens_completion, cost_usd, failure_reason FROM agent_runs WHERE job_id = ?', (job_id,)).fetchall():
    print(r)

print('\n=== TECHNICAL ISSUES ===')
for r in c.execute('SELECT output_json FROM agent_runs WHERE job_id = ? AND agent = ?', (job_id, 'technical')).fetchall():
    data = json.loads(r[0])
    for iss in data.get('issues', []):
        print(f"ISSUE: {iss.get('issue_type')} | SEV: {iss.get('severity')} | HINT: {iss.get('fix_hint')}")

print('\n=== STRATEGY TASKS ===')
for r in c.execute('SELECT plan_json FROM strategy_plans WHERE job_id = ?', (job_id,)).fetchall():
    plan = json.loads(r[0])
    for t in plan.get('tasks', []):
        print(f"[{t.get('priority')}] {t.get('title')} | impact={t.get('impact')}")

print('\n=== CONTENT OUTPUTS ===')
for r in c.execute('SELECT output_json FROM content_outputs WHERE job_id = ?', (job_id,)).fetchall():
    data = json.loads(r[0])
    briefs = data.get('briefs', [])
    rewrites = data.get('rewrites', [])
    links = data.get('internal_links', [])
    print(f"Total Briefs: {len(briefs)}, Total Rewrites: {len(rewrites)}, Total Internal Links: {len(links)}")

    print("\n--- Internal Link Details ---")
    target_counts = {}
    for l in links:
        tgt = l.get('target_url')
        target_counts[tgt] = target_counts.get(tgt, 0) + 1
        print(f"Source: {l.get('source_url')} -> Target: {tgt} | Anchor: '{l.get('anchor_text')}' | Reason: {l.get('reason')}")

    print("\n--- Target Page Counts ---")
    for tgt, cnt in target_counts.items():
        print(f"{tgt}: {cnt} suggestion(s)")

    print("\n--- Rewrites Before/After (First 5) ---")
    for rw in rewrites[:5]:
        print(f"Target: {rw.get('target_url')}")
        print(f"  Current Title: {rw.get('current_title')}")
        print(f"  Suggested Title: {rw.get('suggested_title')}")
        print(f"  Current Meta: {rw.get('current_meta_desc')}")
        print(f"  Suggested Meta: {rw.get('suggested_meta_desc')}")
        print(f"  Current H1: {rw.get('current_h1')}")
        print(f"  Suggested H1: {rw.get('suggested_h1')}")
        print(f"  Preserved entities: {rw.get('preserved_entities')}")
        print(f"  Entity check passed: {rw.get('entity_check_passed')}")

print('\n=== VERIFIER RUN LOGS ===')
for r in c.execute('SELECT agent, output_json FROM agent_runs WHERE job_id = ? AND agent LIKE "verifier%"', (job_id,)).fetchall():
    print(f"\n--- {r[0]} ---")
    print(r[1])
