"""
Configuration Validator Subsystem for F.R.I.D.A.Y. Phase 10.

Enforces strict fail-closed safety defaults:
  - dry_run: Coerced to bool; defaults to True if missing or invalid
  - allow_real_execution: Coerced to bool; defaults to False if missing or invalid
  - permissions: Unknown keys rejected; invalid values fail closed to False
  - reasoning endpoint & model: Structure & type validated
"""
from typing import Any, Tuple
from urllib.parse import urlparse
from friday.utils.logger import get_logger

logger = get_logger(__name__)

# Known permission keys matching Action enum
VALID_PERMISSION_KEYS = {
    "open_app",
    "close_app",
    "open_folder",
    "open_website",
    "search_web",
    "get_time",
    "find_file",
    "open_file",
}


def validate_config(config: dict) -> Tuple[bool, dict, list[str]]:
    """
    Validate and sanitize the configuration dictionary.

    Args:
        config: Raw dictionary loaded from config.yaml.

    Returns:
        (is_valid, sanitized_config, messages)
        - is_valid: True if no critical errors encountered
        - sanitized_config: Copy of config with fail-closed safety defaults applied
        - messages: List of warning or error messages
    """
    messages = []
    sanitized = dict(config or {})

    # 1. Tools & Safety Gate Validation
    tools = dict(sanitized.get("tools", {}))

    # Gate 1: dry_run (Must be strict bool; fails closed to True)
    raw_dry_run = tools.get("dry_run", True)
    if not isinstance(raw_dry_run, bool):
        messages.append(f"Invalid dry_run setting {raw_dry_run!r} (type {type(raw_dry_run).__name__}); defaulting to True (fail-closed).")
        tools["dry_run"] = True
    else:
        tools["dry_run"] = raw_dry_run

    # Gate 2: allow_real_execution (Must be strict bool; fails closed to False)
    raw_allow_real = tools.get("allow_real_execution", False)
    if not isinstance(raw_allow_real, bool):
        messages.append(f"Invalid allow_real_execution setting {raw_allow_real!r} (type {type(raw_allow_real).__name__}); defaulting to False (fail-closed).")
        tools["allow_real_execution"] = False
    else:
        tools["allow_real_execution"] = raw_allow_real

    # Gate 3: permissions dictionary validation
    raw_perms = tools.get("permissions", {})
    sanitized_perms = {}
    if not isinstance(raw_perms, dict):
        messages.append(f"Invalid permissions block (type {type(raw_perms).__name__}); initializing safe defaults.")
        raw_perms = {}

    for k, v in raw_perms.items():
        if k not in VALID_PERMISSION_KEYS:
            messages.append(f"Unknown permission key {k!r} ignored.")
            continue
        if not isinstance(v, bool):
            messages.append(f"Invalid boolean value for permission {k!r} ({v!r}); setting to False (fail-closed).")
            sanitized_perms[k] = False
        else:
            sanitized_perms[k] = v

    # Ensure all valid keys are present (defaulting missing ones to True for backward compat if tools enabled)
    for valid_key in VALID_PERMISSION_KEYS:
        if valid_key not in sanitized_perms:
            sanitized_perms[valid_key] = True

    tools["permissions"] = sanitized_perms
    sanitized["tools"] = tools

    # 2. Reasoning Layer Validation
    reasoning = dict(sanitized.get("reasoning", {}))
    endpoint = reasoning.get("endpoint", "http://localhost:11434/api/generate")
    if not isinstance(endpoint, str) or not (endpoint.startswith("http://") or endpoint.startswith("https://")):
        messages.append(f"Invalid reasoning endpoint URL {endpoint!r}; defaulting to http://localhost:11434/api/generate.")
        reasoning["endpoint"] = "http://localhost:11434/api/generate"

    model = reasoning.get("model", "llama3:latest")
    if not isinstance(model, str) or not model.strip():
        reasoning["model"] = "llama3:latest"

    sanitized["reasoning"] = reasoning

    # Log any configuration sanitization messages
    for msg in messages:
        logger.warning("[CONFIG] %s", msg)

    return True, sanitized, messages
