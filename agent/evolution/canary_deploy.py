"""Canary deployment orchestrator for zero-downtime self-evolution.

Architecture (see plans/TODO_zero_downtime_self_evolution.md):

    production bot (@neomindagent_bot)
        ↑ restart ONLY after canary passes
        │
    canary bot (@neomindagent_test_bot)  ← restarted first on every evolve
        ↑ Telethon validator hits this

Flow:
    1. EvolutionTransaction applies file edits, runs smoke + optional local canary.
    2. Caller invokes CanaryDeployer.deploy_and_verify(transaction) to:
         a. Write the transaction intent file to the canary state dir.
         b. Restart the `neomind-canary` container (not production).
         c. Wait for canary to boot and self-verify.
         d. Run the Telethon validator against the canary bot.
         e. Report PASS/FAIL to the caller.
    3. If PASS, caller invokes CanaryDeployer.promote_to_prod(transaction) to:
         a. Write the intent file to the production state dir.
         b. Restart the `neomind-telegram` container.
         c. Production's post_restart_verify re-runs (fast path — canary already proved it).
    4. If canary FAILs, caller rolls back (transaction.rollback). Production
       is NEVER touched, so users never see downtime.

This module does NOT hardcode the validator scenario list — the caller
passes in a subset name (`gate_b3`, `gate_final`, etc.) from the
validation plan at `tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py`.

No Docker SDK dependency — we shell out to `docker` / `docker compose`
from the host, so this module only runs on the host (never inside a
container). The intent-file-write happens inside the container via
`docker exec` so state lives on the canary volume.

Prerequisites (user action):
    - TELEGRAM_TEST_BOT_TOKEN in .env (fresh bot from @BotFather)
    - TG_CANARY_BOT_USERNAME in ~/.config/neomind-tester/telethon.env
    - `docker compose --profile canary up -d neomind-canary` (one-time)

Environment markers:
    NEOMIND_CANARY=1 set inside the canary container by docker-compose;
    application code can branch on this to choose isolated state paths.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


CANARY_CONTAINER = "neomind-canary"
PROD_CONTAINER = "neomind-telegram"

# Inside-container paths (bind-mounted by docker-compose).
CONTAINER_INTENT_PATH = "/data/neomind/evolution/evolution_intent.json"

# Boot wait: how long to give the canary container after `supervisorctl
# restart` before we expect /health to return 200.
CANARY_BOOT_TIMEOUT_SEC = 45

# Telethon validator wall clock — we budget ~25s per scenario average
# but let the caller override for smaller subsets.
DEFAULT_VALIDATOR_TIMEOUT_SEC = 60 * 45  # 45 min for gate_final

# Where the host-side tester lives.
TESTER_SCRIPT = Path(__file__).resolve().parents[2] / "tests" / "integration" / "telegram_tester.py"


@dataclass
class CanaryResult:
    stage: str  # "boot", "verify", "validator", "prod_deploy"
    ok: bool
    message: str
    duration_sec: float
    log_excerpt: str = ""


class CanaryDeployer:
    """Orchestrate a canary-first evolution deployment.

    Typical flow:

        from agent.evolution.transaction import EvolutionTransaction
        from agent.evolution.canary_deploy import CanaryDeployer

        with EvolutionTransaction(reason="add /foo") as txn:
            txn.apply("path/to/file.py", new_content)
            ok, msg = txn.smoke_test()
            if not ok:
                raise RuntimeError(msg)

            deployer = CanaryDeployer()
            canary_result = deployer.deploy_and_verify(
                txn, validator_subset="gate_b3",
            )
            if not canary_result.ok:
                raise RuntimeError(f"canary FAIL: {canary_result.message}")

            txn.commit()
            prod_result = deployer.promote_to_prod(txn)
            if not prod_result.ok:
                # Canary passed but prod failed — extraordinary case
                raise RuntimeError(f"prod deploy FAIL: {prod_result.message}")
    """

    def __init__(
        self,
        canary_container: str = CANARY_CONTAINER,
        prod_container: str = PROD_CONTAINER,
        python_bin: Optional[str] = None,
    ):
        self.canary_container = canary_container
        self.prod_container = prod_container
        # Validator needs Telethon — use the project venv.
        repo = Path(__file__).resolve().parents[2]
        self.python_bin = python_bin or str(repo / ".venv" / "bin" / "python")

    # ── Preflight ────────────────────────────────────────────────────

    def preflight(self) -> Tuple[bool, str]:
        """Verify the canary container exists and the validator is usable.

        Returns (ok, message). Call this before deploy_and_verify to catch
        misconfiguration cheaply instead of mid-deploy.
        """
        if not shutil.which("docker"):
            return False, "docker binary not found on PATH"

        try:
            inspect = subprocess.run(
                ["docker", "inspect", self.canary_container],
                capture_output=True, text=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            return False, "docker inspect timed out"
        if inspect.returncode != 0:
            return False, (
                f"canary container '{self.canary_container}' not running. "
                f"Start it with: docker compose --profile canary up -d {self.canary_container}"
            )

        if not TESTER_SCRIPT.exists():
            return False, f"validator script missing: {TESTER_SCRIPT}"

        if not Path(self.python_bin).exists():
            return False, f"python venv missing: {self.python_bin}"

        # Canary env token check
        env_output = subprocess.run(
            ["docker", "exec", self.canary_container, "sh", "-c", "echo $TELEGRAM_BOT_TOKEN"],
            capture_output=True, text=True, timeout=10,
        )
        token = (env_output.stdout or "").strip()
        if not token or token == "":
            return False, (
                "canary container has empty TELEGRAM_BOT_TOKEN — set "
                "TELEGRAM_TEST_BOT_TOKEN in .env and recreate the canary"
            )
        if len(token) < 20:
            return False, f"canary TELEGRAM_BOT_TOKEN looks invalid (len={len(token)})"

        return True, "preflight ok"

    # ── Canary deploy path ───────────────────────────────────────────

    def deploy_and_verify(
        self,
        transaction,
        validator_subset: str = "gate_b3",
        validator_timeout_sec: int = DEFAULT_VALIDATOR_TIMEOUT_SEC,
    ) -> CanaryResult:
        """Deploy the transaction's intent to canary and run the validator.

        Does NOT touch production. On success, caller should invoke
        `promote_to_prod(transaction)` to actually deploy to users.

        Args:
            transaction: An EvolutionTransaction whose apply() has been
                called for every file change, smoke_test has passed, and
                commit() has NOT yet been called.
            validator_subset: Scenario subset name from the validation plan
                (e.g. "gate_b3", "gate_final"). Must exist in
                tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py.
            validator_timeout_sec: Max wall time for the validator.

        Returns:
            CanaryResult with stage/ok/message/duration + log excerpt.
        """
        t0 = time.time()

        # 1. Write intent file into the canary container's state dir.
        try:
            intent_json = transaction.record.to_json()
        except Exception as e:
            return CanaryResult(
                stage="intent", ok=False,
                message=f"could not serialize transaction intent: {e}",
                duration_sec=time.time() - t0,
            )

        write_cmd = [
            "docker", "exec", self.canary_container, "sh", "-c",
            f"mkdir -p $(dirname {CONTAINER_INTENT_PATH}) && "
            f"cat > {CONTAINER_INTENT_PATH}",
        ]
        try:
            proc = subprocess.run(
                write_cmd,
                input=intent_json,
                text=True, capture_output=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            return CanaryResult(
                stage="intent", ok=False,
                message="intent write timed out",
                duration_sec=time.time() - t0,
            )
        if proc.returncode != 0:
            return CanaryResult(
                stage="intent", ok=False,
                message=f"intent write failed: {proc.stderr[:300]}",
                duration_sec=time.time() - t0,
            )

        # 2. Restart the canary agent inside the container.
        restart_t = time.time()
        try:
            restart = subprocess.run(
                ["docker", "exec", self.canary_container,
                 "supervisorctl", "restart", "neomind-agent"],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return CanaryResult(
                stage="restart", ok=False,
                message="supervisorctl restart timed out",
                duration_sec=time.time() - t0,
            )
        if restart.returncode != 0:
            return CanaryResult(
                stage="restart", ok=False,
                message=f"restart failed: {restart.stderr[:300]}",
                duration_sec=time.time() - t0,
            )
        logger.info(f"[canary] restart ok in {time.time() - restart_t:.1f}s")

        # 3. Wait for canary boot — supervisord ready + post_restart_verify.
        boot_ok, boot_msg = self._wait_for_canary_boot(CANARY_BOOT_TIMEOUT_SEC)
        if not boot_ok:
            return CanaryResult(
                stage="boot", ok=False,
                message=f"canary did not become healthy: {boot_msg}",
                duration_sec=time.time() - t0,
                log_excerpt=self._tail_canary_log(50),
            )

        # 4. Confirm post_restart_verify wrote a success marker (intent
        #    file status updated to "verified" or intent cleared).
        verify_ok, verify_msg = self._check_post_restart_verify()
        if not verify_ok:
            return CanaryResult(
                stage="verify", ok=False,
                message=f"post_restart_verify failed: {verify_msg}",
                duration_sec=time.time() - t0,
                log_excerpt=self._tail_canary_log(80),
            )

        # 5. Run the Telethon validator against the canary bot.
        val_ok, val_msg = self._run_validator(
            validator_subset, validator_timeout_sec,
        )
        if not val_ok:
            return CanaryResult(
                stage="validator", ok=False,
                message=f"validator FAIL ({validator_subset}): {val_msg}",
                duration_sec=time.time() - t0,
                log_excerpt=self._tail_canary_log(80),
            )

        return CanaryResult(
            stage="validator", ok=True,
            message=f"canary PASS ({validator_subset}): {val_msg}",
            duration_sec=time.time() - t0,
        )

    # ── Promote canary → prod ────────────────────────────────────────

    def promote_to_prod(self, transaction) -> CanaryResult:
        """After canary PASS, copy the intent file to prod and restart.

        Production's own post_restart_verify re-runs (fast path since the
        same code already validated on canary). Called only by the
        caller AFTER deploy_and_verify returned ok=True.
        """
        t0 = time.time()

        # 1. Write intent file to prod container.
        try:
            intent_json = transaction.record.to_json()
        except Exception as e:
            return CanaryResult(
                stage="prod_intent", ok=False,
                message=f"could not serialize intent for prod: {e}",
                duration_sec=time.time() - t0,
            )

        write_cmd = [
            "docker", "exec", self.prod_container, "sh", "-c",
            f"mkdir -p $(dirname {CONTAINER_INTENT_PATH}) && "
            f"cat > {CONTAINER_INTENT_PATH}",
        ]
        proc = subprocess.run(
            write_cmd, input=intent_json, text=True,
            capture_output=True, timeout=10,
        )
        if proc.returncode != 0:
            return CanaryResult(
                stage="prod_intent", ok=False,
                message=f"prod intent write failed: {proc.stderr[:300]}",
                duration_sec=time.time() - t0,
            )

        # 2. Restart prod (real users see ~5s blip here — this is the
        #    shortest window we can offer without leader-handoff).
        restart = subprocess.run(
            ["docker", "exec", self.prod_container,
             "supervisorctl", "restart", "neomind-agent"],
            capture_output=True, text=True, timeout=30,
        )
        if restart.returncode != 0:
            return CanaryResult(
                stage="prod_restart", ok=False,
                message=f"prod restart failed: {restart.stderr[:300]}",
                duration_sec=time.time() - t0,
            )

        # 3. Quick sanity wait — production /health endpoint should
        #    return 200 within 30s since canary already validated the
        #    code path.
        ok, msg = self._wait_for_prod_boot(30)
        if not ok:
            return CanaryResult(
                stage="prod_boot", ok=False,
                message=f"production failed post-restart health: {msg}",
                duration_sec=time.time() - t0,
            )

        return CanaryResult(
            stage="prod_deploy", ok=True,
            message="production restarted — new code serving users",
            duration_sec=time.time() - t0,
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _wait_for_canary_boot(self, timeout_sec: int) -> Tuple[bool, str]:
        deadline = time.time() + timeout_sec
        last_err = ""
        while time.time() < deadline:
            try:
                proc = subprocess.run(
                    ["docker", "exec", self.canary_container,
                     "python3", "-c",
                     "import urllib.request;"
                     "urllib.request.urlopen('http://localhost:18791/health', timeout=3);"
                     "print('ok')"],
                    capture_output=True, text=True, timeout=6,
                )
                if proc.returncode == 0 and "ok" in proc.stdout:
                    return True, f"healthy after {timeout_sec - (deadline - time.time()):.1f}s"
                last_err = (proc.stderr or proc.stdout)[:200]
            except subprocess.TimeoutExpired:
                last_err = "health probe timed out"
            except Exception as e:
                last_err = str(e)[:200]
            time.sleep(2)
        return False, f"timeout after {timeout_sec}s (last: {last_err})"

    def _wait_for_prod_boot(self, timeout_sec: int) -> Tuple[bool, str]:
        deadline = time.time() + timeout_sec
        last_err = ""
        while time.time() < deadline:
            try:
                proc = subprocess.run(
                    ["docker", "exec", self.prod_container,
                     "python3", "-c",
                     "import urllib.request;"
                     "urllib.request.urlopen('http://localhost:18791/health', timeout=3);"
                     "print('ok')"],
                    capture_output=True, text=True, timeout=6,
                )
                if proc.returncode == 0 and "ok" in proc.stdout:
                    return True, "healthy"
                last_err = (proc.stderr or proc.stdout)[:200]
            except Exception as e:
                last_err = str(e)[:200]
            time.sleep(2)
        return False, f"timeout (last: {last_err})"

    def _check_post_restart_verify(self) -> Tuple[bool, str]:
        """Read the intent file inside the canary — after successful
        post_restart_verify it should be either absent (cleared on pass)
        or have status != 'in_progress'.
        """
        try:
            proc = subprocess.run(
                ["docker", "exec", self.canary_container, "sh", "-c",
                 f"cat {CONTAINER_INTENT_PATH} 2>/dev/null || echo '__MISSING__'"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            return False, f"could not read intent: {e}"

        raw = (proc.stdout or "").strip()
        if raw == "__MISSING__":
            # intent cleared by post_restart_verify → success
            return True, "intent cleared by verifier"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return False, f"unparseable intent: {raw[:200]}"
        status = data.get("status", "")
        if status in ("committed", "verified"):
            return True, f"status={status}"
        if status == "post_restart_failed":
            return False, f"verifier reported failure: {data.get('error','(no detail)')}"
        # still in_progress — give the verifier a short grace window
        time.sleep(3)
        proc2 = subprocess.run(
            ["docker", "exec", self.canary_container, "sh", "-c",
             f"cat {CONTAINER_INTENT_PATH} 2>/dev/null || echo '__MISSING__'"],
            capture_output=True, text=True, timeout=10,
        )
        raw2 = (proc2.stdout or "").strip()
        if raw2 == "__MISSING__":
            return True, "intent cleared after grace period"
        return False, f"verifier stuck at status={status}"

    def _run_validator(
        self, subset: str, timeout_sec: int,
    ) -> Tuple[bool, str]:
        """Spawn the Telethon validator subprocess targeting the canary bot.

        The tester script is parameterised by NEOMIND_TESTER_TARGET=canary
        (added in this session) so it reads TG_CANARY_BOT_USERNAME instead
        of TG_BOT_USERNAME.
        """
        env = dict(os.environ)
        env["NEOMIND_TESTER_TARGET"] = "canary"
        env["NEOMIND_VALIDATOR_SUBSET"] = subset

        # The existing tester CLI doesn't support a "run subset by name"
        # flag out of the box, so we invoke it via a small inline runner.
        runner = (
            "import asyncio, importlib.util, sys\n"
            "from pathlib import Path\n"
            "plan_path = Path('tests/qa_archive/plans/2026-04-10_telegram_validation_v1.py')\n"
            "spec = importlib.util.spec_from_file_location('vplan', plan_path)\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            f"subset = mod.SUBSETS.get({subset!r}, [])\n"
            "if not subset:\n"
            f"    print(f'ERR: subset {subset!r} not found'); sys.exit(2)\n"
            "from tests.integration.telegram_tester import run_plan\n"
            "ok = asyncio.run(run_plan(subset, label='canary-validator'))\n"
            "sys.exit(0 if ok else 1)\n"
        )

        try:
            proc = subprocess.run(
                [self.python_bin, "-c", runner],
                capture_output=True, text=True, timeout=timeout_sec,
                env=env, cwd=str(Path(__file__).resolve().parents[2]),
            )
        except subprocess.TimeoutExpired:
            return False, f"validator exceeded {timeout_sec}s"

        if proc.returncode == 0:
            tail = (proc.stdout or "").strip().splitlines()[-5:]
            return True, " | ".join(tail)[:400]
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-10:]
        return False, "\n".join(tail)[:600]

    def _tail_canary_log(self, lines: int = 50) -> str:
        try:
            proc = subprocess.run(
                ["docker", "exec", self.canary_container,
                 "tail", "-n", str(lines), "/data/neomind/agent.log"],
                capture_output=True, text=True, timeout=10,
            )
            return proc.stdout[-2000:]
        except Exception:
            return ""
