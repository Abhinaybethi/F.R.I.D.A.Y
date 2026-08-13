"""
Tool Test — dry-run mode only.
================================
Tests every registered tool via the registry.  No actual applications are
opened or closed.  dry_run is always True here.

Run:
    python tests/test_tools.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.models import Action, Intent
from friday.tools import registry, apps, browser, files, system


def _section(title: str):
    print(f"\n{'-' * 56}")
    print(f"  {title}")
    print(f"{'-' * 56}")


def _check(label: str, result: dict, expect_success: bool = True):
    ok = result.get("success") == expect_success
    status = "OK  " if ok else "FAIL"
    print(f"  [{status}] {label}")
    print(f"         {result.get('message', result)}")
    return ok


def run():
    print("\n" + "=" * 56)
    print("  TOOL TEST  (dry_run=True throughout)")
    print("=" * 56)

    passed = 0
    total = 0

    def test(label: str, result: dict, expect_success: bool = True):
        nonlocal passed, total
        total += 1
        passed += _check(label, result, expect_success)

    # -----------------------------------------------------------------------
    _section("System - get_time()")
    r = system.get_time()
    test("get_time()", r)
    print(f"         time={r.get('time')}")

    # -----------------------------------------------------------------------
    _section("Apps - open_app() dry-run")
    for app in ["chrome", "edge", "firefox", "vscode", "notepad", "explorer"]:
        test(f"open_app({app!r})", apps.open_app(app, dry_run=True))

    _section("Apps - open_app() unknown")
    test("open_app('unknown')", apps.open_app("unknown", dry_run=True), expect_success=False)

    _section("Apps - close_app() dry-run")
    for app in ["chrome", "edge", "vscode"]:
        test(f"close_app({app!r})", apps.close_app(app, dry_run=True))

    # -----------------------------------------------------------------------
    _section("Browser - open_website() dry-run")
    for site in ["youtube", "google", "github"]:
        test(f"open_website({site!r})", browser.open_website(site, dry_run=True))

    test("open_website('unknown')", browser.open_website("unknown", dry_run=True), expect_success=False)

    _section("Browser - search_web() dry-run")
    test("search_web('python tutorials')", browser.search_web("python tutorials", dry_run=True))
    test("search_web('')", browser.search_web("", dry_run=True), expect_success=False)

    # -----------------------------------------------------------------------
    _section("Files - find_file()")
    r = files.find_file("resume")
    test("find_file('resume') - runs on real fs", r)
    print(f"         candidates: {r.get('candidates', [])[:3]}")

    r2 = files.find_file("")
    test("find_file('') - empty query", r2, expect_success=False)

    _section("Files - open_folder() dry-run")
    for folder in ["downloads", "documents", "desktop"]:
        test(f"open_folder({folder!r})", files.open_folder(folder, dry_run=True))

    test("open_folder('unknown')", files.open_folder("unknown", dry_run=True), expect_success=False)

    # -----------------------------------------------------------------------
    _section("Registry - execute() via Intent objects (dry-run)")

    intents = [
        Intent(action=Action.OPEN_APP,     target="chrome",            intent_confidence=0.9, target_confidence=1.0, confidence=0.9),
        Intent(action=Action.CLOSE_APP,    target="vscode",            intent_confidence=0.9, target_confidence=1.0, confidence=0.9),
        Intent(action=Action.OPEN_WEBSITE, target="youtube",           intent_confidence=0.9, target_confidence=1.0, confidence=0.9),
        Intent(action=Action.SEARCH_WEB,   target="python tutorials",  intent_confidence=0.9, target_confidence=1.0, confidence=0.9),
        Intent(action=Action.OPEN_FOLDER,  target="downloads",         intent_confidence=0.9, target_confidence=1.0, confidence=0.9),
        Intent(action=Action.GET_TIME,                                  intent_confidence=0.9, target_confidence=1.0, confidence=0.9),
    ]
    for intent in intents:
        label = f"registry.execute({intent.action.name}, target={intent.target!r})"
        test(label, registry.execute(intent, dry_run=True))

    # -----------------------------------------------------------------------
    print(f"\n{'=' * 56}")
    print(f"  {passed}/{total} passed")
    print(f"{'=' * 56}\n")
    return passed == total


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
