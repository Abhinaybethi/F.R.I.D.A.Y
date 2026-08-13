"""
Real Voice -> Intent -> Dry-Run Pipeline Test.

Connects VoiceSessionManager (mic -> VAD -> Whisper small.en) directly to
the deterministic intent router, validator, and tool registry in DRY RUN mode.

No real computer actions are executed.

Run:
    python tests/test_voice_pipeline.py
"""
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from friday.voice.session_manager import VoiceSessionManager
from friday.intent.router import route
from friday.intent.models import Action
from friday.safety.validator import validate, Policy
from friday.tools import registry


def main():
    # Load config and enforce dry-run safety lock
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    voice_cfg = config.get("voice", {})
    stt_cfg = voice_cfg.get("stt", {})
    listening_cfg = config.get("listening", {})
    debug_cfg = voice_cfg.get("debug", {})

    print("=" * 60)
    print("  VOICE -> INTENT -> DRY RUN PIPELINE TEST")
    print("=" * 60)
    print("  Safety Lock: DRY RUN ONLY (no real actions will execute)")
    print("  Model      : small.en | CPU | int8")
    print("  Press Ctrl+C to stop.\n")

    # Metrics counter
    stats = {
        "utterances": 0,
        "recognized": 0,
        "intent_recognized": 0,
        "safe": 0,
        "confirmed": 0,
        "rejected": 0,
    }

    session = VoiceSessionManager(
        stt_config=stt_cfg,
        listening_config=listening_cfg,
        debug_config=debug_cfg,
    )

    with session:
        try:
            while True:
                text = session.listen_once()
                if not text:
                    continue

                stats["utterances"] += 1
                stats["recognized"] += 1

                print(f"\n[STT]\nHeard: {text}")

                intent = route(text)
                print(
                    f"\n[INTENT]\n"
                    f"Action:     {intent.action.name}\n"
                    f"Target:     {intent.target}\n"
                    f"Confidence: {intent.confidence:.2f}"
                )

                policy = validate(intent)
                print(f"\n[SAFETY]\nPolicy: {policy.name}")

                if intent.action != Action.UNKNOWN:
                    stats["intent_recognized"] += 1

                if policy == Policy.REJECT:
                    stats["rejected"] += 1
                    print("\nAssistant: I didn't understand that.")
                    continue

                execute_action = False
                if policy == Policy.SAFE:
                    stats["safe"] += 1
                    execute_action = True

                elif policy == Policy.CONFIRM:
                    target_desc = intent.target.title() if intent.target else ""
                    action_desc = intent.action.name.replace("_", " ").title()
                    desc = f"{action_desc} {target_desc}".strip()

                    print(f"\n[CONFIRMATION REQUIRED]\nDid you mean \"{desc}\"? [y/n]: ", end="", flush=True)
                    try:
                        ans = input().strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        print("\n[CANCELLED]")
                        break

                    if ans in ("y", "yes"):
                        stats["confirmed"] += 1
                        execute_action = True
                    else:
                        stats["rejected"] += 1
                        print("\n[CANCELLED]")

                if execute_action:
                    # Explicitly enforce dry_run=True, allow_real_execution=False
                    res = registry.execute(intent, dry_run=True, allow_real_execution=False)
                    print(f"\n[DRY RUN]\n{res.get('message')}")

        except KeyboardInterrupt:
            pass

    print("\n\n" + "=" * 50)
    print("VOICE PIPELINE SUMMARY")
    print("=" * 50)
    print(f"Utterances:        {stats['utterances']}")
    print(f"Recognized:        {stats['recognized']}")
    print(f"Intent recognized: {stats['intent_recognized']}")
    print(f"Safe:              {stats['safe']}")
    print(f"Confirmed:         {stats['confirmed']}")
    print(f"Rejected:          {stats['rejected']}")
    print("\nNo real actions executed.")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
