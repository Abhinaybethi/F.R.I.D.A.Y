"""
Phase 21 Release Audit - Security Scanner
Scans production Friday code for dangerous patterns, secrets, and safety defaults.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROD_DIRS = ["friday"]

DANGER_PATTERNS = {
    "shell=True":         re.compile(r"shell\s*=\s*True"),
    "os.system":          re.compile(r"\bos\.system\s*\("),
    "eval(":              re.compile(r"\beval\s*\("),
    "exec(":              re.compile(r"\bexec\s*\("),
}

SECRET_KEYWORDS = [
    "api_key", "apikey", "secret_key", "private_key", "auth_token",
]

SAFE_VALUE_TOKENS = {
    "none", "false", "true", '""', "''", "str", "optional[str]",
    "str | none", "", "your_key_here", "your-key",
}

findings = []
secrets = []

for d in PROD_DIRS:
    for f in sorted((ROOT / d).rglob("*.py")):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for name, pat in DANGER_PATTERNS.items():
                if pat.search(stripped):
                    rel = f.relative_to(ROOT)
                    findings.append(f"  {rel}:{i}: [{name}] {stripped[:120]}")
            low = stripped.lower()
            for kw in SECRET_KEYWORDS:
                if kw in low and "=" in stripped:
                    val = stripped.split("=", 1)[-1].strip().strip("\"'")
                    if val.lower() not in SAFE_VALUE_TOKENS and len(val) > 6:
                        rel = f.relative_to(ROOT)
                        secrets.append(f"  {rel}:{i}: {stripped[:100]}")

# Check safety defaults
browser_path = ROOT / "friday" / "tools" / "browser.py"
conversation_path = ROOT / "friday" / "core" / "conversation.py"
executor_path = ROOT / "friday" / "planning" / "executor.py"

safety_checks = []
for fp, keyword, expected in [
    (browser_path, "dry_run: bool = True", "dry_run default True"),
    (conversation_path, "dry_run: bool = True", "conversation dry_run=True"),
    (executor_path, "allow_real_execution", "executor allow_real_execution guard"),
]:
    if fp.exists():
        content = fp.read_text(encoding="utf-8", errors="ignore")
        if keyword in content:
            safety_checks.append(f"  OK  [{expected}]")
        else:
            safety_checks.append(f"  FAIL [{expected}] — keyword not found: {keyword!r}")
    else:
        safety_checks.append(f"  MISS [{expected}] — file not found: {fp}")

# Print results
print("=" * 60)
print("PHASE 21 SECURITY SCAN")
print("=" * 60)
print()
print(f"DANGER PATTERNS ({len(findings)} items):")
if findings:
    for x in findings:
        print(x)
else:
    print("  CLEAN")

print()
print(f"POTENTIAL SECRETS ({len(secrets)} items):")
if secrets:
    for x in secrets:
        print(x)
else:
    print("  CLEAN")

print()
print("SAFETY DEFAULTS:")
for x in safety_checks:
    print(x)

print()
total_issues = len(findings) + len(secrets)
if total_issues == 0:
    print("RESULT: CLEAN — no critical patterns found")
else:
    print(f"RESULT: {total_issues} item(s) require review")

sys.exit(0 if total_issues == 0 else 1)
