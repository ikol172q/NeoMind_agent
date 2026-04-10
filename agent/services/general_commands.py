"""General commands — extracted from core.py for architecture completeness.

Contains: search, models, skills, skill, auto, plan, task, execute, switch, context.
All take `core` as first parameter (standalone function pattern).

Created: 2026-03-28 (P3-C completion)
"""

import asyncio
from typing import Optional


# ── /search ─────────────────────────────────────────────────────────────

def handle_search(core, query: str) -> str:
    """Process search command — smart routing between LLM, grep, and web."""
    if not query or query.strip() == "":
        return (
            "Usage: /search <query>\n"
            "  Routes automatically:\n"
            "  • 'search codebase for TODO'  → local grep\n"
            "  • 'search codebase to understand it' → AI analysis\n"
            "  • 'search python asyncio tutorial'  → web search\n"
            "  Subcommands:\n"
            "  • /search status  — show search engine status & active sources\n"
            "  Or use directly: /grep <pattern>  |  /find <name>"
        )

    q_stripped = query.strip().lower()
    if q_stripped in ("status", "sources", "info"):
        if hasattr(core.searcher, 'get_status'):
            return core.searcher.get_status()
        return f"Search engine: {type(core.searcher).__name__} (no status available)"
    if q_stripped in ("metrics", "stats", "report"):
        if hasattr(core.searcher, 'metrics'):
            return core.searcher.metrics.format_report(all_time=(q_stripped == "report"))
        return "Metrics not available (legacy search engine)."

    # Smart routing in coding mode
    if core.mode == "coding":
        intent = core._classify_search_intent(query)
        if intent == "llm":
            core._safe_print("🧠 Detected codebase comprehension request — gathering context...")
            context = _gather_codebase_context(core)
            prompt = f"{query}\n\nHere is the project structure and key files:\n{context}"
            core.add_to_history("user", prompt)
            return None
        if intent == "grep":
            pattern = core._extract_grep_pattern(query)
            core._safe_print(f"🔍 Detected code search — running /grep {pattern}")
            return core.handle_grep_command(pattern)

    # Web search
    if not core.search_enabled:
        return "Search is disabled. Enable it in config or use a different search method."

    if not core.search_loop:
        core.search_loop = asyncio.new_event_loop()

    try:
        success, result = core.search_loop.run_until_complete(
            core.searcher.search(query.strip())
        )
    except Exception as e:
        success, result = False, f"Search error: {e}"

    if success:
        core.add_search_results_to_history('web', query.strip(), result)
    else:
        core.add_to_history("system", f"Web search failed for '{query.strip()}': {result}")
    return result


def _gather_codebase_context(core) -> str:
    """Gather project structure and key file previews for LLM comprehension."""
    import os
    parts = []
    cwd = os.getcwd()
    if core.code_analyzer:
        cwd = core.code_analyzer.root_path
    try:
        entries = sorted(os.listdir(cwd))
        tree_lines = []
        for entry in entries:
            full = os.path.join(cwd, entry)
            if entry.startswith(".") and entry in (".git", ".venv", "__pycache__", ".mypy_cache"):
                continue
            if os.path.isdir(full):
                tree_lines.append(f"  {entry}/")
                try:
                    subs = sorted(os.listdir(full))[:15]
                    for s in subs:
                        if s.startswith(".") or s == "__pycache__":
                            continue
                        sub_full = os.path.join(full, s)
                        suffix = "/" if os.path.isdir(sub_full) else ""
                        tree_lines.append(f"    {s}{suffix}")
                    if len(subs) > 15:
                        tree_lines.append(f"    ... ({len(os.listdir(full)) - 15} more)")
                except OSError:
                    pass
            else:
                tree_lines.append(f"  {entry}")
        parts.append("Project structure:\n" + "\n".join(tree_lines))
    except OSError:
        pass

    key_files = ["README.md", "pyproject.toml", "setup.py", "main.py",
                 "agent_config.py", "Makefile", "requirements.txt"]
    for fname in key_files:
        fpath = os.path.join(cwd, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath, "r", errors="replace") as f:
                    lines = f.readlines()[:30]
                preview = "".join(lines)
                if len(lines) == 30:
                    preview += "\n... (truncated)"
                parts.append(f"── {fname} ──\n{preview}")
            except OSError:
                pass

    return "\n\n".join(parts) if parts else "(Could not read project structure)"


