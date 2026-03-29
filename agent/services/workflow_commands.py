"""Workflow command handlers — sprint, evolve, dashboard, upgrade, evidence, guard.

Extracted from core.py (Tier 2E). Each function takes the core agent reference
and command string, returning formatted output.

Created: 2026-03-28 (Tier 2E)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    pass


def handle_sprint_command(core, command: str) -> Optional[str]:
    """Handle /sprint command for structured task execution."""
    try:
        HAS_SPRINT = hasattr(core, 'sprint_mgr') and core.sprint_mgr is not None
    except Exception:
        HAS_SPRINT = False

    if not HAS_SPRINT:
        return core.formatter.warning("Sprint module not available. Install workflow modules.")

    try:
        parts = command.strip().split(maxsplit=2) if command.strip() else []
        subcommand = parts[0] if parts else "status"

        if subcommand == "start":
            if len(parts) < 2:
                return core.formatter.error("Usage: /sprint start <goal>")
            goal = " ".join(parts[1:])
            sprint = core.sprint_mgr.create(goal, mode=core.mode)
            core.current_sprint_id = sprint.id
            return core.formatter.success(
                f"✅ Sprint started: {sprint.id}\n" + core.sprint_mgr.format_status(sprint.id)
            )

        elif subcommand == "status":
            if not getattr(core, 'current_sprint_id', None):
                return core.formatter.info("No active sprint. Use: /sprint start <goal>")
            return core.formatter.info(core.sprint_mgr.format_status(core.current_sprint_id))

        elif subcommand == "advance":
            if not getattr(core, 'current_sprint_id', None):
                return core.formatter.error("No active sprint")
            next_phase = core.sprint_mgr.advance(core.current_sprint_id)
            if next_phase:
                return core.formatter.success(
                    f"▶️ Advanced to phase: {next_phase.name}\n"
                    + core.sprint_mgr.format_status(core.current_sprint_id)
                )
            else:
                core.current_sprint_id = None
                return core.formatter.success("✅ Sprint completed!")

        elif subcommand == "skip":
            if not getattr(core, 'current_sprint_id', None):
                return core.formatter.error("No active sprint")
            next_phase = core.sprint_mgr.skip_phase(core.current_sprint_id)
            if next_phase:
                return core.formatter.success(
                    f"⏭️  Skipped to phase: {next_phase.name}\n"
                    + core.sprint_mgr.format_status(core.current_sprint_id)
                )
            else:
                core.current_sprint_id = None
                return core.formatter.success("✅ Sprint completed!")

        elif subcommand == "complete":
            if not getattr(core, 'current_sprint_id', None):
                return core.formatter.error("No active sprint")
            output = " ".join(parts[1:]) if len(parts) > 1 else ""
            core.sprint_mgr.complete_phase(core.current_sprint_id, output=output)
            return core.formatter.success(
                f"✅ Phase output recorded.\n" + core.sprint_mgr.format_status(core.current_sprint_id)
            )

        elif subcommand == "help":
            return """📋 /sprint Command — Structured Task Execution

Available subcommands:
  /sprint start <goal>      - Start a new sprint (auto-detects mode-specific phases)
  /sprint status            - Show current sprint progress
  /sprint advance           - Complete current phase and move to next
  /sprint skip              - Skip current phase and move to next
  /sprint complete <output> - Record output/notes for current phase
  /sprint help              - Show this help

Example workflow:
  /sprint start "Fix authentication bug"
  /sprint status                           # See progress
  /sprint complete "Analyzed root cause"   # Add notes
  /sprint advance                          # Move to next phase"""

        else:
            return core.formatter.error(f"Unknown sprint subcommand: {subcommand}")

    except Exception as e:
        return core.formatter.error(f"Sprint error: {e}")


