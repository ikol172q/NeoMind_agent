"""Cross-mode boot smoke for NeoMind CLI — used by git pre-commit hook.

Launches each mode (chat / fin / coding), sends ONE simple message, verifies
the bot responds without crashing. ~30s per mode = ~90s total.

Skips gracefully (exit 0) if iTerm2 API is unavailable (CI / headless / etc.).
Exits 0 on success, exit 1 on hard failure (any mode crashed / timed out / no
response). Designed to be fast and reliable enough to run on every commit that
touches shared code paths.

Usage:
    .venv/bin/python tests/integration/cross_mode_boot_smoke.py

Env:
    NEOMIND_SKIP_SMOKE=1   skip entirely
"""
from __future__ import annotations
import asyncio
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tests.integration.cli_tester_iterm2 import (  # noqa: E402
    ITerm2CliTester, ITerm2APIUnavailable, ITerm2Config,
)


# Mode → (probe message, max wait seconds)
MODE_PROBES = {
    "chat":   ("你好,简单介绍下自己", 25),
    "fin":    ("AAPL 现价", 60),
    "coding": ("列出 agent/ 目录的子目录", 30),
}


async def smoke_one(mode: str, probe: str, max_wait: int) -> tuple[str, str]:
    """Returns (status, detail). status ∈ {pass, fail, skip}."""
    cfg = ITerm2Config(
        launch_cmd=(
            f"export NEOMIND_AUTO_ACCEPT=1 NEOMIND_MODE={mode} "
            f"LLM_ROUTER_BASE_URL=http://127.0.0.1:8000/v1 "
            f"LLM_ROUTER_API_KEY=dummy && "
            f".venv/bin/python main.py interactive --mode {mode}"
        ),
        cwd=str(REPO_ROOT),
        cols=120, rows=60, visible=False, boot_timeout_sec=25,
    )
    try:
        async with ITerm2CliTester(cfg) as tester:
            await tester.start_neomind()
            ok = await tester.wait_for_prompt(timeout=25)
            if not ok:
                screen = await tester.capture(lines=200)
                return "fail", f"boot timeout. tail: {screen[-300:]}"

            tester.start_recording()
            await tester.send(probe)

            # Wait for response — poll for stable content
            t0 = time.time()
            last_len = 0
            stable_since = None
            while time.time() - t0 < max_wait:
                await asyncio.sleep(1.0)
                screen = await tester.capture(lines=200)
                cur_len = len(screen)
                if cur_len == last_len and cur_len > 100:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since > 3:
                        break
                else:
                    stable_since = None
                    last_len = cur_len

            full = tester.stop_recording()

            # Check for fatal markers
            if "Traceback" in full:
                return "fail", "python traceback in output"
            if "API authentication" in full or "401" in full[-500:]:
                return "fail", "API auth error"
            if len(full) < 200:
                return "fail", f"response too short ({len(full)} chars)"
            return "pass", f"{len(full)} chars in {time.time()-t0:.0f}s"

    except ITerm2APIUnavailable as e:
        return "skip", f"iterm2 unavailable: {e}"
    except Exception as e:
        return "fail", f"{type(e).__name__}: {e}"


async def main() -> int:
    if os.environ.get("NEOMIND_SKIP_SMOKE"):
        print("[smoke] NEOMIND_SKIP_SMOKE set — skipping")
        return 0

    print("[smoke] cross-mode boot smoke starting (chat / fin / coding)")
    results = {}
    for mode, (probe, max_wait) in MODE_PROBES.items():
        print(f"[smoke] {mode}: launching...")
        t0 = time.time()
        status, detail = await smoke_one(mode, probe, max_wait)
        elapsed = time.time() - t0
        results[mode] = (status, detail, elapsed)
        emoji = {"pass": "✅", "fail": "❌", "skip": "⏭"}[status]
        print(f"[smoke]   {emoji} {mode} ({elapsed:.0f}s) — {detail[:120]}")

    # Decide exit code
    fails = [m for m, (s, _, _) in results.items() if s == "fail"]
    skips = [m for m, (s, _, _) in results.items() if s == "skip"]
    passes = [m for m, (s, _, _) in results.items() if s == "pass"]

    print()
    print(f"[smoke] PASS={len(passes)} FAIL={len(fails)} SKIP={len(skips)}")
    if fails:
        print(f"[smoke] FAILED modes: {', '.join(fails)}")
        print("[smoke] To bypass: NEOMIND_SKIP_SMOKE=1 git commit ...")
        return 1
    if not passes and skips:
        # All skipped (no iterm2) — don't block commit
        print("[smoke] all modes skipped (no iterm2), allowing commit")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
