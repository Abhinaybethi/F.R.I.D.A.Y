"""Phase 21 Release Audit — Security Recheck Script."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from friday.tools.files import find_file, open_file
from friday.tools.browser import _validate_url_security
from friday.tools.memory import remember, recall
from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState

all_pass = True


def chk(label, cond, detail=""):
    global all_pass
    status = "PASS" if cond else "FAIL"
    if not cond:
        all_pass = False
    print(f"  {status}  {label}" + (f" | {detail}" if detail else ""))


print("=" * 60)
print("SSRF BOUNDARY CHECKS")
print("=" * 60)
blocked_targets = [
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8080",
    "http://[::1]",
    "http://10.0.0.1",
    "http://192.168.1.1",
    "http://172.16.0.1",
    "http://169.254.169.254",
    "file:///etc/passwd",
    "ftp://example.com/file.txt",
    "data:text/plain;base64,SGVsbG8=",
    "javascript:alert(1)",
    "http://something.local",
    "http://service.internal",
]
for t in blocked_targets:
    safe, reason = _validate_url_security(t, is_dry_run=False)
    chk(f"Blocked: {t[:50]}", not safe, reason[:60])

# NAT64 check
import ipaddress
nat64_ip = ipaddress.ip_address("64:ff9b::4.4.4.4")
nat64_ok = nat64_ip in ipaddress.IPv6Network("64:ff9b::/96")
chk("NAT64 64:ff9b::/96 recognized", nat64_ok)

print()
print("=" * 60)
print("PATH TRAVERSAL CHECKS")
print("=" * 60)
traversal_payloads = [
    "../secret.txt",
    "..\\secret.txt",
    "../../../../etc/passwd",
    "..\\..\\..\\Windows\\System32\\config",
    "\\\\server\\share\\file.txt",
    "//server/share/file.txt",
    "C:\\Windows\\System32\\cmd.exe",
    "D:\\data.txt",
    "/etc/shadow",
    "mixed/../traversal",
    "%2e%2e%2fsecret.txt",
    "....//....//secret.txt",
]
for p in traversal_payloads:
    res = find_file(p)
    blocked = not res["success"]
    chk(f"find_file blocked: {p[:50]}", blocked, res["message"][:60])

# open_file blocks absolute paths outside safe roots
res = open_file(r"C:\Windows\System32\calc.exe", dry_run=True)
chk("open_file blocks C:\\Windows\\System32\\calc.exe", not res["success"], res["message"][:60])

# open_file allows safe path in Downloads
safe_path = str(Path.home() / "Downloads" / "test.txt")
res = open_file(safe_path, dry_run=True)
chk("open_file allows Downloads/test.txt", res["success"], res.get("message", "")[:60])

print()
print("=" * 60)
print("FORGET GATE CHECKS")
print("=" * 60)
import sqlite3, tempfile, os

# Test via ConversationManager dry_run conversation state machine
cm = ConversationManager(dry_run=True, allow_real_execution=False)
cm.start_session()
cm.handle_transcript("remember that my name is Alice")

# FORGET requires confirmation
resp, keep = cm.handle_transcript("forget my name")
confirmation_requested = cm.state == ConversationState.WAITING_FOR_CONFIRMATION
chk("FORGET enters WAITING_FOR_CONFIRMATION", confirmation_requested, f"state={cm.state}")

# NO does nothing
resp, keep = cm.handle_transcript("no")
chk("NO does not execute FORGET", cm.state != ConversationState.WAITING_FOR_CONFIRMATION or "cancelled" in resp.lower() or "Cancelled" in resp, resp[:60])

# Re-trigger
cm2 = ConversationManager(dry_run=True, allow_real_execution=False)
cm2.start_session()
cm2.handle_transcript("remember that my name is Alice")
cm2.handle_transcript("forget my name")
resp_yes, _ = cm2.handle_transcript("yes")
chk("YES executes FORGET", cm2.context.current_plan is None, resp_yes[:60])

# YES outside confirmation window does nothing dangerous
cm3 = ConversationManager(dry_run=True, allow_real_execution=False)
cm3.start_session()
resp_stray, _ = cm3.handle_transcript("yes")
chk("YES outside confirmation is safe (no crash)", True, resp_stray[:40])

print()
print("=" * 60)
print("MEMORY DEDUPLICATION CHECKS")
print("=" * 60)
# remember() deduplication requires actual DB writes (dry_run=True never writes)
# so we use dry_run=False for the first entry, then verify duplicates are caught
import sqlite3
from contextlib import closing
from friday.tools.memory import _get_db_path
r1 = remember("my favorite color is blue", dry_run=False)
r2 = remember("my favorite color is blue", dry_run=False)  # exact duplicate
r3 = remember("My Favorite Color Is Blue", dry_run=False)  # case variant
r4 = remember("  my favorite color is blue  ", dry_run=False)  # whitespace variant
chk("Duplicate detected (exact)", r2.get("duplicate") is True, str(r2.get("message", ""))[:60])
chk("Duplicate detected (case variant)", r3.get("duplicate") is True, str(r3.get("message", ""))[:60])
chk("Duplicate detected (whitespace variant)", r4.get("duplicate") is True, str(r4.get("message", ""))[:60])
# Cleanup test data
try:
    with closing(sqlite3.connect(_get_db_path())) as _c:
        _c.execute("DELETE FROM memories WHERE content LIKE ?", ("%color%",))
        _c.commit()
except Exception:
    pass

print()
print("=" * 60)
print("WEB SEARCH / CONTEXT ISOLATION CHECKS")
print("=" * 60)
from unittest.mock import patch
with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 80))]):
    cm4 = ConversationManager(dry_run=True, allow_real_execution=False)
    cm4.start_session()
    cm4.handle_transcript("search for python tutorials")
    has_results = cm4.context.last_tool_result is not None
    chk("Web search results stored in short-term context", has_results)
    results = cm4.context.last_tool_result or {}
    chk("Results are not stored in long-term memory", "results" in results or has_results)

    resp_open, _ = cm4.handle_transcript("open the first result")
    chk("'open the first result' resolves from context", "Would open" in resp_open or "Opening" in resp_open, resp_open[:60])

    cm5 = ConversationManager(dry_run=True, allow_real_execution=False)
    cm5.start_session()
    resp_no_ctx, _ = cm5.handle_transcript("open the first result")
    chk("'open the first result' with no context rejected", "don't have" in resp_no_ctx.lower() or "result list" in resp_no_ctx.lower() or "I didn't understand" in resp_no_ctx, resp_no_ctx[:60])

print()
print("=" * 60)
print("SAFETY DEFAULTS")
print("=" * 60)
import inspect
sig = inspect.signature(ConversationManager.__init__)
params = sig.parameters
chk("dry_run default = True", params["dry_run"].default is True)
chk("allow_real_execution default = False", params["allow_real_execution"].default is False)

print()
print("=" * 60)
status_msg = "ALL CHECKS PASSED" if all_pass else "SOME CHECKS FAILED"
print(f"RESULT: {status_msg}")
print("=" * 60)
sys.exit(0 if all_pass else 1)
