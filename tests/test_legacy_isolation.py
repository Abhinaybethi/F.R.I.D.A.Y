"""
UNIT TEST — Legacy Code Isolation & Deprecation
================================================
Verifies that all dead legacy modules (friday.system_control, friday.skills,
friday.brain, friday.core.command_router) are strictly isolated and NOT imported
by any active runtime pipeline module.
"""
import sys
import os
import glob
from pathlib import Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


ACTIVE_MODULE_PATHS = [
    "main.py",
    "friday/core/assistant.py",
    "friday/core/conversation.py",
    "friday/core/state.py",
    "friday/core/wake_word.py",
    "friday/intent/models.py",
    "friday/intent/router.py",
    "friday/intent/normalizer.py",
    "friday/safety/permissions.py",
    "friday/safety/validator.py",
    "friday/safety/confirmation.py",
    "friday/planning/planner.py",
    "friday/planning/executor.py",
    "friday/planning/plan_models.py",
    "friday/planning/plan_validator.py",
    "friday/planning/context_resolver.py",
    "friday/reasoning/interface.py",
    "friday/reasoning/local_reasoner.py",
    "friday/reasoning/parser.py",
    "friday/reasoning/prompt.py",
    "friday/reasoning/validator.py",
    "friday/tools/registry.py",
    "friday/tools/apps.py",
    "friday/tools/browser.py",
    "friday/tools/files.py",
    "friday/tools/system.py",
    "friday/verification/__init__.py",
    "friday/verification/models.py",
    "friday/verification/verifier.py",
    "friday/verification/action_verifiers.py",
    "friday/verification/formatter.py",
    "friday/utils/audit_logger.py",
    "friday/utils/logger.py",
    "friday/voice/audio_input.py",
    "friday/voice/speech_to_text.py",
    "friday/voice/text_to_speech.py",
    "friday/voice/vad.py",
    "friday/voice/session_manager.py",
]

FORBIDDEN_LEGACY_IMPORTS = [
    "friday.system_control",
    "friday.skills",
    "friday.brain",
    "friday.core.command_router",
]


def test_active_pipeline_files_exist():
    """Verify all listed active pipeline files exist."""
    root = Path(__file__).parent.parent
    for rel_path in ACTIVE_MODULE_PATHS:
        full_path = root / rel_path
        assert full_path.exists(), f"Active pipeline file missing: {full_path}"


def test_active_pipeline_imports_zero_legacy_code():
    """Verify no active pipeline file imports any forbidden legacy modules."""
    root = Path(__file__).parent.parent
    violations = []

    for rel_path in ACTIVE_MODULE_PATHS:
        full_path = root / rel_path
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()

        for forbidden in FORBIDDEN_LEGACY_IMPORTS:
            if forbidden in content:
                violations.append(f"{rel_path} imports {forbidden!r}")

    assert not violations, f"Forbidden legacy imports found in active pipeline:\n" + "\n".join(violations)


def test_legacy_modules_are_deprecated():
    """Verify legacy_deprecated package exists with deprecation notice."""
    leg_path = Path(__file__).parent.parent / "friday" / "legacy_deprecated" / "__init__.py"
    assert leg_path.exists(), f"Legacy deprecation package missing at {leg_path}"
    with open(leg_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "__deprecated__" in content or "DEPRECATED" in content


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
