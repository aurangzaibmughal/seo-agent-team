import os
import re
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Patterns that indicate leaked secrets
SECRET_PATTERNS = [
    (r"AIza[0-9A-Za-z-_]{35}", "Google API Key (AIza...)"),
    (r"GOCSPX-[0-9A-Za-z-_]{28}", "Google OAuth Client Secret (GOCSPX-...)"),
    (r"1/[0-9]{16}:[0-9a-fA-F]{32}", "Asana Personal Access Token"),
]

FORBIDDEN_TRACKED_PATTERNS = [
    r"^\.env$",
    r"^\.env\.local$",
    r"^\.env\.production$",
    r"^\.env\.development$",
    r".*\.secret\.key$",
    r".*\.db$",
    r".*\.sqlite3?$"
]


def get_tracked_files():
    """Returns list of files tracked by git."""
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True
    )
    return [f.strip() for f in proc.stdout.splitlines() if f.strip()]


def test_no_forbidden_files_tracked_in_git():
    """Verify that git does not track .env files, database files, or secret keys."""
    try:
        tracked_files = get_tracked_files()
    except Exception as e:
        pytest.skip(f"git command not available or failed: {e}")

    violations = []
    for f in tracked_files:
        norm_path = f.replace("\\", "/")
        filename = os.path.basename(norm_path)
        for pat in FORBIDDEN_TRACKED_PATTERNS:
            if re.match(pat, filename, re.IGNORECASE):
                violations.append(f)

    assert not violations, f"Forbidden sensitive files are tracked in git repository: {violations}"


def test_no_hardcoded_secrets_in_tracked_files():
    """Scan all tracked repository source code and assets for hardcoded API keys or credentials."""
    try:
        tracked_files = get_tracked_files()
    except Exception as e:
        pytest.skip(f"git command not available or failed: {e}")

    compiled_patterns = [(re.compile(pat), desc) for pat, desc in SECRET_PATTERNS]
    leaks = []

    for rel_path in tracked_files:
        # Skip binary files and test files that specifically define test pattern matchers
        ext = os.path.splitext(rel_path)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".ico", ".pdf", ".zip", ".woff", ".woff2", ".pyc", ".db"):
            continue
        if os.path.basename(rel_path) in ("test_secret_scanner.py", "M6_PROMPT.md", "PLAN.md", "GEMINI.md"):
            continue

        full_path = REPO_ROOT / rel_path
        if not full_path.exists():
            continue

        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, 1):
                    for pattern, desc in compiled_patterns:
                        if pattern.search(line):
                            leaks.append(f"{rel_path}:{line_no} matches {desc}")
        except Exception:
            pass

    assert not leaks, "Hardcoded credentials/secrets detected in tracked repository files:\n" + "\n".join(leaks)