# ── /auto ────────────────────────────────────────────────────────────────

def handle_auto_command(core, subcommand: str) -> Optional[str]:
    """Handle /auto command for controlling auto-features."""
    # Import agent_config from the same path as core.py so test patches work
    import agent.core as _core_module
    _agent_config = _core_module.agent_config

    from agent.services.nl_interpreter import NaturalLanguageInterpreter

    subcommand = subcommand.strip().lower()
    parts = subcommand.split()
    if not parts:
        return _show_auto_status(core)

    if parts[0] == 'search' and len(parts) == 2:
        value = parts[1]
        if value in ('on', 'enable', 'true'):
            core.auto_search_enabled = True
            success = _agent_config.update_value("agent.auto_features.auto_search.enabled", True)
            return f"Auto-search enabled {'(config saved)' if success else '(config save failed)'}"
        elif value in ('off', 'disable', 'false'):
            core.auto_search_enabled = False
            success = _agent_config.update_value("agent.auto_features.auto_search.enabled", False)
            return f"Auto-search disabled {'(config saved)' if success else '(config save failed)'}"
        else:
            return "Usage: /auto search on|off"

    elif parts[0] == 'interpret' and len(parts) == 2:
        value = parts[1]
        if value in ('on', 'enable', 'true'):
            core.natural_language_enabled = True
            if not core.interpreter:
                core.interpreter = NaturalLanguageInterpreter(
                    confidence_threshold=core.natural_language_confidence_threshold
                )
            success = _agent_config.update_value("agent.auto_features.natural_language.enabled", True)
            return f"Natural language interpretation enabled {'(config saved)' if success else '(config save failed)'}"
        elif value in ('off', 'disable', 'false'):
            core.natural_language_enabled = False
            core.interpreter = None
            success = _agent_config.update_value("agent.auto_features.natural_language.enabled", False)
            return f"Natural language interpretation disabled {'(config saved)' if success else '(config save failed)'}"
        else:
            return "Usage: /auto interpret on|off"

    elif parts[0] == 'status':
        return _show_auto_status(core)

    elif parts[0] == 'help':
        return _show_auto_help()

    else:
        return _show_auto_help()


def _show_auto_status(core) -> str:
    """Return status of auto-features."""
    status_lines = [
        "🤖 Auto-feature Status:",
        f"  • Auto-search: {'ENABLED' if core.auto_search_enabled else 'DISABLED'}",
        f"  • Natural language interpretation: {'ENABLED' if core.natural_language_enabled else 'DISABLED'}",
    ]
    if core.interpreter:
        status_lines.append(f"  • Confidence threshold: {core.interpreter.confidence_threshold}")
    status_lines.append(
        f"  • Safety confirmations: File ops={core.safety_confirm_file_operations}, "
        f"Code changes={core.safety_confirm_code_changes}"
    )
    return "\n".join(status_lines)


def _show_auto_help() -> str:
    """Return help for /auto command."""
    return "\n".join([
        "🤖 /auto command usage:",
        "  /auto search on|off      - Enable/disable auto-search",
        "  /auto interpret on|off   - Enable/disable natural language interpretation",
        "  /auto status            - Show current auto-feature settings",
        "  /auto help              - Show this help",
    ])


# ── /models ──────────────────────────────────────────────────────────────

