"""macOS launchd autostart installer for the NeoMind fin dashboard.

Set-and-forget solution — install once with::

    python scripts/neomind_fin_autostart.py install

After install, the fin dashboard (agent/finance/dashboard_server.py)
starts automatically every time you log in and listens on
http://127.0.0.1:8001. No terminal needed. Survives reboots. Logs land
at ``~/Library/Logs/neomind-fin-dashboard.log``.

Commands:
    install     Render plist, write to ~/Library/LaunchAgents/,
                load via launchctl, open browser.
    uninstall   launchctl unload + remove the plist.
    status      Show whether it's loaded + listening.
    render      Print the plist to stdout (debug / dry-run).

Why launchd instead of a background Python daemon: launchd is the
native macOS service manager. It restarts the process if it crashes,
handles session lifecycle (starts at login, stops at logout), and
keeps logs in the standard Mac location. A hand-rolled PID-file
daemon would reimplement all that badly.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LABEL = "com.neomind.fin-dashboard"
DEFAULT_URL = "http://127.0.0.1:8001"

# Isolated venv used by launchd. Lives OUTSIDE ~/Desktop so its own
# site-packages are readable by non-FDA processes, and built with a
# non-Apple-signed python (Homebrew) so FDA grants actually apply
# to the binary. The repo source on Desktop still requires FDA on the
# launcher python; see _HOMEBREW_PYTHON_CANDIDATES below.
ISOLATED_VENV_DIR = Path.home() / ".neomind_fin_venv"

# Apple-signed python binaries CANNOT be granted Full Disk Access
# (macOS rejects the grant on system binaries). The isolated venv
# must be built from one of these non-system candidates.
_HOMEBREW_PYTHON_CANDIDATES = [
    "/opt/homebrew/bin/python3",                       # Apple Silicon
    "/opt/homebrew/opt/python@3.12/bin/python3.12",
    "/opt/homebrew/opt/python@3.11/bin/python3.11",
    "/usr/local/bin/python3",                          # Intel Homebrew
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",  # python.org
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
]

# System binaries that WILL be rejected for FDA grants — used to warn
# early if ``sys.executable`` resolves here.
_SYSTEM_PYTHON_PREFIXES = (
    "/Library/Developer/CommandLineTools/",
    "/Applications/Xcode.app/",
    "/usr/bin/",
    "/System/",
)

# macOS directories gated by TCC (Transparency, Consent, Control).
# Processes spawned by launchd do NOT inherit the user's interactive
# Terminal/Finder grant for these locations — they get silent EPERM
# unless the binary has been explicitly granted Full Disk Access.
# Symptom: `Operation not permitted` on reading .venv/pyvenv.cfg or
# any repo file when the repo lives inside one of these dirs.
_TCC_PROTECTED_DIRS = ("Desktop", "Documents", "Downloads")


def _is_tcc_protected_path(path: Path) -> bool:
    home = Path.home().resolve()
    try:
        rel = path.resolve().relative_to(home)
    except ValueError:
        return False
    return len(rel.parts) > 0 and rel.parts[0] in _TCC_PROTECTED_DIRS


def repo_root() -> Path:
    """Absolute path to the NeoMind_agent repo this script lives in."""
    return Path(__file__).resolve().parent.parent


def default_python_bin() -> Path:
    """Absolute path to the launcher python used by the plist.

    Returns the isolated venv's python if it already exists (the
    expected state after ``bootstrap_isolated_venv`` has run). Falls
    back to the repo's ``.venv/bin/python`` and finally
    ``sys.executable`` — both of which may fail the TCC grant check
    if they resolve to an Apple-signed system binary.
    """
    isolated = ISOLATED_VENV_DIR / "bin" / "python"
    if isolated.exists():
        return isolated
    venv_py = repo_root() / ".venv" / "bin" / "python"
    if venv_py.exists():
        return venv_py
    return Path(sys.executable)


def find_homebrew_python() -> Optional[Path]:
    """Return the first non-system python on disk, or None. We scan a
    hard-coded list instead of $PATH so a user who just
    ``brew install python`` will be found even if their shell rc hasn't
    been reloaded."""
    for candidate in _HOMEBREW_PYTHON_CANDIDATES:
        p = Path(candidate)
        if p.exists() and os.access(p, os.X_OK):
            # Resolve symlinks so we return the concrete binary
            return p.resolve()
    return None


def _is_system_python(py: Path) -> bool:
    """True if ``py`` resolves under an Apple-signed system location
    where TCC refuses to honor user FDA grants."""
    try:
        real = str(py.resolve())
    except OSError:
        real = str(py)
    return real.startswith(_SYSTEM_PYTHON_PREFIXES)


def bootstrap_isolated_venv(
    base_python: Optional[Path] = None,
    *,
    force: bool = False,
    verbose: bool = True,
) -> Path:
    """Create (or reuse) the ~/.neomind_fin_venv virtualenv, built
    with a non-system python, and pip-install the repo in editable
    mode so ``import agent.finance.dashboard_server`` works.

    Returns the absolute path to the venv's python binary.

    Raises ``RuntimeError`` if no non-system python is available and
    ``base_python`` was not supplied.
    """
    if base_python is None:
        base_python = find_homebrew_python()
    if base_python is None:
        raise RuntimeError(
            "no non-system python found. Install one via "
            "`brew install python` and re-run this command."
        )

    venv_py = ISOLATED_VENV_DIR / "bin" / "python"
    if venv_py.exists() and not force:
        if verbose:
            print(f"(reusing existing {ISOLATED_VENV_DIR})")
    else:
        if verbose:
            print(f"creating isolated venv at {ISOLATED_VENV_DIR}")
            print(f"  base python: {base_python}")
        if ISOLATED_VENV_DIR.exists() and force:
            shutil.rmtree(ISOLATED_VENV_DIR)
        _run(
            [str(base_python), "-m", "venv", str(ISOLATED_VENV_DIR)],
            check=True,
        )

    # Always (re)install the repo + FastAPI deps — fast no-op when
    # already installed, and picks up new optional deps if added.
    if verbose:
        print("installing repo (editable) + fastapi + uvicorn...")
    pip = ISOLATED_VENV_DIR / "bin" / "pip"
    _run(
        [
            str(pip), "install", "--quiet", "--upgrade", "pip",
        ],
        check=False,
    )
    _run(
        [
            str(pip), "install", "--quiet",
            "-e", str(repo_root()),
            "fastapi", "uvicorn",
        ],
        check=True,
    )
    if verbose:
        print("isolated venv ready")
    return venv_py


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path() -> Path:
    return launch_agents_dir() / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "neomind-fin-dashboard.log"


def build_plist_dict(
    repo: Path,
    python_bin: Path,
    log: Path,
) -> Dict:
    """Construct the plist payload as a Python dict.

    Kept separate from rendering so tests can inspect it without
    parsing XML."""
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(python_bin),
            "-m",
            "agent.finance.dashboard_server",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
        ],
        "WorkingDirectory": str(repo),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "PYTHONUNBUFFERED": "1",
            # PYTHONPATH so the isolated venv's python can import
            # agent.finance.* even if the editable pip install .pth
            # file is missing for any reason. Belt-and-braces.
            "PYTHONPATH": str(repo),
        },
        # RunAtLoad: launch immediately when `launchctl load` runs AND
        # every time the user logs in thereafter.
        "RunAtLoad": True,
        # KeepAlive with SuccessfulExit=false: restart if the process
        # crashes, but do NOT restart if it exits cleanly (so
        # `launchctl unload` actually stops it).
        "KeepAlive": {"SuccessfulExit": False},
        # Nice = +5 so the dashboard never steals priority from the
        # user's foreground apps.
        "Nice": 5,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
        "ProcessType": "Background",
    }


def render_plist(
    repo: Path | None = None,
    python_bin: Path | None = None,
    log: Path | None = None,
) -> bytes:
    """Return the plist as XML bytes (plistlib format=FMT_XML)."""
    payload = build_plist_dict(
        repo=repo or repo_root(),
        python_bin=python_bin or default_python_bin(),
        log=log or log_path(),
    )
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False)


# ── Command helpers ────────────────────────────────────────────────


def _run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _launchctl_loaded() -> bool:
    try:
        out = _run(["launchctl", "list"], check=False).stdout
    except FileNotFoundError:
        return False
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[-1] == LABEL:
            return True
    return False


def _port_listening(port: int = 8001) -> bool:
    try:
        out = _run(["lsof", "-i", f"tcp:{port}", "-sTCP:LISTEN"], check=False).stdout
    except FileNotFoundError:
        return False
    return bool(out.strip())


def _scan_log_for_tcc_error(log: Path, since_ts: float) -> bool:
    """Return True if the log has a 'Operation not permitted' error
    on the .venv or any repo file that appeared after ``since_ts``.
    Used to detect macOS TCC denial after launchd first loads the job.
    """
    if not log.exists():
        return False
    try:
        if log.stat().st_mtime < since_ts:
            return False
        tail = log.read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        return False
    return (
        "Operation not permitted" in tail
        or "PermissionError" in tail
    )


def _print_tcc_help(repo: Path, py: Path) -> None:
    protected = _is_tcc_protected_path(repo)
    print()
    print("─" * 70)
    print("ERROR: the dashboard process was denied filesystem access.")
    print("─" * 70)
    if protected:
        print(
            f"Your repo lives inside a macOS TCC-protected folder:\n"
            f"  {repo}"
        )
        print(
            "\nmacOS silently blocks launchd-spawned processes from reading\n"
            "~/Desktop, ~/Documents, and ~/Downloads unless the binary has\n"
            "been explicitly granted Full Disk Access."
        )
    print()
    print("Fix (one-time, ~30 seconds):")
    print("  1. Open System Settings → Privacy & Security → Full Disk Access")
    print("  2. Click the '+' button, press ⌘⇧G, paste this path, click Open:")
    print(f"       {py}")
    print("  3. Toggle it ON (add if not already listed)")
    print("  4. Re-run: python scripts/neomind_fin_autostart.py install")
    print()
    print("Shortcut — open the right pane directly:")
    print("  python scripts/neomind_fin_autostart.py grant-fda")
    print()
    print("Alternative: move the repo out of ~/Desktop (e.g. to ~/code/)")
    print("─" * 70)


def cmd_install(args: argparse.Namespace) -> int:
    repo = repo_root()
    log = log_path()

    # Bootstrap (or reuse) the isolated Homebrew-python venv at
    # ~/.neomind_fin_venv. This is the launcher binary the plist
    # will point at. Built from a non-system python so FDA grants
    # actually stick — Apple-signed system pythons silently reject
    # the grant.
    try:
        py = bootstrap_isolated_venv()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "\nThe fin dashboard launchd job needs a non-Apple-signed\n"
            "python because macOS refuses Full Disk Access grants on\n"
            "system binaries. Install Homebrew python once:\n"
            "    brew install python\n"
            "then re-run:\n"
            "    python scripts/neomind_fin_autostart.py install",
            file=sys.stderr,
        )
        return 2

    # Sanity check — the isolated venv's python should never resolve
    # to a system binary, but assert it so a broken Homebrew install
    # doesn't produce a plist that will fail silently.
    if _is_system_python(py):
        print(
            f"ERROR: {py} resolves to an Apple-signed system binary",
            file=sys.stderr,
        )
        print(
            "macOS will reject FDA grants on it. Rebuild with:\n"
            "  python scripts/neomind_fin_autostart.py bootstrap --force",
            file=sys.stderr,
        )
        return 2

    # Import probe against the isolated venv's python
    probe = _run(
        [
            str(py),
            "-c",
            "from agent.finance.dashboard_server import create_app; "
            "create_app()",
        ],
        check=False,
    )
    if probe.returncode != 0:
        print(
            "ERROR: agent.finance.dashboard_server failed to import "
            "under the isolated venv.",
            file=sys.stderr,
        )
        print(probe.stderr, file=sys.stderr)
        return 2

    # Warn if repo lives in a TCC-protected folder — the isolated venv
    # python still needs FDA to read the source files from Desktop,
    # even though its own site-packages live safely under ~/.
    if _is_tcc_protected_path(repo):
        print(
            f"⚠  repo is inside a TCC-protected folder ({repo.parts[-2]}/…)"
        )
        print(
            f"   the launcher binary must have Full Disk Access so it"
        )
        print(
            f"   can read your source files:"
        )
        print(f"     {py}")
        print()

    launch_agents_dir().mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)

    plist = plist_path()
    plist_bytes = render_plist(repo=repo, python_bin=py, log=log)

    # If already loaded, unload first so we pick up any plist changes.
    if _launchctl_loaded():
        _run(["launchctl", "unload", str(plist)], check=False)

    plist.write_bytes(plist_bytes)
    print(f"wrote {plist}")

    load_ts = time.time()
    load = _run(["launchctl", "load", str(plist)], check=False)
    if load.returncode != 0:
        print("launchctl load failed:", file=sys.stderr)
        print(load.stderr, file=sys.stderr)
        return 3

    print(f"loaded  {LABEL}")
    print(f"log     {log}")

    # Poll for up to 4s: either the port starts listening (success) or
    # launchd crash-loops the job and the log shows a TCC permission
    # error. We detect the latter so we can give the user clear help
    # instead of leaving them to discover the failure themselves.
    deadline = time.monotonic() + 4.0
    listening = False
    tcc_denied = False
    while time.monotonic() < deadline:
        time.sleep(0.4)
        if _port_listening():
            listening = True
            break
        if _scan_log_for_tcc_error(log, load_ts):
            tcc_denied = True
            break

    if tcc_denied:
        # Unload the broken job so it doesn't keep crash-looping
        _run(["launchctl", "unload", str(plist)], check=False)
        _print_tcc_help(repo, py)
        return 4

    if not listening:
        print()
        print("⚠  dashboard did not start listening on 8001 within 4s")
        print(f"   check the log: tail {log}")
        return 5

    print()
    print(f"◇ neomind fin dashboard is now running at {DEFAULT_URL}")
    print("   it will restart automatically at every login")
    print(
        "   stop with: python scripts/neomind_fin_autostart.py uninstall"
    )

    # Open the dashboard in the default browser (non-fatal if absent).
    if not args.no_open and shutil.which("open"):
        _run(["open", DEFAULT_URL], check=False)
    return 0


def cmd_grant_fda(args: argparse.Namespace) -> int:
    """Open System Settings → Privacy & Security → Full Disk Access
    directly, and print the exact python binary path to grant."""
    py = default_python_bin()
    print(f"python binary to grant Full Disk Access: {py}")
    print()
    print("In the pane that opens:")
    print("  1. Click the '+' button (may need to unlock first)")
    print("  2. Press ⌘⇧G, paste the path above, click Open")
    print("  3. Toggle it ON")
    print("  4. Re-run: python scripts/neomind_fin_autostart.py install")
    print()
    if shutil.which("open"):
        # The URL scheme for the FDA pane. Works on macOS 13+.
        _run(
            [
                "open",
                "x-apple.systempreferences:com.apple.preference.security"
                "?Privacy_AllFiles",
            ],
            check=False,
        )
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    plist = plist_path()
    if plist.exists():
        _run(["launchctl", "unload", str(plist)], check=False)
        plist.unlink()
        print(f"removed {plist}")
    else:
        print(f"(no plist at {plist})")
    if _port_listening():
        print(
            "warning: something is still listening on 8001 — check "
            "`lsof -i tcp:8001` and kill it manually if needed"
        )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    loaded = _launchctl_loaded()
    listening = _port_listening()
    plist = plist_path()
    print(f"plist:     {'present' if plist.exists() else 'absent'} ({plist})")
    print(f"launchd:   {'loaded' if loaded else 'not loaded'}")
    print(
        f"port 8001: {'listening' if listening else 'idle'}"
    )
    if loaded and listening:
        print()
        print(f"◇ dashboard is live → {DEFAULT_URL}")
    return 0 if (loaded and listening) else 1


def cmd_render(args: argparse.Namespace) -> int:
    sys.stdout.buffer.write(render_plist())
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="macOS launchd autostart for NeoMind fin dashboard",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="install + load + open browser")
    p_install.add_argument(
        "--no-open",
        action="store_true",
        help="don't open the dashboard in a browser after install",
    )
    p_install.set_defaults(func=cmd_install)

    p_uninstall = sub.add_parser("uninstall", help="unload + remove plist")
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_status = sub.add_parser("status", help="show loaded + listening state")
    p_status.set_defaults(func=cmd_status)

    p_render = sub.add_parser("render", help="print rendered plist to stdout")
    p_render.set_defaults(func=cmd_render)

    p_fda = sub.add_parser(
        "grant-fda",
        help="open System Settings → Full Disk Access with the right binary",
    )
    p_fda.set_defaults(func=cmd_grant_fda)

    p_boot = sub.add_parser(
        "bootstrap",
        help="create ~/.neomind_fin_venv (Homebrew python + repo editable)",
    )
    p_boot.add_argument(
        "--force", action="store_true",
        help="delete any existing venv and rebuild from scratch",
    )
    p_boot.set_defaults(
        func=lambda args: (
            print(f"isolated venv python: {bootstrap_isolated_venv(force=args.force)}")
            or 0
        )
    )

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
