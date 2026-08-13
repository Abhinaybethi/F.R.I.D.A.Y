"""
Real Tools Test
===============
Safely test real tool execution.

IMPORTANT:
This test MUST NOT automatically execute anything.
By default, it verifies configuration and prints:
"Real tool execution is disabled."

To manually enable real execution for testing:
    python tests/test_real_tools.py --allow-real

Only the following 4 safe read/open actions are tested:
1. Open Notepad
2. Open Chrome
3. Open YouTube
4. Open Downloads

Closing applications or file modifications are NOT tested here.
"""
import sys
import yaml
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from friday.tools import apps, browser, files


def main():
    allow_flag = "--allow-real" in sys.argv

    # Check config.yaml
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    tools_cfg = cfg.get("tools", {})
    cfg_dry = tools_cfg.get("dry_run", True)
    cfg_allow = tools_cfg.get("allow_real_execution", False)

    print("=" * 60)
    print("  REAL TOOLS TEST")
    print("=" * 60)
    print(f"  Config dry_run              : {cfg_dry}")
    print(f"  Config allow_real_execution : {cfg_allow}")
    print(f"  CLI --allow-real flag       : {allow_flag}")

    real_enabled = (not cfg_dry) and cfg_allow and allow_flag

    if not real_enabled:
        print("\n  [SAFETY LOCK] Real tool execution is disabled.")
        print("  To run real execution test:")
        print("    1. Set dry_run: false AND allow_real_execution: true in config.yaml")
        print("    2. Pass --allow-real flag to this script")
        print("=" * 60)
        return

    print("\n  [WARNING] REAL EXECUTION IS ENABLED! Running safe open tests...\n")

    # 1. Open Notepad
    print("  1. Testing Open Notepad...")
    res = apps.open_app("notepad", dry_run=False)
    print(f"     Result: {res}")

    # 2. Open Chrome
    print("\n  2. Testing Open Chrome...")
    res = apps.open_app("chrome", dry_run=False)
    print(f"     Result: {res}")

    # 3. Open YouTube
    print("\n  3. Testing Open YouTube...")
    res = browser.open_website("youtube", dry_run=False)
    print(f"     Result: {res}")

    # 4. Open Downloads
    print("\n  4. Testing Open Downloads folder...")
    res = files.open_folder("downloads", dry_run=False)
    print(f"     Result: {res}")

    print("\n" + "=" * 60)
    print("  Real tool execution test completed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
