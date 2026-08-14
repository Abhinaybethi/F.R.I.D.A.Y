"""
DEPRECATED / LEGACY MODULE QUARANTINE
=====================================
Contains early Phase 1-3 prototype modules that are NOT used in the active F.R.I.D.A.Y. runtime.

The active pipeline uses:
  - Router:       friday.intent.router
  - Reasoning:    friday.reasoning.local_reasoner
  - Planner:      friday.planning.planner / executor
  - Safety:       friday.safety.permissions / validator
  - Execution:    friday.tools.registry (apps / browser / files / system)
  - Verification: friday.verification.verifier

DO NOT IMPORT ANYTHING FROM THIS DIRECTORY IN ACTIVE PIPELINE CODE.
"""
__deprecated__ = True
