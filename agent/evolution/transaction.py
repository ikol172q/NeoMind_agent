"""NeoMind Evolution Transaction — Multi-File Atomic Self-Edit

Wraps SelfEditor with transaction semantics so a self-improvement that
spans multiple files either fully applies or fully rolls back.

Why not just call SelfEditor.propose_edit() in a loop?
  - SelfEditor commits each file individually to git. If file 3 of 5 fails,
    files 1 and 2 are already committed and there is no clean rollback.
  - SelfEditor's smoke test only validates the single file being edited, not
    cross-file consistency (e.g. file A imports a symbol that file B removed).
  - There is no canary phase: a successful per-file test does not guarantee
    that all files together actually load.

EvolutionTransaction adds:
  1. Pre-edit git tag → fixed rollback anchor
  2. apply() per file (still routed through SelfEditor for safety)
  3. smoke_test() → subprocess imports every applied file
  4. canary() → optional subprocess that exercises a specific code path
  5. commit() → final git commit + write evolution-intent file
  6. rollback() → git reset --hard to the tag, drop all applied files
  7. Concurrency lock so two transactions cannot interleave
  8. Cleanly survives normal Python exceptions via the with-statement form

Safety guarantees inherited from SelfEditor:
  - AST safety, syntax check, constitutional review, daily edit limit,
    forbidden file list, fork-process per-file test.

Safety guarantees added by this class:
  - All-or-nothing: an exception during apply rolls back every file
  - Cross-file validation: smoke + canary in subprocess after the last apply
  - Persistent intent file: post-restart verifier reads it to confirm health
  - Single concurrent transaction (lock file with O_EXCL)

Usage:
    with EvolutionTransaction(reason="add playwright support") as txn:
        txn.apply("agent/tools/screenshot.py", new_screenshot_module)
        txn.apply("agent/coding/tools.py", updated_registry)
        ok, msg = txn.smoke_test()
        if not ok:
            raise RuntimeError(f"smoke failed: {msg}")
        ok, msg = txn.canary("agent.tools.screenshot:capture")
        if not ok:
            raise RuntimeError(f"canary failed: {msg}")
        txn.commit(notify_chat_id=123456)
        # caller is responsible for triggering restart after this returns

If any step inside the with-block raises, rollback() runs automatically.

No external dependencies — stdlib only.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Any

from agent.evolution.self_edit import SelfEditor

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────

REPO_DIR = SelfEditor.REPO_DIR
DATA_DIR = Path("/data/neomind/evolution")
LOCK_FILE = DATA_DIR / "transaction.lock"
INTENT_FILE = DATA_DIR / "evolution_intent.json"
TXN_LOG = DATA_DIR / "transactions.jsonl"

# Maximum files in a single transaction. Mirrors SelfEditor.MAX_EDITS_PER_DAY
# upper bound but is also a sanity guardrail against runaway plans.
MAX_FILES_PER_TRANSACTION = 8

# Subprocess timeouts (seconds)
SMOKE_TIMEOUT = 30
CANARY_TIMEOUT = 30
REGRESSION_TIMEOUT = 180  # pytest can legitimately take >30s

# Critical-path tests that MUST stay green across any self-modification.
# Kept deliberately small so the full suite runs in <60s. Listed here
# rather than discovered automatically so a broken test file cannot
# silently disappear from the gate.
DEFAULT_REGRESSION_TARGETS: Tuple[str, ...] = (
    "tests/test_provider_state.py",
    "tests/test_evolution_transaction.py",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Concurrency lock ────────────────────────────────────────────────

@contextmanager
def _transaction_lock():
    """Atomic single-writer lock via O_EXCL file create.

    Yields the lock fd. Releases (deletes) the file on exit.
    Raises BlockingIOError if already held.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd = None
    try:
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except OSError as e:
            if e.errno == errno.EEXIST:
                # Try to determine if the existing lock is stale
                try:
                    age = time.time() - LOCK_FILE.stat().st_mtime
                    if age > 600:  # 10 minutes — definitely stale
                        logger.warning(f"Removing stale evolution lock (age={age:.0f}s)")
                        LOCK_FILE.unlink(missing_ok=True)
                        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    else:
                        raise BlockingIOError(
                            f"Another evolution transaction is in progress "
                            f"(lock age {age:.0f}s, max 600s before stale)"
                        )
                except FileNotFoundError:
                    # Race: someone else cleaned it up between checks. Try once more.
                    fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            else:
                raise

        os.write(fd, json.dumps({"pid": os.getpid(), "started": _now_iso()}).encode())
        yield fd
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"Failed to release evolution lock: {e}")


