"""Conservative text normalizer — lowercase, punctuation, whitespace only."""
import re


def normalize(text: str) -> str:
    """
    Lowercase, strip punctuation, collapse whitespace.

    Conservative by design: no word substitutions, no aggressive spelling
    correction.  The router and resolver handle ambiguity downstream.
    """
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)   # drop punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text
