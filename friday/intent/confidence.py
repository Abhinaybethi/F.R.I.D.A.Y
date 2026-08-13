"""Confidence computation — the weakest link propagates."""


def compute(intent_confidence: float, target_confidence: float) -> float:
    """
    Overall confidence = min(intent_confidence, target_confidence).

    A high intent confidence cannot compensate for a shaky target.
    Example:
        intent  = 0.98  (clearly an OPEN_APP command)
        target  = 0.55  ("grove" → "chrome" fuzzy match)
        overall = 0.55  → MEDIUM → require confirmation
    """
    return min(intent_confidence, target_confidence)
