"""SharedCommandsMixin — commands available to ALL personality modes.

P3-C COMPLETE: All 39 commands are real implementations or module calls.
  - 13 LLM/conversation commands: real implementations (summarize, reason, etc.)
  - 9 workflow commands: call workflow_commands.py standalone functions directly
  - 10 general commands: call general_commands.py standalone functions directly
  - 5 web/research commands: read, links, crawl, webmap, logs (moved from Chat)
  - 2 inlined: mode, help

Created: 2026-03-28 (Step 6 of architecture redesign)
Updated: 2026-03-28 (P3-C — workflow commands + mode/help/context inlined)
"""

from typing import TYPE_CHECKING, Dict, Tuple, Callable, Any

if TYPE_CHECKING:
    pass


class SharedCommandsMixin:
    """Commands available to ALL personalities via mixin inheritance.

    Each personality class inherits this mixin:
        class ChatPersonality(BasePersonality, SharedCommandsMixin): ...

    All handlers currently delegate to self.core (NeoMindAgent) which still
    holds the real implementations. As methods are extracted from core.py,
    the delegation will be replaced with direct implementations here.
    """

    def get_shared_command_handlers(self) -> Dict[str, tuple]:
        """Return the 39 shared command → (handler, strip_prefix) mappings.

        Called by core._rebuild_command_handlers() to merge with
        personality-specific handlers.
        """
        return {
            # ── Search & Discovery ───────────────────────────────
            "/search": (self._shared_handle_search, True),
            "/models": (self._shared_handle_models_command, False),
            "/mode": (self._shared_handle_mode_command, True),

            # ── Skills ───────────────────────────────────────────
            "/skills": (self._shared_handle_skills_command, True),
            "/skill": (self._shared_handle_skill_command, True),
            "/auto": (self._shared_handle_auto_command, True),

            # ── Planning & Tasks ─────────────────────────────────
            "/plan": (self._shared_handle_plan_command, True),
            "/task": (self._shared_handle_task_command, True),
            "/execute": (self._shared_handle_execute_command, True),
            "/switch": (self._shared_handle_switch_command, True),

            # ── Analysis (LLM-only, no file changes) ────────────
            "/summarize": (self._shared_handle_summarize_command, True),
            "/reason": (self._shared_handle_reason_command, True),
            "/debug": (self._shared_handle_debug_command, True),
            "/explain": (self._shared_handle_explain_command, True),
            "/refactor": (self._shared_handle_refactor_command, True),
            "/translate": (self._shared_handle_translate_command, True),
            "/generate": (self._shared_handle_generate_command, True),

            # ── Conversation Management ──────────────────────────
            "/clear": (self._shared_handle_clear_command, True),
            "/history": (self._shared_handle_history_command, True),
            "/context": (self._shared_handle_context_command, True),
            "/think": (self._shared_handle_think_command, True),
            "/verbose": (self._shared_handle_verbose_command, True),

            # ── Session Control ──────────────────────────────────
            "/quit": (self._shared_handle_quit_command, True),
            "/exit": (self._shared_handle_exit_command, True),
            "/help": (self._shared_handle_help_command, True),

            # ── Workflow & Safety ────────────────────────────────
            "/sprint": (self._shared_handle_sprint_command, True),
            "/careful": (self._shared_handle_careful_command, True),
            "/freeze": (self._shared_handle_freeze_command, True),
            "/guard": (self._shared_handle_guard_command, True),
            "/unfreeze": (self._shared_handle_unfreeze_command, True),
            "/evidence": (self._shared_handle_evidence_command, True),
            "/evolve": (self._shared_handle_evolve_command, True),
            "/dashboard": (self._shared_handle_dashboard_command, True),
            "/upgrade": (self._shared_handle_upgrade_command, True),

            # ── Architecture ──────────────────────────────────────
            "/arch": (self._shared_handle_arch_command, True),

            # ── Web / Research (available to ALL modes) ───────────
            "/read": (self._shared_handle_read_command, True),
            "/links": (self._shared_handle_links_command, True),
            "/crawl": (self._shared_handle_crawl_command, True),
            "/webmap": (self._shared_handle_webmap_command, True),
            "/logs": (self._shared_handle_logs_command, True),
        }

    # ── P3-C: All commands now call standalone module functions ──────

    def _shared_handle_search(self, query):
        from agent.services.general_commands import handle_search
        return handle_search(self.core, query)

    def _shared_handle_models_command(self, arg):
        from agent.services.general_commands import handle_models_command
        return handle_models_command(self.core, arg)

    def _shared_handle_mode_command(self, arg):
        """Switch mode — /mode chat|coding|fin."""
        if not arg or not arg.strip():
            return f"📍 Current mode: {self.core.mode}. Usage: /mode <chat|coding|fin>"
        target = arg.strip().lower()
        if target == self.core.mode:
            return f"Already in {target} mode."
        success = self.core.switch_mode(target)
        if not success:
            return f"❌ Invalid mode: {target}. Use 'chat', 'coding', or 'fin'."
        return None  # switch_mode prints its own message

    def _shared_handle_skills_command(self, arg):
        from agent.services.general_commands import handle_skills_command
        return handle_skills_command(self.core, arg)

    def _shared_handle_skill_command(self, arg):
        from agent.services.general_commands import handle_skill_command
        return handle_skill_command(self.core, arg)

    def _shared_handle_auto_command(self, arg):
        from agent.services.general_commands import handle_auto_command
        return handle_auto_command(self.core, arg)

    def _shared_handle_plan_command(self, arg):
        from agent.services.general_commands import handle_plan_command
        return handle_plan_command(self.core, arg)

    def _shared_handle_task_command(self, arg):
        from agent.services.general_commands import handle_task_command
        return handle_task_command(self.core, arg)

    def _shared_handle_execute_command(self, arg):
        from agent.services.general_commands import handle_execute_command
        return handle_execute_command(self.core, arg)

    def _shared_handle_switch_command(self, arg):
        from agent.services.general_commands import handle_switch_command
        return handle_switch_command(self.core, arg)

    # ── Phase C: LLM-analysis commands (real implementations) ───────
    # Moved from core.py — these only need self.core.generate_completion()
    # and self.core.safety_manager.

    def _shared_handle_summarize_command(self, arg):
        """Summarize text or code using LLM."""
        if not arg or not arg.strip():
            return "Usage: /summarize <text>"
        prompt = f"Summarize the following content concisely:\n\n{arg.strip()}"
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.3, max_tokens=1000)
            return f"📝 Summary:\n{response}"
        except Exception as e:
            return f"❌ Failed to generate summary: {e}"

    def _shared_handle_reason_command(self, arg):
        """Chain-of-thought reasoning using LLM."""
        if not arg or not arg.strip():
            return "Usage: /reason <problem>"
        prompt = f"Solve the following problem using step-by-step reasoning:\n\n{arg.strip()}"
        messages = [{"role": "user", "content": prompt}]
        try:
            original_model = self.core.model
            if "reason" not in original_model.lower():
                self.core.set_model("deepseek-reasoner")
                response = self.core.generate_completion(messages, temperature=0.3, max_tokens=2000)
                self.core.set_model(original_model)
            else:
                response = self.core.generate_completion(messages, temperature=0.3, max_tokens=2000)
            return f"🤔 Reasoning:\n{response}"
        except Exception as e:
            return f"❌ Failed to reason: {e}"

    def _shared_handle_debug_command(self, arg):
        """Debug code using LLM analysis."""
        import os
        if not arg or not arg.strip():
            return "Usage: /debug <file_path> or /debug <code snippet>"
        if os.path.exists(arg.strip()):
            safe, reason, content = self.core.safety_manager.safe_read_file(arg.strip())
            if not safe:
                return f"❌ Cannot read file: {reason}"
            code = content
            source = f"file: {arg.strip()}"
        else:
            code = arg.strip()
            source = "provided code"
        prompt = f"Debug the following code from {source}. Identify bugs, errors, and suggest fixes:\n\n```\n{code}\n```"
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.3, max_tokens=2000)
            return f"🐛 Debug analysis for {source}:\n{response}"
        except Exception as e:
            return f"❌ Failed to debug: {e}"

    def _shared_handle_explain_command(self, arg):
        """Explain code using LLM."""
        import os
        if not arg or not arg.strip():
            return "Usage: /explain <file_path> or /explain <code snippet>"
        if os.path.exists(arg.strip()):
            safe, reason, content = self.core.safety_manager.safe_read_file(arg.strip())
            if not safe:
                return f"❌ Cannot read file: {reason}"
            code = content
            source = f"file: {arg.strip()}"
        else:
            code = arg.strip()
            source = "provided code"
        prompt = f"Explain the following code from {source} in simple terms:\n\n```\n{code}\n```"
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.3, max_tokens=2000)
            return f"📚 Explanation of {source}:\n{response}"
        except Exception as e:
            return f"❌ Failed to explain: {e}"

    def _shared_handle_refactor_command(self, arg):
        """Suggest refactoring improvements using LLM."""
        import os
        if not arg or not arg.strip():
            return "Usage: /refactor <file_path>"
        file_path = arg.strip()
        if not os.path.exists(file_path):
            return f"❌ File not found: {file_path}"
        safe, reason, content = self.core.safety_manager.safe_read_file(file_path)
        if not safe:
            return f"❌ Cannot read file: {reason}"
        prompt = f"Suggest refactoring improvements for the following code. Focus on readability, performance, and maintainability:\n\n```\n{content}\n```"
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.3, max_tokens=2000)
            return f"🔧 Refactoring suggestions for {file_path}:\n{response}"
        except Exception as e:
            return f"❌ Failed to generate refactoring suggestions: {e}"

    def _shared_handle_translate_command(self, arg):
        """Translate text using LLM."""
        if not arg or not arg.strip():
            return "Usage: /translate <text> [to <language>]"
        text = arg.strip()
        target_language = "English"
        import re
        if " to " in text.lower():
            match = re.search(r'^(.*?) to (.+)$', text, re.IGNORECASE)
            if match:
                text = match.group(1).strip()
                target_language = match.group(2).strip()
        prompt = f"Translate the following text to {target_language}:\n\n{text}"
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.3, max_tokens=1000)
            return f"🌐 Translation to {target_language}:\n{response}"
        except Exception as e:
            return f"❌ Failed to translate: {e}"

    def _shared_handle_generate_command(self, arg):
        """Generate content using LLM."""
        if not arg or not arg.strip():
            return "Usage: /generate <prompt>"
        messages = [{"role": "user", "content": arg.strip()}]
        try:
            response = self.core.generate_completion(messages, temperature=0.7, max_tokens=2000)
            return f"🎨 Generated content:\n{response}"
        except Exception as e:
            return f"❌ Failed to generate content: {e}"

    # ── Phase C: Real implementations (moved from core.py) ─────────

    def _shared_handle_clear_command(self, arg):
        """Clear conversation history."""
        self.core.clear_history()
        return "🗑️ Conversation history cleared."

    def _shared_handle_history_command(self, arg):
        """Show conversation history."""
        history = self.core.conversation_history
        if not history:
            return "📭 No conversation history."
        result = ["📜 Conversation History:"]
        for i, msg in enumerate(history, 1):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            preview = content[:100] + "..." if len(content) > 100 else content
            result.append(f"{i}. [{role}] {preview}")
        return "\n".join(result)

    def _shared_handle_context_command(self, arg):
        from agent.services.general_commands import handle_context_command
        return handle_context_command(self.core, arg)

    def _shared_handle_think_command(self, arg):
        """Toggle thinking mode."""
        self.core.toggle_thinking_mode()
        status = "enabled" if self.core.thinking_enabled else "disabled"
        return f"🤔 Thinking mode {status}."

    def _shared_handle_verbose_command(self, arg):
        """Toggle verbose debug output."""
        cmd = arg.strip().lower() if arg else ""
        if cmd == "on":
            self.core.verbose_mode = True
            status = "ENABLED"
        elif cmd == "off":
            self.core.verbose_mode = False
            status = "DISABLED"
        elif cmd == "toggle" or cmd == "":
            self.core.toggle_verbose_mode()
            status = "TOGGLED"
        else:
            return f"❌ Invalid option: {cmd}. Use /verbose [on|off|toggle]"

        if self.core.verbose_mode and self.core.status_buffer:
            result = [f"🔊 Verbose mode: {status}", "📋 Recent debug messages:"]
            for entry in self.core.status_buffer[-10:]:
                result.append(f"  [{entry['level']}] {entry['message']}")
            return "\n".join(result)
        return f"🔊 Verbose mode: {status}"

    def _shared_handle_quit_command(self, arg):
        """Signal quit to CLI."""
        return "🛑 Quit command received. Use Ctrl+C or type /quit in the CLI to exit."

    def _shared_handle_exit_command(self, arg):
        """Alias for /quit."""
        return self._shared_handle_quit_command(arg)

    def _shared_handle_help_command(self, arg):
        """Show help — delegates to HelpSystem."""
        if hasattr(self.core, 'help_system') and self.core.help_system:
            return self.core.help_system.get_help(arg.strip() if arg else "")
        return "Help system not available."

    def _shared_handle_sprint_command(self, arg):
        from agent.services.workflow_commands import handle_sprint_command
        return handle_sprint_command(self.core, arg)

    def _shared_handle_careful_command(self, arg):
        from agent.services.workflow_commands import handle_careful_command
        return handle_careful_command(self.core, arg)

    def _shared_handle_freeze_command(self, arg):
        from agent.services.workflow_commands import handle_freeze_command
        return handle_freeze_command(self.core, arg)

    def _shared_handle_guard_command(self, arg):
        from agent.services.workflow_commands import handle_guard_command
        return handle_guard_command(self.core, arg)

    def _shared_handle_unfreeze_command(self, arg):
        from agent.services.workflow_commands import handle_unfreeze_command
        return handle_unfreeze_command(self.core, arg)

    def _shared_handle_evidence_command(self, arg):
        from agent.services.workflow_commands import handle_evidence_command
        return handle_evidence_command(self.core, arg)

    def _shared_handle_evolve_command(self, arg):
        from agent.services.workflow_commands import handle_evolve_command
        return handle_evolve_command(self.core, arg)

    def _shared_handle_dashboard_command(self, arg):
        from agent.services.workflow_commands import handle_dashboard_command
        return handle_dashboard_command(self.core, arg)

    def _shared_handle_upgrade_command(self, arg):
        from agent.services.workflow_commands import handle_upgrade_command
        return handle_upgrade_command(self.core, arg)

    # ── Architecture ──────────────────────────────────────────────

    def _shared_handle_arch_command(self, arg):
        """Generate or audit the architecture graph.

        Usage:
            /arch           — regenerate HTML + JSON + audit
            /arch audit     — audit only (no regeneration)
            /arch json      — output JSON only
        """
        import subprocess
        import os

        script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "scripts", "gen_architecture.py")

        if not os.path.exists(script):
            return self.core.formatter.error(
                "Architecture script not found at scripts/gen_architecture.py")

        cmd = ["python3", script]
        sub = (arg or "").strip().lower()
        if sub == "audit":
            cmd.append("--audit-only")
        elif sub == "json":
            cmd.append("--json")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))))
            )
            output = result.stdout.strip()
            if result.stderr:
                output += "\n" + result.stderr.strip()
            if result.returncode != 0:
                return self.core.formatter.error(
                    f"Architecture generation failed:\n{output}")
            return self.core.formatter.format_result(
                "Architecture Graph",
                output + "\n\nOpen plans/architecture_interactive.html to view."
            )
        except subprocess.TimeoutExpired:
            return self.core.formatter.error("Architecture generation timed out.")
        except Exception as e:
            return self.core.formatter.error(f"Error: {e}")

    # ── Web / Research commands (moved from Chat — all modes need web) ──

    def _shared_handle_read_command(self, arg):
        """Read file or URL content."""
        return self.core.handle_read_command(arg)

    def _shared_handle_links_command(self, arg):
        """Extract links from a URL."""
        from agent.web.web_commands import handle_links_command
        return handle_links_command(self.core, arg)

    def _shared_handle_crawl_command(self, arg):
        """Crawl a website starting from a URL."""
        from agent.web.web_commands import handle_crawl_command
        return handle_crawl_command(self.core, arg)

    def _shared_handle_webmap_command(self, arg):
        """Generate a site map from a URL."""
        from agent.web.web_commands import handle_webmap_command
        return handle_webmap_command(self.core, arg)

    def _shared_handle_logs_command(self, arg):
        """Browse application logs."""
        from agent.web.web_commands import handle_logs_command
        return handle_logs_command(self.core, arg)
