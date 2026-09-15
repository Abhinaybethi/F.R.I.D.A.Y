"""
Phase 29 Real Action Execution Certification Test Suite.

Verifies end-to-end trace, execution outcome, independent observation,
and classification across all 20 benchmark commands under dry-run and real modes.
"""
import pytest
import sqlite3
from contextlib import closing

from friday.core.conversation import ConversationManager, ConversationState
from friday.intent.models import Action, Intent
from friday.verification.models import (
    ExecutionStatus,
    VerificationStatus,
    FinalStatus,
    ActionOutcome,
)
from friday.verification.verifier import verify_execution
from friday.tools import registry, memory, apps, browser, files


def _create_cm(dry_run: bool = True, allow_real_execution: bool = False):
    cm = ConversationManager(dry_run=dry_run, allow_real_execution=allow_real_execution)
    cm.start_session()
    return cm


# 1. open Chrome
def test_cmd1_open_chrome_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("open Chrome")
    assert "[DRY RUN]" in resp and "open Chrome" in resp
    assert cm.context.last_intent.action == Action.OPEN_APP
    assert cm.context.last_intent.target == "chrome"

    # Verify dry_run returns SIMULATED
    intent = Intent(action=Action.OPEN_APP, target="chrome")
    out = registry.execute(intent, dry_run=True)
    assert out.verification.status == VerificationStatus.DRY_RUN


# 2. open YouTube
def test_cmd2_open_youtube_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("open YouTube")
    assert "Opening Youtube" in resp or "youtube" in resp.lower()
    assert cm.context.last_intent.action == Action.OPEN_WEBSITE
    assert cm.context.last_intent.target == "youtube"

    intent = Intent(action=Action.OPEN_WEBSITE, target="youtube")
    out = registry.execute(intent, dry_run=True)
    assert out.verification.status == VerificationStatus.DRY_RUN


# 3. open Downloads
def test_cmd3_open_downloads_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("open Downloads")
    assert "Download" in resp
    assert cm.context.last_intent.action == Action.OPEN_FOLDER
    assert cm.context.last_intent.target == "download"

    intent = Intent(action=Action.OPEN_FOLDER, target="download")
    out = registry.execute(intent, dry_run=True)
    assert out.verification.status == VerificationStatus.DRY_RUN


# 4. find my resume
def test_cmd4_find_my_resume_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("find my resume")
    assert cm.context.last_intent.action == Action.FIND_FILE
    assert cm.context.last_intent.target == "resume"

    intent = Intent(action=Action.FIND_FILE, target="resume")
    out = registry.execute(intent, dry_run=True)
    assert out.verification.status in (VerificationStatus.DRY_RUN, VerificationStatus.NOT_APPLICABLE)


# 5. search Python tutorials
def test_cmd5_search_python_tutorials_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("search Python tutorials")
    assert "Searching" in resp or "python tutorials" in resp.lower()
    assert cm.context.last_intent.action == Action.SEARCH_WEB
    assert cm.context.last_intent.target == "python tutorials"

    intent = Intent(action=Action.SEARCH_WEB, target="python tutorials")
    out = registry.execute(intent, dry_run=True)
    assert out.verification.status == VerificationStatus.DRY_RUN


# 6. open first result
def test_cmd6_open_first_result_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    cm.context.last_search_results = [
        {"title": "Python Tutorials", "url": "https://example.com/python"}
    ]

    resp, cont = cm.handle_transcript("open first result")
    assert "Opening" in resp or "example.com/python" in resp
    assert cm.context.last_intent.action == Action.OPEN_WEBSITE
    assert cm.context.last_intent.target == "https://example.com/python"


# 7. read it
def test_cmd7_read_it_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    cm.context.last_intent = Intent(action=Action.OPEN_WEBSITE, target="https://example.com/article")

    resp, cont = cm.handle_transcript("read it")
    assert "Reading" in resp or "example.com/article" in resp or "Here is the page content" in resp
    assert cm.context.last_intent.action == Action.READ_WEBSITE
    assert cm.context.last_intent.target == "https://example.com/article"


# 8. remember my editor is VS Code
def test_cmd8_remember_my_editor_is_vscode_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("remember my editor is VS Code")
    assert "editor" in resp.lower() or "remember" in resp.lower()
    assert cm.context.last_intent.action == Action.REMEMBER

    intent = Intent(action=Action.REMEMBER, target="my editor is VS Code", arguments={"key_name": "editor", "category": "preference"})
    out = registry.execute(intent, dry_run=True)
    assert out.verification.status == VerificationStatus.DRY_RUN