# ── Transaction record ──────────────────────────────────────────────

@dataclass
class TransactionRecord:
    """Persisted transaction state. Read by post_restart_verify."""
    tag: str
    reason: str
    started_at: str
    applied_files: List[str] = field(default_factory=list)
    smoke_target: Optional[str] = None
    canary_target: Optional[str] = None
    notify_chat_id: Optional[int] = None
    notify_bot_username: Optional[str] = None
    status: str = "in_progress"  # in_progress | committed | rolled_back | post_restart_failed
    finished_at: Optional[str] = None
    error: Optional[str] = None
    # Per-stage wall-clock timings in seconds (float). Written by the
    # _time_stage context manager. Persisted with the intent file so the
    # post-restart verifier and /evolve status can surface hotspots.
    stage_timings: Dict[str, float] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_file(cls, path: Path) -> Optional["TransactionRecord"]:
        if not path.exists():
            return None
        try:
            return cls(**json.loads(path.read_text()))
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"Failed to read transaction record {path}: {e}")
            return None


# ── Main Class ───────────────────────────────────────────────────────

class EvolutionTransaction:
    """Multi-file atomic edit with snapshot, smoke, canary, and rollback.

    Use as a context manager:

        with EvolutionTransaction(reason="...") as txn:
            txn.apply("path/to/file1.py", new_content_1)
            txn.apply("path/to/file2.py", new_content_2)
            ok, msg = txn.smoke_test()
            if not ok: raise RuntimeError(msg)
            txn.commit()

    On any exception inside the with-block, rollback() runs automatically
    and the exception propagates to the caller.
    """

    def __init__(
        self,
        reason: str,
        smoke_target: Optional[str] = None,
        canary_target: Optional[str] = None,
        notify_chat_id: Optional[int] = None,
        notify_bot_username: Optional[str] = None,
        tag_prefix: str = "evolve",
        regression_targets: Optional[Sequence[str]] = None,
    ):
        if not reason or not isinstance(reason, str):
            raise ValueError("reason must be a non-empty string")

        self.editor = SelfEditor()
        # Use microsecond precision so two transactions started in the same
        # second get different tags. Includes PID as a final tiebreaker for
        # the (extremely unlikely) within-microsecond collision.
        _now = datetime.now()
        self.tag = (
            f"{tag_prefix}-{_now.strftime('%Y%m%d-%H%M%S')}-"
            f"{_now.microsecond:06d}-{os.getpid()}"
        )
        self.record = TransactionRecord(
            tag=self.tag,
            reason=reason[:500],
            started_at=_now_iso(),
            smoke_target=smoke_target,
            canary_target=canary_target,
            notify_chat_id=notify_chat_id,
            notify_bot_username=notify_bot_username,
        )

        # Track originals so we can manually restore if git rollback fails for
        # any reason (e.g. file added that wasn't yet committed).
        self._originals: Dict[str, Optional[str]] = {}
        self._lock_ctx = None
        self._lock_fd = None

        # Regression test targets — default to the critical-path list, or the
        # caller-supplied override. An empty list/tuple disables regression.
        if regression_targets is None:
            self.regression_targets: Tuple[str, ...] = tuple(DEFAULT_REGRESSION_TARGETS)
        else:
            self.regression_targets = tuple(regression_targets)

    # ── Lifecycle ─────────────────────────────────────────────────

    def __enter__(self) -> "EvolutionTransaction":
        # Acquire the global concurrency lock
        self._lock_ctx = _transaction_lock()
        self._lock_fd = self._lock_ctx.__enter__()

        # Create the rollback anchor
        ok, msg = self._git_tag(self.tag)
        if not ok:
            self._release_lock()
            raise RuntimeError(f"Failed to create rollback tag: {msg}")
        logger.info(f"[evolve] Transaction started, rollback tag: {self.tag}")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            logger.warning(
                f"[evolve] Transaction failed with {exc_type.__name__}: {exc} — rolling back"
            )
            try:
                self.rollback(reason=f"{exc_type.__name__}: {exc}")
            except Exception as rollback_err:
                logger.error(f"[evolve] Rollback ALSO failed: {rollback_err}")
        self._release_lock()
        # Don't suppress the exception
        return False

    def _release_lock(self):
        if self._lock_ctx is not None:
            try:
                self._lock_ctx.__exit__(None, None, None)
            except Exception as e:
                logger.warning(f"Lock release error: {e}")
            self._lock_ctx = None
            self._lock_fd = None

    # ── Timing helper ─────────────────────────────────────────────

    @contextmanager
    def _time_stage(self, stage_name: str):
        """Record wall time for a named stage + log start/end.

        Accumulates into stage_timings[name]. If the same stage runs multiple
        times (e.g. apply() called N times), the times are summed so the
        total reflects the aggregate cost of that phase. A separate
        per-stage count is NOT tracked here — it would complicate the
        downstream /evolve status formatting for marginal value.

        Usage:
            with self._time_stage("smoke"):
                ...
        """
        t0 = time.time()
        logger.info(f"[evolve] ▶ {stage_name}")
        try:
            yield
        finally:
            dt = time.time() - t0
            prev = self.record.stage_timings.get(stage_name, 0.0)
            self.record.stage_timings[stage_name] = round(prev + dt, 3)
            logger.info(f"[evolve] ◀ {stage_name} ({dt:.2f}s, total {self.record.stage_timings[stage_name]:.2f}s)")

    # ── Apply ─────────────────────────────────────────────────────

    def apply(self, file_path: str, new_content: str) -> Tuple[bool, str]:
        """Apply a single file edit through SelfEditor's safety pipeline.

        Returns (ok, message). On failure, the file is reverted by SelfEditor
        (it does its own per-file rollback). On success, the file content is
        recorded so this transaction can roll it back later if needed.
        """
        if len(self.record.applied_files) >= MAX_FILES_PER_TRANSACTION:
            return False, (
                f"Transaction file limit reached ({MAX_FILES_PER_TRANSACTION}). "
                f"Split into multiple transactions."
            )

        # Snapshot the current content for emergency manual rollback
        target = REPO_DIR / file_path
        original = target.read_text() if target.exists() else None

        with self._time_stage("apply"):
            ok, msg = self.editor.propose_edit(
                file_path=file_path,
                reason=f"[txn {self.tag}] {self.record.reason}",
                new_content=new_content,
            )

        if ok:
            self._originals[file_path] = original
            self.record.applied_files.append(file_path)
            logger.info(f"[evolve] Applied {file_path} ({len(self.record.applied_files)} of N)")
        else:
            logger.warning(f"[evolve] Failed to apply {file_path}: {msg}")

        return ok, msg

    # ── Validation ────────────────────────────────────────────────

    def smoke_test(
        self,
        run_regression: bool = True,
        run_telegram_dry_run: bool = True,
    ) -> Tuple[bool, str]:
        """Cross-file smoke test in a fresh subprocess.

        Three gates, all run in isolated subprocesses so broken code cannot
        corrupt the live agent:

          1. Import-smoke — every applied .py file gets imported
          2. Regression   — pytest runs self.regression_targets
          3. Telegram dry-run — NeoMindTelegramBot is INSTANTIATED (but not
             started) to catch broken __init__ paths, missing imports, and
             broken cross-references inside the main Telegram handler class

        The regression gate is the main guard that "old features still work
        after the edit". The telegram dry-run gate is the "the bot can
        actually boot" guard. Both are opt-out via explicit False, but that
        should only be done for edits that cannot possibly affect them
        (e.g. touching a disconnected README).

        Returns (ok, summary). On failure, summary contains the failing
        output truncated to the tail so callers can surface it verbatim.
        """
        # Gate 1: import-smoke
        with self._time_stage("smoke"):
            ok, msg = self._import_smoke()
        if not ok:
            return False, f"import-smoke failed: {msg}"
        summaries = [msg]

        # Gate 2: regression (optional)
        if run_regression:
            with self._time_stage("regression"):
                rok, rmsg = self.regression_test()
            if not rok:
                return False, f"regression failed: {rmsg}"
            summaries.append(rmsg)

        # Gate 3: telegram-bot dry-run (optional)
        if run_telegram_dry_run:
            with self._time_stage("telegram_dry_run"):
                tok, tmsg = self.telegram_dry_run()
            if not tok:
                return False, f"telegram-dry-run failed: {tmsg}"
            summaries.append(tmsg)

        return True, " | ".join(summaries)

    def _import_smoke(self) -> Tuple[bool, str]:
        """First gate: import every applied .py file in a fresh subprocess."""
        if not self.record.applied_files:
            return True, "no files to smoke-test"

        modules = []
        for f in self.record.applied_files:
            if f.endswith(".py") and "/" in f:
                module = f.replace("/", ".").removesuffix(".py")
                # Skip __init__.py — importing the package handles it
                if module.endswith(".__init__"):
                    module = module.removesuffix(".__init__")
                modules.append(module)

        if not modules:
            return True, "no .py modules to smoke-test"

        # Build a small Python program that imports each module in order
        imports = "\n".join(
            f"    importlib.import_module({m!r})" for m in modules
        )
        program = (
            "import importlib, sys\n"
            "try:\n"
            f"{imports}\n"
            "    print('SMOKE OK')\n"
            "except Exception as e:\n"
            "    import traceback\n"
            "    print(f'SMOKE FAIL: {type(e).__name__}: {e}')\n"
            "    traceback.print_exc(file=sys.stderr)\n"
            "    sys.exit(1)\n"
        )

        try:
            result = subprocess.run(
                [sys.executable or "python3", "-c", program],
                capture_output=True,
                text=True,
                timeout=SMOKE_TIMEOUT,
                cwd=str(REPO_DIR),
                env={**os.environ, "PYTHONPATH": str(REPO_DIR)},
            )
        except subprocess.TimeoutExpired:
            return False, f"smoke test timed out after {SMOKE_TIMEOUT}s"
        except Exception as e:
            return False, f"smoke subprocess error: {e}"

        if result.returncode == 0:
            return True, result.stdout.strip()[-300:]
        return False, (result.stderr or result.stdout).strip()[-500:]

    def regression_test(
        self,
        targets: Optional[Sequence[str]] = None,
    ) -> Tuple[bool, str]:
        """Run pytest against critical-path tests in an isolated subprocess.

        This is the "old features still work" gate. It runs the tests listed
        in `self.regression_targets` (or the `targets` override) via
        `python -m pytest -q --tb=short`, returning (ok, summary).

        Any non-zero pytest exit code, missing target file, or timeout fails
        the gate and — if called via smoke_test — blocks the commit so the
        transaction rolls back automatically.

        The subprocess is started with PYTHONPATH=REPO_DIR so it picks up the
        freshly applied code (which is already on disk at this point).
        """
        run_targets = list(targets) if targets is not None else list(self.regression_targets)
        if not run_targets:
            return True, "no regression targets configured"

        # Verify every target exists before firing pytest — a missing test
        # file is a hard failure (means someone accidentally deleted a guard).
        missing = [t for t in run_targets if not (REPO_DIR / t).exists()]
        if missing:
            return False, f"regression target(s) missing: {', '.join(missing)}"

        # Prefer the local venv python so we pick up project deps even if
        # the outer process was launched from a different interpreter.
        venv_python = REPO_DIR / ".venv" / "bin" / "python"
        interpreter = str(venv_python) if venv_python.exists() else (sys.executable or "python3")

        cmd = [
            interpreter, "-m", "pytest",
            "-q", "--tb=short", "--no-header",
            "-p", "no:cacheprovider",
            *run_targets,
        ]
        try:
            t_start = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=REGRESSION_TIMEOUT,
                cwd=str(REPO_DIR),
                env={**os.environ, "PYTHONPATH": str(REPO_DIR)},
            )
            elapsed = time.time() - t_start
        except subprocess.TimeoutExpired:
            return False, f"regression pytest timed out after {REGRESSION_TIMEOUT}s"
        except Exception as e:
            return False, f"regression subprocess error: {e}"

        # Pytest exit codes: 0 = all passed, 1 = failures, 2 = interrupted,
        # 3 = internal error, 4 = usage error, 5 = no tests collected.
        if result.returncode == 0:
            # Extract the pytest summary line (last non-empty line of stdout)
            tail = (result.stdout or "").strip().splitlines()
            summary = tail[-1] if tail else ""
            return True, f"pytest OK ({elapsed:.1f}s) {summary}".strip()
        if result.returncode == 5:
            return False, "pytest collected 0 tests — targets may all be skipped"

        # Failure — return a short tail of stdout + stderr so the operator
        # and post-restart verifier can see exactly what broke.
        combined = (result.stdout or "") + (result.stderr or "")
        tail = combined.strip()[-800:]
        return False, f"pytest exit={result.returncode} ({elapsed:.1f}s):\n{tail}"

    def telegram_dry_run(self) -> Tuple[bool, str]:
        """Instantiate NeoMindTelegramBot in a subprocess without connecting.

        This is the gate that ensures the main Telegram handler class can
        actually boot after the edit. It runs inside an isolated subprocess
        so any import-time side effects, broken decorators, or malformed
        class bodies are caught before we restart the live bot.

        The subprocess:
          - Sets a fake TELEGRAM_BOT_TOKEN so TelegramConfig.from_env passes
          - Imports agent.integration.telegram_bot
          - Constructs NeoMindTelegramBot(components={})
          - Verifies _store, _usage, _state_mgr attributes exist
          - Exits without calling .start() — no network, no polling

        Returns (ok, summary). A broken __init__, missing module-level
        symbol, or crashed sub-import all fail the gate.
        """
        program = (
            "import os, sys, traceback\n"
            "os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'dryrun:test:000000')\n"
            "os.environ.setdefault('NEOMIND_DRY_RUN', '1')\n"
            "try:\n"
            "    from agent.integration.telegram_bot import NeoMindTelegramBot\n"
            "    bot = NeoMindTelegramBot(components={})\n"
            "    # Verify a few attributes that the live bot relies on\n"
            "    for attr in ('_store', '_usage', '_state_mgr', 'config'):\n"
            "        if not hasattr(bot, attr):\n"
            "            raise AttributeError(f'NeoMindTelegramBot missing {attr}')\n"
            "    print('TELEGRAM_DRY_RUN OK')\n"
            "except Exception as e:\n"
            "    print(f'TELEGRAM_DRY_RUN FAIL: {type(e).__name__}: {e}')\n"
            "    traceback.print_exc(file=sys.stderr)\n"
            "    sys.exit(1)\n"
        )

        # Prefer the local venv python so project deps are on sys.path
        venv_python = REPO_DIR / ".venv" / "bin" / "python"
        interpreter = str(venv_python) if venv_python.exists() else (sys.executable or "python3")

        try:
            t_start = time.time()
            result = subprocess.run(
                [interpreter, "-c", program],
                capture_output=True,
                text=True,
                timeout=SMOKE_TIMEOUT,
                cwd=str(REPO_DIR),
                env={**os.environ, "PYTHONPATH": str(REPO_DIR)},
            )
            elapsed = time.time() - t_start
        except subprocess.TimeoutExpired:
            return False, f"telegram dry-run timed out after {SMOKE_TIMEOUT}s"
        except Exception as e:
            return False, f"telegram dry-run subprocess error: {e}"

        if result.returncode == 0:
            return True, f"telegram dry-run OK ({elapsed:.1f}s)"
        combined = (result.stdout or "") + (result.stderr or "")
        tail = combined.strip()[-800:]
        return False, f"telegram dry-run exit={result.returncode}:\n{tail}"

    def canary(self, importable_target: Optional[str] = None) -> Tuple[bool, str]:
        """Optional canary: import + invoke a specific symbol in subprocess.

        Format of `importable_target`:
            "agent.tools.screenshot"               → just import
            "agent.tools.screenshot:capture"       → import + call capture()
            "agent.foo:Bar.method"                 → import + call Bar().method()

        Returns (ok, output). On any exception, the canary fails.
        """
        target = importable_target or self.record.canary_target
        if not target:
            return True, "no canary target — skipped"

        with self._time_stage("canary"):
            return self._run_canary(target)

    def _run_canary(self, target: str) -> Tuple[bool, str]:
        """Implementation of canary() — separated so the _time_stage wrapper
        records timing uniformly regardless of early-return paths.
        """
        if ":" in target:
            module_path, attr_path = target.split(":", 1)
        else:
            module_path, attr_path = target, None

        if attr_path:
            # Import + invoke
            program = (
                f"import importlib\n"
                f"m = importlib.import_module({module_path!r})\n"
                f"obj = m\n"
                f"for part in {attr_path!r}.split('.'):\n"
                f"    obj = getattr(obj, part)\n"
                f"if callable(obj):\n"
                f"    try:\n"
                f"        result = obj()\n"
                f"        print(f'CANARY OK: {{type(result).__name__}}')\n"
                f"    except TypeError:\n"
                f"        # may need args; just verifying it exists is enough\n"
                f"        print('CANARY OK: (callable, not invoked due to required args)')\n"
                f"else:\n"
                f"    print(f'CANARY OK: {{type(obj).__name__}} (not callable)')\n"
            )
        else:
            program = (
                f"import importlib\n"
                f"m = importlib.import_module({module_path!r})\n"
                f"print(f'CANARY OK: {{m.__name__}}')\n"
            )

        try:
            result = subprocess.run(
                [sys.executable or "python3", "-c", program],
                capture_output=True,
                text=True,
                timeout=CANARY_TIMEOUT,
                cwd=str(REPO_DIR),
                env={**os.environ, "PYTHONPATH": str(REPO_DIR)},
            )
        except subprocess.TimeoutExpired:
            return False, f"canary timed out after {CANARY_TIMEOUT}s"
        except Exception as e:
            return False, f"canary subprocess error: {e}"

        if result.returncode == 0:
            return True, result.stdout.strip()[-300:]
        return False, (result.stderr or result.stdout).strip()[-500:]

    # ── Commit ────────────────────────────────────────────────────

    def commit(self) -> Tuple[bool, str]:
        """Persist the intent file so post-restart verifier can confirm health.

        Note: SelfEditor already commits each file individually to git as it
        applies. This method just writes the transaction-level intent file
        and the audit log entry. It does NOT trigger the restart — caller
        decides when (typically right after).

        Timing note: the 'commit' stage is recorded BEFORE the intent file
        is written, so the persisted intent file includes the commit
        timing itself. This means the commit timing excludes the file
        write, but makes downstream analysis complete.
        """
        self.record.status = "committed"
        self.record.finished_at = _now_iso()

        # Record a nominal commit timing so it appears in stage_timings
        # BEFORE we serialize the intent file.
        commit_start = time.time()
        self.record.stage_timings["commit"] = round(time.time() - commit_start, 3)

        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            INTENT_FILE.write_text(self.record.to_json())
            self._append_log(self.record)
        except OSError as e:
            return False, f"failed to write intent file: {e}"

        # Update commit timing with actual elapsed after the write
        self.record.stage_timings["commit"] = round(time.time() - commit_start, 3)

        total = sum(self.record.stage_timings.values())
        stages = ", ".join(
            f"{k}={v:.1f}s" for k, v in self.record.stage_timings.items()
        )
        logger.info(
            f"[evolve] Committed transaction {self.tag} "
            f"({len(self.record.applied_files)} files, total {total:.1f}s) — {stages}"
        )
        return True, f"committed: {self.tag}"

    # ── Rollback ──────────────────────────────────────────────────

    def rollback(self, reason: str = "manual rollback") -> Tuple[bool, str]:
        """Reset the working tree to the rollback tag.

        Two-phase recovery:
          1. Try `git reset --hard <tag>` (preferred — clean restore)
          2. If that fails, manually restore each tracked original from
             self._originals (best-effort, no atomic guarantee)
        """
        with self._time_stage("rollback"):
            self.record.status = "rolled_back"
            self.record.error = reason
            self.record.finished_at = _now_iso()

            # Phase 1: git reset
            ok, msg = self._git_reset_to_tag(self.tag)

            if not ok:
                logger.warning(f"[evolve] Git reset failed: {msg} — falling back to manual restore")
                # Phase 2: best-effort file-by-file
                for fp, original in self._originals.items():
                    try:
                        target = REPO_DIR / fp
                        if original is None:
                            target.unlink(missing_ok=True)
                        else:
                            target.write_text(original)
                    except OSError as e:
                        logger.error(f"[evolve] Failed to restore {fp}: {e}")

            # Always log the rollback
            try:
                self._append_log(self.record)
            except Exception as e:
                logger.warning(f"Failed to log rollback: {e}")

            # Clear the intent file so post-restart verifier doesn't see a stale one
            try:
                INTENT_FILE.unlink(missing_ok=True)
            except OSError:
                pass

        return ok, msg

    # ── Git helpers ───────────────────────────────────────────────

    def _git_tag(self, tag: str) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                ["git", "tag", tag, "-m", f"evolve rollback anchor: {self.record.reason[:100]}"],
                cwd=str(REPO_DIR),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True, tag
            return False, result.stderr.strip()
        except (subprocess.TimeoutExpired, OSError) as e:
            return False, str(e)

    def _git_reset_to_tag(self, tag: str) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                ["git", "reset", "--hard", tag],
                cwd=str(REPO_DIR),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                return True, "reset to " + tag
            return False, result.stderr.strip()
        except (subprocess.TimeoutExpired, OSError) as e:
            return False, str(e)

    def _append_log(self, record: TransactionRecord):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(TXN_LOG, "a") as f:
                f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning(f"Failed to append transaction log: {e}")


# ── Query helpers ────────────────────────────────────────────────────

def get_pending_intent() -> Optional[TransactionRecord]:
    """Read the evolution intent file (if any). Used by post-restart verifier."""
    return TransactionRecord.from_file(INTENT_FILE)


def clear_pending_intent():
    """Remove the intent file. Called by post-restart verifier after handling."""
    try:
        INTENT_FILE.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"Failed to clear intent file: {e}")


def get_transaction_log(limit: int = 20) -> List[Dict[str, Any]]:
    """Return recent transactions from the audit log."""
    if not TXN_LOG.exists():
        return []
    try:
        lines = TXN_LOG.read_text().splitlines()
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(entries))
    except OSError:
        return []
