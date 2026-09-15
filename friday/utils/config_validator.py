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
    "minimize_app",
    "maximize_app",
    "take_screenshot",
    "play_video",
    "greeting",
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

    provider = reasoning.get("provider", "llamacpp")
    if provider not in ("ollama", "llamacpp"):
        messages.append(f"Invalid reasoning provider {provider!r}; defaulting to 'llamacpp'.")
        provider = "llamacpp"
    reasoning["provider"] = provider

    if provider == "ollama":
        default_endpoint = "http://localhost:11434/api/generate"
        default_model = "llama3:latest"
    else:
        default_endpoint = "http://127.0.0.1:8080"
        default_model = "C:\\AI\\models\\Bonsai-8B-Q1_0.gguf"

    endpoint = reasoning.get("endpoint", default_endpoint)
    if not isinstance(endpoint, str) or not (endpoint.startswith("http://") or endpoint.startswith("https://")):
        messages.append(f"Invalid reasoning endpoint URL {endpoint!r}; defaulting to {default_endpoint}.")
        reasoning["endpoint"] = default_endpoint
    else:
        reasoning["endpoint"] = endpoint

    model = reasoning.get("model", default_model)
    if not isinstance(model, str) or not model.strip():
        reasoning["model"] = default_model

    timeout = reasoning.get("timeout", 30)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        messages.append(f"Invalid reasoning timeout {timeout!r}; defaulting to 30.")
        reasoning["timeout"] = 30
    else:
        reasoning["timeout"] = float(timeout)

    # 2b. Reasoning server lifecycle settings
    server = dict(reasoning.get("server", {}))
    server.setdefault("auto_start", True)
    server.setdefault("executable", "llama-server")
    server.setdefault("context_size", 2048)
    server.setdefault("startup_timeout", 60)

    if not isinstance(server["auto_start"], bool):
        messages.append(f"Invalid server.auto_start {server['auto_start']!r}; defaulting to True.")
        server["auto_start"] = True
    if not isinstance(server["executable"], str) or not server["executable"].strip():
        server["executable"] = "llama-server"
    if not isinstance(server["context_size"], int) or server["context_size"] <= 0:
        server["context_size"] = 2048
    if not isinstance(server["startup_timeout"], (int, float)) or server["startup_timeout"] <= 0:
        server["startup_timeout"] = 60.0
    else:
        server["startup_timeout"] = float(server["startup_timeout"])

    reasoning["server"] = server
    sanitized["reasoning"] = reasoning

    # 3. Voice Layer Validation (active-session / wake-gate settings)
    voice = dict(sanitized.get("voice", {}))

    raw_wake_required = voice.get("wake_word_required", True)
    if not isinstance(raw_wake_required, bool):
        messages.append(f"Invalid voice.wake_word_required {raw_wake_required!r}; defaulting to True.")
        voice["wake_word_required"] = True
    else:
        voice["wake_word_required"] = raw_wake_required

    raw_timeout = voice.get("conversation_timeout_seconds", 300)
    if not isinstance(raw_timeout, (int, float)) or raw_timeout <= 0:
        messages.append(f"Invalid voice.conversation_timeout_seconds {raw_timeout!r}; defaulting to 300.")
        voice["conversation_timeout_seconds"] = 300
    else:
        # Clamp to the supported 180–300s inactivity window.
        voice["conversation_timeout_seconds"] = int(max(180, min(300, int(raw_timeout))))
        if int(raw_timeout) != voice["conversation_timeout_seconds"]:
            messages.append(
                f"voice.conversation_timeout_seconds clamped to {voice['conversation_timeout_seconds']}s (supported range 180–300)."
            )

    sanitized["voice"] = voice

    # Log any configuration sanitization messages
    for msg in messages:
        logger.warning("[CONFIG] %s", msg)

    return True, sanitized, messages
