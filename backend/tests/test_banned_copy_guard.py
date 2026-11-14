import ast
import glob
import json
from pathlib import Path
from typing import List

CONFIG_PATH = Path(__file__).resolve().parent.parent / "app" / "config" / "banned_copy.json"

def get_banned_words() -> List[str]:
    assert CONFIG_PATH.exists(), f"Banned copy config not found at {CONFIG_PATH}"
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        words = json.load(f)
    assert isinstance(words, list) and len(words) >= 11
    return words

def scan_ast_for_banned_copy(tree: ast.AST, filename: str, banned_words: List[str]) -> List[str]:
    """Scans an AST tree for string and bytes constants containing any banned words."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            val_lower = ""
            if isinstance(node.value, str):
                val_lower = node.value.lower()
            elif isinstance(node.value, (bytes, bytearray)):
                val_lower = node.value.decode("utf-8", errors="ignore").lower()

            if val_lower:
                for banned in banned_words:
                    if banned in val_lower:
                        hits.append(f"{filename}:{node.lineno} [{banned}] -> {repr(node.value)[:60]}")
    return hits

def test_no_banned_copy_in_agents_and_jsonld():
    """Scans all string and bytes literals in backend/app/agents/*.py and jsonld_builder.py
    for banned marketing copy from app/config/banned_copy.json. Fails on any hit.
    """
    banned_words = get_banned_words()
    repo_root = Path(__file__).resolve().parent.parent
    agent_files = sorted(glob.glob(str(repo_root / "app" / "agents" / "*.py")))
    jsonld_file = str(repo_root / "app" / "code_generator" / "jsonld_builder.py")
    target_files = agent_files + [jsonld_file]

    violations = []
    for fn in target_files:
        p = Path(fn)
        with open(p, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(p))
        hits = scan_ast_for_banned_copy(tree, filename=p.name, banned_words=banned_words)
        violations.extend(hits)

    assert not violations, "Banned marketing copy literals detected in agents or jsonld_builder:\n" + "\n".join(violations)

def test_guard_catches_banned_word_as_bytes_literal():
    """Proves the guard catches a banned copy violation written as a bytes literal (e.g. b'verified')."""
    banned_words = get_banned_words()
    dummy_code = '''
def snippet():
    x = b"verified packages"
    return x
'''
    tree = ast.parse(dummy_code)
    violations = scan_ast_for_banned_copy(tree, filename="dummy_bytes.py", banned_words=banned_words)
    assert len(violations) >= 1
    assert any("verified" in v for v in violations)

def test_guard_catches_banned_word_as_string_literal():
    """Proves the guard catches a banned copy violation written as a string literal (e.g. 'official')."""
    banned_words = get_banned_words()
    dummy_code = '''
def snippet():
    x = "official itinerary"
    return x
'''
    tree = ast.parse(dummy_code)
    violations = scan_ast_for_banned_copy(tree, filename="dummy_str.py", banned_words=banned_words)
    assert len(violations) >= 1
    assert any("official" in v for v in violations)

def test_banned_copy_startup_loader_raises_on_missing_file(tmp_path):
    """Proves _load_banned_copy raises RuntimeError when the config file does not exist."""
    import pytest
    from app.agents.content_agent import _load_banned_copy
    missing_file = tmp_path / "non_existent_banned_copy.json"
    with pytest.raises(RuntimeError, match="not found"):
        _load_banned_copy(cfg_path=missing_file)

def test_banned_copy_startup_loader_raises_on_empty_file(tmp_path):
    """Proves _load_banned_copy raises RuntimeError when the config file is empty or contains empty list."""
    import pytest
    from app.agents.content_agent import _load_banned_copy
    empty_file = tmp_path / "empty_banned_copy.json"
    empty_file.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="empty or invalid"):
        _load_banned_copy(cfg_path=empty_file)