def handle_models_command(core, command: str) -> Optional[str]:
    """Handle /models command with various subcommands."""
    parts = command.split()

    if len(parts) == 1:  # Just "/models"
        core.print_models()
        return None
    elif len(parts) >= 2:
        subcommand = parts[1].lower()

        if subcommand in ["list", "show", "ls"]:
            core.print_models(force_refresh=len(parts) > 2 and parts[2] == "--refresh")
            return None
        elif subcommand in ["switch", "use", "set"]:
            if len(parts) == 3:
                model_id = parts[2]
                success = core.set_model(model_id)
                return "Model switched successfully." if success else "Failed to switch model."
            elif len(parts) == 4:
                target = parts[2].lower()
                model_id = parts[3]
                if target in ["agent", "a"]:
                    success = core.set_model(model_id)
                    return "Model switched successfully." if success else "Failed to switch model."
                else:
                    print(f"Unknown target: {target}. Use 'agent'.")
                    print("Usage: /models switch [agent] <model_id>")
                    return None
            else:
                print("Usage: /models switch [agent] <model_id>")
                print("Examples:")
                print("  /models switch deepseek-reasoner          # Switch to DeepSeek model")
                print("  /models switch glm-5                      # Switch to z.ai model")
                print("  /models switch agent deepseek-reasoner    # Switch model (explicit)")
                return None
        elif subcommand in ["current", "active"]:
            print(f"\nCurrent model: {core.model}")
            return None
        elif subcommand in ["help", "?"]:
            print("""
/models commands:
  /models                    - Show available models
  /models list              - List all available models
  /models list --refresh    - Force refresh model list
  /models switch <model>    - Switch agent model (backward compatible)
  /models switch agent <model> - Switch agent model
  /models current           - Show current agent model
  /models help              - Show this help
            """.strip())
            return None
        else:
            print(f"Unknown subcommand: {subcommand}")
            print("Try: /models help")
            return None

    return None


# ── /skills & /skill ─────────────────────────────────────────────────────

def handle_skills_command(core, command: str) -> Optional[str]:
    """Handle /skills command to list available skills."""
    command = command.strip().lower()

    if not core._skill_loader:
        return "⚠️ Skill system not loaded."

    if not command or command == "list":
        output = core._skill_loader.format_skill_list(core.mode)
        active = ""
        if core._active_skill:
            active = f"\n\n✅ Active skill: /{core._active_skill.name}"
        return f"📚 Skills available in **{core.mode}** mode:\n{output}{active}"

    elif command == "all":
        output = core._skill_loader.format_skill_list(None)
        return f"📚 All skills:\n{output}"

    elif command == "refresh":
        count = core._skill_loader.load_all()
        return f"🔄 Reloaded {count} skills from disk."

    elif command == "help":
        return (
            "/skills command usage:\n"
            "  /skills        — List skills for current mode\n"
            "  /skills all    — List all skills\n"
            "  /skills refresh — Reload from disk\n"
            "  /skills help   — Show this help\n\n"
            "Use /skill <name> to activate a skill."
        )
    else:
        return "Unknown subcommand. Use /skills help for usage."


