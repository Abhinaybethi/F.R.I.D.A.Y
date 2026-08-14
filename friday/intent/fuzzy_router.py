"""
Fuzzy Phonetic Intent Router for F.R.I.D.A.Y. Phase 14 (P1).

Resolves STT near-misses (e.g. "open grove" -> "chrome", "on youtube" -> "youtube")
deterministically in < 0.5 ms without invoking Ollama LLM fallback.
"""
import re
from typing import Optional, Set
from friday.intent.models import Action, Intent
from friday.tools.apps import _APP_EXECUTABLES
from friday.tools.browser import _WEBSITE_URLS
from friday.tools.files import _SAFE_DIRS
from friday.utils.logger import get_logger

logger = get_logger(__name__)

# Phonetic & Common STT Mis-transcription Alias Map
_TARGET_ALIASES = {
    # Apps
    "grove": "chrome",
    "groom": "chrome",
    "chorm": "chrome",
    "crome": "chrome",
    "chrom": "chrome",
    "vs code": "vscode",
    "openvscode": "vscode",
    "vis code": "vscode",
    "note pad": "notepad",
    "note": "notepad",
    "calc": "calculator",
    
    # Websites
    "u tube": "youtube",
    "utube": "youtube",
    "you tube": "youtube",
    "googl": "google",
    "gogle": "google",
    "git hub": "github",
    "git": "github",
}


def get_dynamic_targets() -> Set[str]:
    """Dynamically harvest all registered tool target names and safe aliases."""
    targets = set(_APP_EXECUTABLES.keys()) | set(_WEBSITE_URLS.keys()) | set(_SAFE_DIRS.keys())
    return targets


def fuzzy_route(transcript: str) -> Optional[Intent]:
    """
    Perform fuzzy / phonetic target resolution on unrouted transcripts.

    Returns:
        Intent if a near-miss target is confidently resolved, else None.
    """
    norm = transcript.lower().strip()
    if not norm or len(norm) < 3:
        return None

    # Strip opening phrases like "could you open", "please open", "on"
    clean = re.sub(r"^(could\s+you\s+|please\s+|can\s+you\s+)?(open|launch|start|show|on)\s+", "", norm).strip()

    # 1. Alias lookup check
    if clean in _TARGET_ALIASES:
        canonical = _TARGET_ALIASES[clean]
        return _build_intent_for_target(canonical)

    # Check direct word token in alias dict
    tokens = clean.split()
    for tok in tokens:
        if tok in _TARGET_ALIASES:
            canonical = _TARGET_ALIASES[tok]
            return _build_intent_for_target(canonical)

    # 2. Levenshtein Distance Matching against dynamically registered safe targets
    all_targets = get_dynamic_targets()
    best_target = None
    best_dist = 999

    for target in all_targets:
        dist = _levenshtein_distance(clean, target)
        if dist < best_dist and dist <= 2:  # Max 2 character edits allowed
            best_dist = dist
            best_target = target

    if best_target and best_dist <= 2:
        logger.info("[FUZZY ROUTER] Matched %r -> %r (dist=%d)", clean, best_target, best_dist)
        return _build_intent_for_target(best_target)

    return None


def _build_intent_for_target(target: str) -> Intent:
    """Build Intent for recognized target string."""
    if target in _APP_EXECUTABLES:
        return Intent(action=Action.OPEN_APP, target=target, confidence=0.90)
    elif target in _WEBSITE_URLS:
        return Intent(action=Action.OPEN_WEBSITE, target=target, confidence=0.90)
    elif target in _SAFE_DIRS:
        return Intent(action=Action.OPEN_FOLDER, target=target, confidence=0.90)
    return Intent(action=Action.OPEN_APP, target=target, confidence=0.90)


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for index2, char2 in enumerate(s2):
        new_distances = [index2 + 1]
        for index1, char1 in enumerate(s1):
            if char1 == char2:
                new_distances.append(distances[index1])
            else:
                new_distances.append(1 + min((distances[index1], distances[index1 + 1], new_distances[-1])))
        distances = new_distances
    return distances[-1]
