import ast
import glob
from pathlib import Path

BANNED_WORDS = [
    "verified", "official", "transparent", "dedicated", "custom",
    "digital growth", "digital agency", "enterprise", "itinerary", "award", "best"
]

def test_no_banned_copy_in_agents_and_jsonld():
    """Scans all string literals in backend/app/agents/*.py and jsonld_builder.py
    for banned marketing copy. Fails on any hit.
    """
    repo_root = Path(__file__).resolve().parent.parent
    agent_files = sorted(glob.glob(str(repo_root / "app" / "agents" / "*.py")))
    jsonld_file = str(repo_root / "app" / "code_generator" / "jsonld_builder.py")
    target_files = agent_files + [jsonld_file]

    violations = []
    for fn in target_files:
        p = Path(fn)
        with open(p, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(p))

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val_lower = node.value.lower()
                for banned in BANNED_WORDS:
                    if banned in val_lower:
                        violations.append(f"{p.name}:{node.lineno} [{banned}] -> {repr(node.value[:60])}")

    assert not violations, "Banned marketing copy string literals detected in agents or jsonld_builder:\n" + "\n".join(violations)