def handle_skill_command(core, command: str) -> Optional[str]:
    """Handle /skill command to activate/deactivate a skill."""
    command = command.strip()

    if not core._skill_loader:
        return "⚠️ Skill system not loaded."

    if not command:
        return "Usage: /skill <name> | /skill off | /skill status"

    if command.lower() == "off":
        if core._active_skill:
            name = core._active_skill.name
            core.conversation_history = [
                msg for msg in core.conversation_history
                if not (msg.get("role") == "system"
                        and msg.get("content", "").startswith("## Active Skill:"))
            ]
            core._active_skill = None
            return f"🔴 Deactivated skill: {name}"
        return "No skill is currently active."

    if command.lower() == "status":
        if core._active_skill:
            s = core._active_skill
            return (
                f"✅ Active skill: {s.name} (v{s.version})\n"
                f"   {s.description}\n"
                f"   Category: {s.category} | Modes: {', '.join(s.modes)}"
            )
        return "No skill is currently active."

    # Activate a skill
    skill_name = command.split()[0].lstrip("/")
    skill = core._skill_loader.get(skill_name)

    if not skill:
        candidates = [
            s for s in core._skill_loader.get_skills_for_mode(core.mode)
            if skill_name in s.name
        ]
        if len(candidates) == 1:
            skill = candidates[0]
        elif candidates:
            names = ", ".join(f"/{c.name}" for c in candidates)
            return f"Multiple matches: {names}. Be more specific."
        else:
            return f"❌ Skill '{skill_name}' not found. Use /skills to see available skills."

    if core.mode not in skill.modes:
        return (
            f"⚠️ Skill '{skill.name}' is not available in {core.mode} mode. "
            f"Available in: {', '.join(skill.modes)}"
        )

    # Deactivate previous skill if any
    if core._active_skill:
        core.conversation_history = [
            msg for msg in core.conversation_history
            if not (msg.get("role") == "system"
                    and msg.get("content", "").startswith("## Active Skill:"))
        ]

    # Activate new skill
    core._active_skill = skill
    core.add_to_history("system", skill.to_system_prompt())

    return (
        f"✅ Activated skill: **{skill.name}** (v{skill.version})\n"
        f"   {skill.description}\n\n"
        f"The skill prompt has been injected. I'll follow its guidelines for subsequent responses.\n"
        f"Use /skill off to deactivate."
    )


# ── /plan ────────────────────────────────────────────────────────────────

def handle_plan_command(core, command: str) -> Optional[str]:
    """Handle /plan command for generating and managing plans."""
    if not command.strip():
        return _show_plan_help()

    parts = command.strip().split()
    if parts[0].lower() not in ("list", "delete", "show", "help"):
        goal = command.strip()
        plan = core.goal_planner.generate_plan(goal, core)
        steps_count = len(plan.get("steps", []))
        return (
            f"📋 Plan generated with ID: {plan['id']}\n"
            f"Goal: {plan['goal']}\n"
            f"Steps: {steps_count}\n"
            f"Status: {plan['status']}\n"
            f"Use /execute {plan['id']} to start execution."
        )

    subcommand = parts[0].lower()

    if subcommand == "list":
        status_filter = None
        if len(parts) > 1:
            status_filter = parts[1].lower()
            if status_filter not in ("pending", "in_progress", "completed", "failed"):
                return f"Invalid status filter '{status_filter}'. Use: pending, in_progress, completed, failed"
        plans = core.goal_planner.list_plans(status_filter)
        if not plans:
            return "📭 No plans found." + (f" (filter: {status_filter})" if status_filter else "")

        result = ["📋 Plan List" + (f" (filter: {status_filter})" if status_filter else "")]
        for plan in plans:
            status_emoji = {"pending": "⭕", "in_progress": "🔄", "completed": "✅", "failed": "❌"}.get(plan.get("status"), "❓")
            result.append(f"  {status_emoji} [{plan['id']}] {plan.get('goal', 'No goal')}")
            result.append(f"     Steps: {len(plan.get('steps', []))}, Status: {plan.get('status')}, Created: {plan.get('created_at', '')[:10]}")
        return "\n".join(result)

    elif subcommand == "delete":
        if len(parts) != 2:
            return "Usage: /plan delete <plan_id>"
        plan_id = parts[1]
        success = core.goal_planner.delete_plan(plan_id)
        return f"✅ Plan {plan_id} deleted" if success else f"❌ Plan {plan_id} not found"

    elif subcommand == "show":
        if len(parts) != 2:
            return "Usage: /plan show <plan_id>"
        plan_id = parts[1]
        plan = core.goal_planner.get_plan(plan_id)
        if not plan:
            return f"❌ Plan {plan_id} not found"

        result = [f"📋 Plan: {plan.get('goal', 'No goal')}"]
        result.append(f"ID: {plan['id']}")
        result.append(f"Status: {plan.get('status')}")
        result.append(f"Created: {plan.get('created_at')}")
        result.append(f"Steps ({len(plan.get('steps', []))}):")
        for i, step in enumerate(plan.get("steps", [])):
            current_mark = " →" if i == plan.get("current_step", 0) else "  "
            result.append(f"{current_mark} {i+1}. {step.get('description', 'No description')}")
            result.append(f"    Action: {step.get('action', 'N/A')}")
            if step.get("details"):
                result.append(f"    Details: {step.get('details')}")
            if step.get("dependencies"):
                result.append(f"    Depends on: {step.get('dependencies')}")
        return "\n".join(result)

    elif subcommand in ("help", "?"):
        return _show_plan_help()

    else:
        return f"Unknown subcommand: {subcommand}\n{_show_plan_help()}"