def handle_careful_command(core, command: str) -> Optional[str]:
    """Handle /careful command — warn before dangerous operations."""
    HAS_GUARDS = hasattr(core, 'guard') and core.guard is not None
    if not HAS_GUARDS:
        return core.formatter.warning("Guards module not available. Install workflow modules.")
    try:
        cmd = command.strip() if command else ""
        if not cmd or cmd == "status":
            return core.guard.get_status()
        elif cmd == "on":
            core.guard.enable_careful()
            return core.formatter.success("🟢 Careful mode ON — warnings enabled for dangerous commands")
        elif cmd == "off":
            core.guard.disable_careful()
            return core.formatter.info("⚪ Careful mode OFF — no warnings")
        else:
            return core.formatter.error("Usage: /careful [on|off|status]")
    except Exception as e:
        return core.formatter.error(f"Guard error: {e}")


def handle_freeze_command(core, command: str) -> Optional[str]:
    """Handle /freeze command — restrict edits to one directory."""
    HAS_GUARDS = hasattr(core, 'guard') and core.guard is not None
    if not HAS_GUARDS:
        return core.formatter.warning("Guards module not available. Install workflow modules.")
    try:
        if not command or not command.strip():
            return core.formatter.error("Usage: /freeze <directory>")
        directory = command.strip()
        core.guard.enable_freeze(directory)
        return core.formatter.success(
            f"🧊 Frozen to: {directory}\n"
            "   Edits restricted to this directory and subdirs.\n"
            "   Use /unfreeze to remove restriction."
        )
    except Exception as e:
        return core.formatter.error(f"Freeze error: {e}")


def handle_guard_command(core, command: str) -> Optional[str]:
    """Handle /guard command — enable both /careful and /freeze."""
    HAS_GUARDS = hasattr(core, 'guard') and core.guard is not None
    if not HAS_GUARDS:
        return core.formatter.warning("Guards module not available. Install workflow modules.")
    try:
        cmd = command.strip() if command else ""
        if not cmd or cmd == "status":
            return core.guard.get_status()
        elif cmd == "on":
            core.guard.enable_guard()
            return core.formatter.success("🛡️  Full guard enabled — /careful + /freeze (with current directory)")
        elif cmd.startswith("on "):
            directory = cmd[3:].strip()
            core.guard.enable_guard(directory)
            return core.formatter.success(f"🛡️  Full guard enabled\n   Careful: ON\n   Frozen to: {directory}")
        elif cmd == "off":
            core.guard.disable_guard()
            return core.formatter.info("⚪ Guard disabled")
        else:
            return core.formatter.error("Usage: /guard [on [dir]|off|status]")
    except Exception as e:
        return core.formatter.error(f"Guard error: {e}")


def handle_unfreeze_command(core, command: str) -> Optional[str]:
    """Handle /unfreeze command — remove edit restrictions."""
    HAS_GUARDS = hasattr(core, 'guard') and core.guard is not None
    if not HAS_GUARDS:
        return core.formatter.warning("Guards module not available. Install workflow modules.")
    try:
        core.guard.disable_freeze()
        return core.formatter.success("🧊 Freeze removed — edits allowed everywhere")
    except Exception as e:
        return core.formatter.error(f"Unfreeze error: {e}")