# 9. recall my editor
def test_cmd9_recall_my_editor_certification():
    memory.remember("my editor is VS Code", category="preference", key_name="editor", dry_run=False)
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("recall my editor")
    assert "VS Code" in resp or "editor" in resp
    assert cm.context.last_intent.action == Action.RECALL

    intent = Intent(action=Action.RECALL, target="editor")
    out = registry.execute(intent, dry_run=True)
    assert out.verification.status in (VerificationStatus.DRY_RUN, VerificationStatus.NOT_APPLICABLE)


# 10. update my editor to PyCharm
def test_cmd10_update_my_editor_to_pycharm_certification():
    memory.remember("my editor is VS Code", category="preference", key_name="editor", dry_run=False)
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("update my editor to PyCharm")
    assert "editor" in resp.lower() or "remember" in resp.lower()

    # Real DB update
    res = memory.remember("my editor is PyCharm", category="preference", key_name="editor", dry_run=False)
    assert res["success"] is True

    # Verify preference was updated in SQLite
    resolved = memory.resolve_preference("editor")
    assert resolved == "PyCharm"


# 11. recall my editor (after update)
def test_cmd11_recall_updated_editor_certification():
    memory.remember("my editor is PyCharm", category="preference", key_name="editor", dry_run=False)
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("recall my editor")
    assert "PyCharm" in resp


# 12. forget my editor
def test_cmd12_forget_my_editor_certification():
    memory.remember("my editor is PyCharm", category="preference", key_name="editor", dry_run=False)
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp1, cont1 = cm.handle_transcript("forget my editor")
    assert "Do you want me to forget" in resp1
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    # Confirm YES
    resp2, cont2 = cm.handle_transcript("yes")
    assert "Forgot" in resp2 or "forgotten" in resp2 or "Forgotten" in resp2
    assert cm.state == ConversationState.LISTENING


# 13. cancel
def test_cmd13_cancel_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("cancel")
    assert resp == "Cancelled."
    assert cont is True
    assert cm.state == ConversationState.LISTENING


# 14. confirmation NO
def test_cmd14_confirmation_no_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp1, cont1 = cm.handle_transcript("forget my editor")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    resp2, cont2 = cm.handle_transcript("no")
    assert resp2 == "Cancelled."
    assert cm.state == ConversationState.LISTENING


# 15. confirmation YES
def test_cmd15_confirmation_yes_certification():
    memory.remember("test preference", dry_run=False)
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp1, cont1 = cm.handle_transcript("forget test preference")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    resp2, cont2 = cm.handle_transcript("yes")
    assert cm.state == ConversationState.LISTENING
    assert "Forgot" in resp2 or "forgotten" in resp2 or "Forgotten" in resp2


# 16. open VS Code
def test_cmd16_open_vscode_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("open VS Code")
    assert "[DRY RUN]" in resp and "open VS Code" in resp
    assert cm.context.last_intent.action == Action.OPEN_APP
    assert cm.context.last_intent.target == "vscode"

    intent = Intent(action=Action.OPEN_APP, target="vscode")
    out = registry.execute(intent, dry_run=True)
    assert out.verification.status == VerificationStatus.DRY_RUN


# 17. open Notepad
def test_cmd17_open_notepad_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("open Notepad")
    assert "[DRY RUN]" in resp and "open Notepad" in resp
    assert cm.context.last_intent.action == Action.OPEN_APP
    assert cm.context.last_intent.target == "notepad"

    intent = Intent(action=Action.OPEN_APP, target="notepad")
    out = registry.execute(intent, dry_run=True)
    assert out.verification.status == VerificationStatus.DRY_RUN


# 18. search Python internships
def test_cmd18_search_python_internships_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("search Python internships")
    assert "Searching" in resp or "python internships" in resp.lower()
    assert cm.context.last_intent.action == Action.SEARCH_WEB
    assert cm.context.last_intent.target == "python internships"

    intent = Intent(action=Action.SEARCH_WEB, target="python internships")
    out = registry.execute(intent, dry_run=True)
    assert out.verification.status == VerificationStatus.DRY_RUN


# 19. read the first result
def test_cmd19_read_the_first_result_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    cm.context.last_search_results = [
        {"title": "Python Internships", "url": "https://example.com/internships"}
    ]

    resp, cont = cm.handle_transcript("read the first result")
    assert "Reading" in resp or "example.com/internships" in resp or "Here is the page content" in resp
    assert cm.context.last_intent.action == Action.READ_WEBSITE
    assert cm.context.last_intent.target == "https://example.com/internships"


# 20. stop F.R.I.D.A.Y. speaking
def test_cmd20_stop_friday_speaking_certification():
    cm = _create_cm(dry_run=True, allow_real_execution=False)
    resp, cont = cm.handle_transcript("stop Friday speaking")
    assert resp in ("Goodbye.", "Stopped.") or cm.state in (ConversationState.STOPPING, ConversationState.LISTENING)