def _show_plan_help() -> str:
    return "\n".join([
        "📋 /plan command usage:",
        "  /plan <goal>                 - Generate a plan for a goal",
        "  /plan list [status]          - List plans (optional status filter)",
        "  /plan delete <id>            - Delete plan",
        "  /plan show <id>              - Show plan details",
        "  /plan help                   - Show this help",
        "",
        "Status filters: pending, in_progress, completed, failed",
    ])


# ── /task ────────────────────────────────────────────────────────────────

def handle_task_command(core, command: str) -> Optional[str]:
    """Handle /task command for task management."""
    if not command.strip():
        return _show_task_help()

    parts = command.strip().split()
    subcommand = parts[0].lower()

    if subcommand == "create":
        if len(parts) < 2:
            return "Usage: /task create <description>"
        description = " ".join(parts[1:])
        task = core.task_manager.create_task(description)
        return f"✅ Task created with ID: {task.id}\nDescription: {task.description}"

    elif subcommand == "list":
        status_filter = None
        if len(parts) > 1:
            status_filter = parts[1].lower()
            if status_filter not in ("todo", "in_progress", "done"):
                return f"Invalid status filter '{status_filter}'. Use: todo, in_progress, done"
        tasks = core.task_manager.list_tasks(status_filter)
        if not tasks:
            return "📭 No tasks found." + (f" (filter: {status_filter})" if status_filter else "")

        result = ["📋 Task List" + (f" (filter: {status_filter})" if status_filter else "")]
        for task in tasks:
            status_emoji = {"todo": "⭕", "in_progress": "🔄", "done": "✅"}.get(task.status, "❓")
            result.append(f"  {status_emoji} [{task.id}] {task.description}")
            result.append(f"     Status: {task.status}, Created: {task.created_at[:10]}")
        return "\n".join(result)

    elif subcommand == "update":
        if len(parts) != 3:
            return "Usage: /task update <task_id> <status>"
        task_id, new_status = parts[1], parts[2].lower()
        if new_status not in ("todo", "in_progress", "done"):
            return f"Invalid status '{new_status}'. Use: todo, in_progress, done"
        success = core.task_manager.update_task_status(task_id, new_status)
        return f"✅ Task {task_id} updated to '{new_status}'" if success else f"❌ Task {task_id} not found"

    elif subcommand == "delete":
        if len(parts) != 2:
            return "Usage: /task delete <task_id>"
        task_id = parts[1]
        success = core.task_manager.delete_task(task_id)
        return f"✅ Task {task_id} deleted" if success else f"❌ Task {task_id} not found"

    elif subcommand == "clear":
        count = core.task_manager.clear_all_tasks()
        return f"✅ Cleared {count} tasks"

    elif subcommand in ("help", "?"):
        return _show_task_help()

    else:
        return f"Unknown subcommand: {subcommand}\n{_show_task_help()}"


def _show_task_help() -> str:
    return "\n".join([
        "📋 /task command usage:",
        "  /task create <description>      - Create a new task",
        "  /task list [status]             - List tasks (optional status filter)",
        "  /task update <id> <status>      - Update task status (todo, in_progress, done)",
        "  /task delete <id>               - Delete task",
        "  /task clear                     - Delete all tasks",
        "  /task help                      - Show this help",
    ])


# ── /execute ─────────────────────────────────────────────────────────────