def handle_evidence_command(core, command: str) -> Optional[str]:
    """Handle /evidence command — view audit trail."""
    HAS_EVIDENCE = hasattr(core, 'evidence') and core.evidence is not None
    if not HAS_EVIDENCE:
        return core.formatter.warning("Evidence module not available. Install workflow modules.")
    try:
        parts = command.strip().split() if command and command.strip() else []
        subcommand = parts[0] if parts else "recent"

        if subcommand == "recent":
            limit = int(parts[1]) if len(parts) > 1 else 10
            return core.evidence.format_recent(limit=limit)

        elif subcommand == "stats":
            stats = core.evidence.get_stats()
            lines = ["📊 Evidence Trail Statistics", "=" * 40]
            lines.append(f"Total entries: {stats.get('total', 0)}")
            if "by_action" in stats:
                lines.append("\nBy action:")
                for action, count in sorted(stats["by_action"].items()):
                    lines.append(f"  {action}: {count}")
            lines.append(f"\nLog size: {stats.get('log_size_kb', 0)} KB")
            lines.append(f"Location: {stats.get('log_path', 'N/A')}")
            return "\n".join(lines)

        elif subcommand == "filter":
            if len(parts) < 2:
                return core.formatter.error("Usage: /evidence filter <action>")
            action = parts[1]
            entries = core.evidence.get_by_action(action)
            if not entries:
                return core.formatter.info(f"No evidence entries for action: {action}")
            lines = [f"📋 Evidence for action: {action}", "=" * 40]
            for e in entries[-10:]:
                ts = e.get("ts", "")[:16]
                lines.append(f"[{ts}] {e.get('input', '')[:60]}")
            return "\n".join(lines)

        elif subcommand == "help":
            return """📋 /evidence Command — Audit Trail Viewer

Available subcommands:
  /evidence recent [limit]  - Show recent entries (default: 10)
  /evidence stats           - Show statistics
  /evidence filter <action> - Filter by action type
  /evidence help            - Show this help

Example:
  /evidence recent 20
  /evidence filter command"""

        else:
            return core.formatter.error(f"Unknown evidence subcommand: {subcommand}")

    except Exception as e:
        return core.formatter.error(f"Evidence error: {e}")


def handle_evolve_command(core, command: str) -> Optional[str]:
    """Handle /evolve command — view self-evolution status."""
    HAS_EVOLUTION = hasattr(core, 'evolution') and core.evolution is not None
    if not HAS_EVOLUTION:
        return core.formatter.warning("Evolution module not available. Install evolution modules.")
    try:
        parts = command.strip().split() if command and command.strip() else []
        subcommand = parts[0] if parts else "status"

        if subcommand == "status":
            return core.evolution.get_evolution_summary()

        elif subcommand == "daily":
            report = core.evolution.run_daily_audit()
            lines = ["📊 Daily Audit Report", "=" * 50]
            lines.append(f"Date: {report.date}")
            lines.append(f"Total calls: {report.total_calls}")
            lines.append(f"Errors: {report.errors}")
            lines.append(f"Fallbacks: {report.fallbacks}")
            if report.most_frequent_action:
                lines.append(f"Top action: {report.most_frequent_action}")
            if report.issues:
                lines.append("\nIssues detected:")
                for issue in report.issues:
                    lines.append(f"  - {issue}")
            return "\n".join(lines)

        elif subcommand == "weekly":
            report = core.evolution.run_weekly_retro()
            lines = ["📈 Weekly Retrospective", "=" * 50]
            lines.append(f"Week: {report.week_start} to {report.week_end}")
            lines.append(f"Sessions: {report.total_sessions}")
            lines.append(f"Tasks: {report.total_tasks}")
            lines.append(f"Success rate: {report.success_rate:.1f}%")
            if report.top_tools:
                lines.append(f"Top tools: {', '.join(report.top_tools)}")
            return "\n".join(lines)

        elif subcommand == "health":
            report = core.evolution.run_startup_check()
            lines = ["🏥 Health Check", "=" * 50]
            lines.append(f"Checks passed: {report.checks_passed}")
            lines.append(f"Checks failed: {report.checks_failed}")
            if report.issues:
                lines.append("\nIssues:")
                for issue in report.issues:
                    lines.append(f"  ⚠️  {issue}")
            else:
                lines.append("\n✓ All systems healthy")
            return "\n".join(lines)

        elif subcommand == "help":
            return """📈 /evolve Command — Self-Evolution Status

Available subcommands:
  /evolve status  - Show overall evolution status
  /evolve daily   - Run daily audit
  /evolve weekly  - Run weekly retrospective
  /evolve health  - Run health check
  /evolve help    - Show this help

NeoMind Phase 4: Self-Evolution Closed Loop
- Learns from feedback and conversations
- Adjusts preferences automatically
- Generates weekly retros
- Tracks improvement over time"""

        else:
            return core.formatter.error(f"Unknown evolve subcommand: {subcommand}")

    except Exception as e:
        return core.formatter.error(f"Evolution error: {e}")


