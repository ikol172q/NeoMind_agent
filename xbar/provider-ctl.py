#!/usr/bin/env python3
"""
provider-ctl.py — Self-contained CLI tool for reading/writing provider-state.json.

Zero dependencies (stdlib only). Called by xbar and usable from terminal.
Shares the same file format as ProviderStateManager in the bot.

Usage:
    provider-ctl.py get                     # show all bots status
    provider-ctl.py get neomind             # show neomind config
    provider-ctl.py set neomind litellm     # switch neomind to litellm
    provider-ctl.py set neomind direct      # switch neomind to direct
    provider-ctl.py health                  # check LiteLLM health
    provider-ctl.py health-update true      # write health status
"""

import json
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────

STATE_DIR = Path(os.getenv("NEOMIND_STATE_DIR", os.path.expanduser("~/.neomind")))
STATE_FILE = STATE_DIR / "provider-state.json"

CURRENT_SCHEMA_VERSION = 1

DEFAULT_STATE = {
    "schema_version": CURRENT_SCHEMA_VERSION,
    "updated_at": "",
    "updated_by": "system",
    "bots": {},
    "litellm": {
        "base_url": "http://localhost:4000/v1",
        "health_ok": False,
        "last_health_check": "",
    },
}

DEFAULT_BOT_CONFIG = {
    "provider_mode": "direct",
    "litellm_model": "local",
    "direct_model": "deepseek-chat",
    "thinking_model": "deepseek-reasoner",
    "moonshot_model": "moonshot-v1-128k",
    "moonshot_thinking_model": "kimi-k2.5",
    "updated_at": "",
    "updated_by": "system",
}


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Atomic File I/O ───────────────────────────────────────────────────

def read_state():
    """Read state file. Returns default state if file missing or corrupted."""
    if not STATE_FILE.exists():
        return json.loads(json.dumps(DEFAULT_STATE))
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Backup corrupted file
        bak = STATE_FILE.with_suffix(".json.bak")
        try:
            STATE_FILE.rename(bak)
        except OSError:
            pass
        return json.loads(json.dumps(DEFAULT_STATE))


def write_state(state):
    """Write state file atomically (write .tmp → rename)."""
    serialized = json.dumps(state, indent=2, ensure_ascii=False)
    # Safety: no API keys in state file
    if "api_key" in serialized.lower():
        print("ERROR: API key detected in state — refusing to write", file=sys.stderr)
        sys.exit(1)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(serialized, encoding="utf-8")
    tmp.rename(STATE_FILE)


# ── Commands ──────────────────────────────────────────────────────────

def cmd_get(args):
    """Show bot config(s)."""
    state = read_state()
    bots = state.get("bots", {})

    if args and args[0] in bots:
        bot = bots[args[0]]
        mode = bot.get("provider_mode", "?")
        updated = bot.get("updated_at", "?")
        by = bot.get("updated_by", "?")
        print(f"{args[0]}: mode={mode} (by {by} at {updated})")
        # Show model details
        print(f"  direct_model:    {bot.get('direct_model', 'deepseek-chat')}")
        print(f"  thinking_model:  {bot.get('thinking_model', 'deepseek-reasoner')}")
        print(f"  litellm_model:   {bot.get('litellm_model', 'local')}")
        print(f"  moonshot_model:  {bot.get('moonshot_model', 'moonshot-v1-128k')}")
        print(f"  moonshot_think:  {bot.get('moonshot_thinking_model', 'kimi-k2.5')}")
    else:
        if not bots:
            print("No bots registered yet.")
            return
        for name, bot in bots.items():
            mode = bot.get("provider_mode", "?")
            by = bot.get("updated_by", "?")
            print(f"{name}: mode={mode} (by {by})")

    # Show available providers (from state, written by bot)
    bot_cfg = bots.get(args[0] if args else "neomind", {})
    ap = bot_cfg.get("available_providers", [])
    if ap:
        print("\nAvailable providers (from bot):")
        for p in ap:
            print(f"  ✅ {p['name']}: {p.get('model', '?')}")
    else:
        # Fallback: check env
        print("\nConfigured providers (from env):")
        providers = []
        if os.getenv("DEEPSEEK_API_KEY"): providers.append("DeepSeek")
        if os.getenv("ZAI_API_KEY"): providers.append("z.ai (GLM)")
        if os.getenv("MOONSHOT_API_KEY"): providers.append("Moonshot (Kimi)")
        if os.getenv("LITELLM_API_KEY"): providers.append("LiteLLM (Ollama)")
        print(f"  {', '.join(providers) if providers else 'None (check .env)'}")

    # Show per-mode routing (from state, written by bot)
    mm = bot_cfg.get("mode_models", {})
    if mm:
        print("\nPer-mode model routing (from bot):")
        for mode, info in mm.items():
            prov = info.get("provider", "?")
            model = info.get("model", "?")
            think = info.get("thinking_model", "?")
            if think and think != model:
                print(f"  {mode}: {prov}/{model} (think: {think})")
            else:
                print(f"  {mode}: {prov}/{model}")
    else:
        print("\nPer-mode model routing: (bot not started yet)")

    # Also show health
    litellm = state.get("litellm", {})
    health = "healthy" if litellm.get("health_ok") else "unhealthy"
    print(f"\nlitellm: {health}")


def cmd_set(args):
    """Set provider mode for a bot."""
    if len(args) < 2:
        print("Usage: provider-ctl.py set <bot_name> <litellm|direct>", file=sys.stderr)
        sys.exit(1)

    bot_name, mode = args[0], args[1]
    if mode not in ("litellm", "direct"):
        print(f"Invalid mode: {mode}. Must be 'litellm' or 'direct'", file=sys.stderr)
        sys.exit(1)

    state = read_state()
    bots = state.setdefault("bots", {})

    if bot_name not in bots:
        bots[bot_name] = json.loads(json.dumps(DEFAULT_BOT_CONFIG))

    now = _now_iso()
    bots[bot_name]["provider_mode"] = mode
    bots[bot_name]["updated_at"] = now
    bots[bot_name]["updated_by"] = "xbar"
    state["updated_at"] = now
    state["updated_by"] = "xbar"

    write_state(state)
    print(f"✅ {bot_name} → {mode}")


def cmd_health(args):
    """Check LiteLLM health via HTTP."""
    state = read_state()
    url = state.get("litellm", {}).get("base_url", "http://localhost:4000/v1")
    # Convert API URL to health endpoint
    health_url = url.replace("/v1", "").rstrip("/") + "/health/liveliness"

    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "--max-time", "3", health_url],
            capture_output=True, text=True, timeout=5,
        )
        status_code = result.stdout.strip()
        ok = status_code == "200"
    except Exception:
        ok = False

    # Update state
    state.setdefault("litellm", {})["health_ok"] = ok
    state["litellm"]["last_health_check"] = _now_iso()
    write_state(state)

    status = "🟢 healthy" if ok else "🔴 unhealthy"
    print(f"LiteLLM: {status}")
    return ok


def cmd_health_update(args):
    """Manually set health status."""
    if not args:
        print("Usage: provider-ctl.py health-update <true|false>", file=sys.stderr)
        sys.exit(1)

    ok = args[0].lower() in ("true", "1", "yes")
    state = read_state()
    state.setdefault("litellm", {})["health_ok"] = ok
    state["litellm"]["last_health_check"] = _now_iso()
    write_state(state)
    print(f"LiteLLM health set to: {ok}")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: provider-ctl.py <get|set|health|health-update> [args...]")
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "get": cmd_get,
        "set": cmd_set,
        "health": cmd_health,
        "health-update": cmd_health_update,
    }

    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