def handle_execute_command(core, command: str) -> Optional[str]:
    """Handle /execute command to execute a plan."""
    if not command.strip():
        return "Usage: /execute <plan_id>"

    parts = command.strip().split()
    if len(parts) != 1:
        return "Usage: /execute <plan_id>"

    plan_id = parts[0]
    plan = core.goal_planner.get_plan(plan_id)
    if not plan:
        return f"❌ Plan {plan_id} not found"

    if plan.get("status") == "pending":
        core.goal_planner.update_plan_status(plan_id, "in_progress")

    current_step = core.goal_planner.get_current_step(plan_id)
    if not current_step:
        core.goal_planner.update_plan_status(plan_id, "completed")
        return f"✅ Plan {plan_id} already completed!"

    step_num = plan.get("current_step", 0) + 1
    total_steps = len(plan.get("steps", []))

    result = [
        f"🚀 Executing Plan: {plan.get('goal', 'No goal')}",
        f"Step {step_num}/{total_steps}: {current_step.get('description', 'No description')}",
        f"Action: {current_step.get('action', 'N/A')}",
    ]
    if current_step.get("details"):
        result.append(f"Details: {current_step.get('details')}")

    result.append("\n📝 The AI will now help you execute this step.")
    result.append(f"After completing, run /execute {plan_id} again to advance to next step.")
    return "\n".join(result)


# ── /switch ──────────────────────────────────────────────────────────────

def handle_switch_command(core, command: str) -> Optional[str]:
    """Handle /switch command to switch model.

    Supports model aliases: opus, sonnet, haiku, reasoner, coder, etc.
    """
    if not command.strip():
        from agent.services.llm_provider import MODEL_ALIASES
        alias_list = ", ".join(f"{k}→{v}" for k, v in sorted(MODEL_ALIASES.items()))
        return f"Usage: /switch <model_id>\nAliases: {alias_list}"

    model_id = command.strip()
    # Resolve alias for display
    from agent.services.llm_provider import resolve_model_alias
    resolved = resolve_model_alias(model_id)
    success = core.set_model(model_id)
    if success:
        alias_note = f" (alias for {resolved})" if resolved != model_id else ""
        return f"✅ Switched model to {resolved}{alias_note}"
    else:
        return f"❌ Failed to switch model to {model_id}"


# ── /context ─────────────────────────────────────────────────────────────

def handle_context_command(core, command: str) -> Optional[str]:
    """Handle /context command to manage conversation context."""
    try:
        HAS_TIKTOKEN = True
        import tiktoken
    except ImportError:
        HAS_TIKTOKEN = False

    command = command.strip().lower()
    if not command or command == "status":
        stats = core.context_manager.get_context_usage()
        lines = [
            "📊 Context Status:",
            f"  • Tokens used: {stats['total_tokens']} / {stats['max_context_tokens']} ({stats['percent_used']:.1%})",
            f"  • Warning threshold: {stats['warning_threshold']:.0%} ({stats['warning_tokens']} tokens)",
            f"  • Break threshold: {stats['break_threshold']:.0%} ({stats['break_tokens']} tokens)",
            f"  • Near limit: {stats['is_near_limit']}",
            f"  • Over break threshold: {stats['is_over_break']}",
        ]
        if HAS_TIKTOKEN:
            lines.append("  • Token counting: tiktoken (cl100k_base)")
        else:
            lines.append("  • Token counting: approximate (chars/4)")
        return "\n".join(lines)
    elif command == "compress":
        result = core.context_manager.compress_history()
        return f"✅ Compressed history: {result['original_tokens']} → {result['compressed_tokens']} tokens (-{result['token_reduction']})"
    elif command == "clear":
        core.conversation_history.clear()
        core._ensure_system_prompt()
        return "✅ Conversation history cleared. System prompt re-added."
    elif command == "help":
        return (
            "/context commands:\n"
            "  status    - Show token usage and limits\n"
            "  compress  - Compress history to reduce tokens\n"
            "  clear     - Clear conversation history\n"
            "  help      - Show this help"
        )
    else:
        return f"Unknown subcommand: {command}. Use /context help for usage."