def handle_dashboard_command(core, command: str) -> Optional[str]:
    """Handle /dashboard command — generate HTML evolution metrics dashboard."""
    try:
        from agent.evolution.dashboard import generate_dashboard

        dashboard_path = Path.home() / ".neomind" / "dashboard.html"
        html = generate_dashboard(str(dashboard_path))

        return core.formatter.success(
            f"📊 Dashboard generated!\n\n"
            f"Location: {dashboard_path}\n\n"
            f"Open in browser to view:\n"
            f"  - Health status and system checks\n"
            f"  - Daily activity (7-day trend)\n"
            f"  - Mode distribution (chat/coding/fin)\n"
            f"  - Learning patterns\n"
            f"  - Recent evidence trail\n"
            f"  - Evolution timeline\n\n"
            f"Size: {dashboard_path.stat().st_size / 1024:.1f} KB"
        )

    except ImportError:
        return core.formatter.warning(
            "Dashboard module not available. "
            "Install evolution modules: pip install agent-evolution"
        )
    except Exception as e:
        return core.formatter.error(f"Dashboard generation error: {e}")


def handle_upgrade_command(core, command: str) -> Optional[str]:
    """Handle /upgrade command — check and manage updates."""
    HAS_UPGRADE = hasattr(core, 'upgrader') and core.upgrader is not None
    if not HAS_UPGRADE:
        return core.formatter.warning("Upgrade module not available. Install upgrade modules.")
    try:
        parts = command.strip().split() if command and command.strip() else []
        subcommand = parts[0] if parts else "check"

        if subcommand == "check":
            has_updates, new_version = core.upgrader.check_for_updates()
            if has_updates:
                lines = ["🎉 Updates Available!", "=" * 50]
                lines.append(f"Current version: {core.upgrader.get_current_version()}")
                lines.append(f"New version: {new_version}")
                lines.append(f"\nChangelog:\n{core.upgrader.get_changelog_diff()}")
                lines.append("\nRun '/upgrade perform' to install updates.")
                return "\n".join(lines)
            else:
                return core.formatter.info(
                    f"✓ You're on the latest version: {core.upgrader.get_current_version()}"
                )

        elif subcommand == "changelog":
            changelog = core.upgrader.get_changelog_diff()
            return f"📝 Changelog:\n\n{changelog}"

        elif subcommand == "perform":
            lines = ["⚠️  Upgrade will:"]
            lines.append("1. Backup current version")
            lines.append("2. Pull latest from origin/main")
            lines.append("3. Verify installation")
            lines.append("4. Rollback if errors detected")
            lines.append("\nAre you sure? Run with '--confirm' to proceed.")
            if "--confirm" in (command or ""):
                success, message = core.upgrader.upgrade(confirmed=True)
                if success:
                    return core.formatter.success(message)
                else:
                    return core.formatter.error(message)
            return "\n".join(lines)

        elif subcommand == "history":
            history = core.upgrader.get_upgrade_history()
            if not history:
                return core.formatter.info("No upgrade history yet.")
            lines = ["📋 Upgrade History", "=" * 50]
            for entry in history[-10:]:
                ts = entry.get("timestamp", "?")[:19]
                upgrade_type = entry.get("type", "?")
                version = entry.get("version", "?")
                lines.append(f"[{ts}] {upgrade_type}: {version}")
            return "\n".join(lines)

        elif subcommand == "help":
            return """🔄 /upgrade Command — Update Management

Available subcommands:
  /upgrade check           - Check for available updates
  /upgrade changelog       - Show what changed
  /upgrade perform         - Perform safe upgrade
  /upgrade perform --confirm - Actually install updates
  /upgrade history         - Show upgrade history
  /upgrade help            - Show this help

Safe Upgrade Process:
1. Backup current version (git tag)
2. Pull latest code
3. Verify installation
4. Rollback on errors"""

        else:
            return core.formatter.error(f"Unknown upgrade subcommand: {subcommand}")

    except Exception as e:
        return core.formatter.error(f"Upgrade error: {e}")
