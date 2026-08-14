"""
Hardware Validation Harness for F.R.I.D.A.Y. Phase 11.

Run this script to validate end-to-end hardware readiness:
    python scripts/validate_hardware_e2e.py
"""
import sys
import os
import time
from pathlib import Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.utils.health_diagnostics import check_system_health
from friday.utils.logger import get_logger

logger = get_logger("hardware_validation")


def main():
    print("=" * 60)
    print(" F.R.I.D.A.Y. Phase 11 Hardware Integration Check")
    print("=" * 60)

    t0 = time.perf_counter()
    health = check_system_health()
    elapsed = time.perf_counter() - t0

    print(f"\nOverall Status: {health['overall_status']} (checked in {elapsed:.2f}s)\n")
    print("Component Status:")
    print("-" * 60)

    for comp, data in health["components"].items():
        status_str = f"[{data['status']}]"
        print(f"  {comp.upper():<12} {status_str:<8} {data.get('details', '')}")
        if data.get("warnings"):
            for w in data["warnings"]:
                print(f"               ⚠️ Warning: {w}")

    print("-" * 60)

    if health["overall_status"] == "PASS":
        print("\nSUCCESS: All hardware & system components are operational.")
        sys.exit(0)
    else:
        print("\nDEGRADED/FAIL: One or more hardware components need attention.")
        sys.exit(1)


if __name__ == "__main__":
    main()
