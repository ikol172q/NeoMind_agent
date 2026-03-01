# agent/core.py
import os
import json
import asyncio
from typing import Optional, Dict, List, Any
import requests
from bs4 import BeautifulSoup
import re
import os
import json
import asyncio
import re
import html
import time
import pathlib
import fnmatch
import hashlib
import warnings
import sys
import stat
from typing import Optional, Dict, List, Any, Set, Tuple, Callable
import requests
from urllib.parse import urlparse
try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    HAS_CHARDET = False
    chardet = None
from .code_analyzer import CodeAnalyzer
from .self_iteration import SelfIteration
from .task_manager import TaskManager
from .formatter import Formatter, success, error, warning, info, header, code_block, command_help
from .help_system import HelpSystem, get_help
from .command_executor import CommandExecutor, execute_safe, execute_git_safe
from .safety import SafetyManager, safe_read_file, safe_write_file, safe_delete_file, is_path_safe, log_operation
from .planner import Planner, plan_changes, GoalPlanner
from .context_manager import ContextManager, HAS_TIKTOKEN
import difflib  # Add this line to your imports

# Add to imports
import html
from urllib.parse import urlparse
try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    HAS_CHARDET = False
    chardet = None  # For auto-detecting encoding

from .search import OptimizedDuckDuckGoSearch
from .natural_language import NaturalLanguageInterpreter
from agent_config import agent_config

try:
    from requests_html import HTMLSession
    HAS_REQUESTS_HTML = True
except ImportError:
    HAS_REQUESTS_HTML = False
    HTMLSession = None

# Optional: For better article extraction
try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

# Optional: html2text for HTML to markdown conversion
try:
    import html2text
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False
    html2text = None

from .search import OptimizedDuckDuckGoSearch
from agent_config import agent_config

class DeepSeekStreamingChat:
    """Main DeepSeek agent with streaming, search, and model listing capabilities"""

    def __init__(self, api_key: Optional[str] = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        # CHANGED: Use agent_config instead of hardcoded values
        self.model = model if model != "deepseek-chat" else agent_config.model
        # Mode configuration
        self.mode = agent_config.mode  # chat or coding
        self.workspace_manager = None  # Lazy initialization for coding mode
        self.show_status_bar = agent_config.coding_mode_show_status_bar if agent_config.mode == "coding" else False
        # Status display system for coding mode
        self.verbose_mode = True if agent_config.mode == "coding" else False  # Show detailed debug messages in coding mode by default
        self.status_buffer = []  # Store debug/info messages for later display
        self.current_status = ""  # Current single-line status message
        self.last_status_update = 0  # Timestamp of last status update
        self._mcp_servers_cache = None  # Cache for MCP servers
        # https://api-docs.deepseek.com/quick_start/pricing
        self.base_url = "https://api.deepseek.com/chat/completions"
        self.models_url = "https://api.deepseek.com/models"  # NEW: For listing models
        self.conversation_history = []
        self.context_manager = ContextManager(self.conversation_history)
        self.thinking_enabled = agent_config.thinking_enabled  # CHANGED
        # Searcher with configurable auto-search triggers
        self.searcher = OptimizedDuckDuckGoSearch(triggers=agent_config.auto_search_triggers)
        # Formatter for consistent output
        self.formatter = Formatter()
        # Command executor for safe shell execution
        self.command_executor = CommandExecutor()
        # Self-iteration setup
        self.agent_root = os.path.dirname(os.path.abspath(__file__))
        # Safety manager for file operations (after agent_root is defined)
        self.safety_manager = SafetyManager(os.getcwd(), agent_root=self.agent_root)
        # Help system for command documentation
        self.help_system = HelpSystem()
        self.self_iteration = None  # Lazy initialization
        # Auto-features configuration
        self.enable_auto_search = agent_config.auto_search_enabled
        self.auto_search_enabled = agent_config.auto_search_enabled
        self.search_enabled = agent_config.search_enabled
        self.natural_language_enabled = agent_config.natural_language_enabled
        self.natural_language_confidence_threshold = agent_config.natural_language_confidence_threshold
        self.safety_confirm_file_operations = agent_config.safety_confirm_file_operations
        self.safety_confirm_code_changes = agent_config.safety_confirm_code_changes
        # Natural language interpreter
        self.interpreter = NaturalLanguageInterpreter(
            confidence_threshold=self.natural_language_confidence_threshold
        ) if self.natural_language_enabled else None
        self.search_loop = None
        self.available_models_cache = None  # NEW: Cache for available models
        self.available_models_cache_timestamp = 0  # NEW: Cache timestamp

        # NEW: Add system prompt if provided
        # Use coding mode system prompt if mode is coding, otherwise default
        if self.mode == "coding" and agent_config.coding_mode_system_prompt:
            self.add_to_history("system", agent_config.coding_mode_system_prompt)
        elif agent_config.system_prompt:
            self.add_to_history("system", agent_config.system_prompt)

        if not self.api_key:
            raise ValueError("API key is required. Set DEEPSEEK_API_KEY environment variable or pass it as argument.")
        # Initialize HTML-to-text converter if available
        if HAS_HTML2TEXT:
            self.html_converter = html2text.HTML2Text()
            self.html_converter.ignore_links = False
            self.html_converter.ignore_images = True
            self.html_converter.body_width = 0  # No width limit
        else:
            self.html_converter = None

        # Initialize optional renderer
        self.session = None
        if HAS_REQUESTS_HTML:
            try:
                self.session = HTMLSession()
            except:
                self.session = None

        # NEW: Code analyzer
        self.code_analyzer = None
        self.code_changes_pending = []  # Store proposed changes

        # Task manager for task tracking
        self.task_manager = TaskManager()
        # Goal planner for generating and executing plans
        self.goal_planner = GoalPlanner()

        # Command registry for unified routing
        self.command_handlers = {}
        self._setup_command_handlers()

    def _setup_command_handlers(self) -> None:
        """Initialize command handler registry."""
        # Mapping: prefix -> (handler, strip_prefix)
        self.command_handlers = {
            "/search": (self.handle_search, True),
            "/mode": (self.handle_mode_command, True),
            "/skills": (self.handle_skills_command, True),
            "/skill": (self.handle_skill_command, True),
            "/auto": (self.handle_auto_command, True),
            "/models": (self.handle_models_command, False),
            "/task": (self.handle_task_command, True),
            "/plan": (self.handle_plan_command, True),
            "/execute": (self.handle_execute_command, True),
            "/switch": (self.handle_switch_command, True),
            "/summarize": (self.handle_summarize_command, True),
            "/translate": (self.handle_translate_command, True),
            "/generate": (self.handle_generate_command, True),
            "/reason": (self.handle_reason_command, True),
            "/debug": (self.handle_debug_command, True),
            "/explain": (self.handle_explain_command, True),
            "/refactor": (self.handle_refactor_command, True),
            "/grep": (self.handle_grep_command, True),
            "/find": (self.handle_find_command, True),
            "/clear": (self.handle_clear_command, True),
            "/history": (self.handle_history_command, True),
            "/context": (self.handle_context_command, True),
            "/think": (self.handle_think_command, True),
            "/quit": (self.handle_quit_command, True),
            "/exit": (self.handle_exit_command, True),
            "/help": (self.handle_help_command, True),
            "/verbose": (self.handle_verbose_command, True),
            "/diff": (self.handle_diff_command, True),
            "/browse": (self.handle_browse_command, True),
            "/undo": (self.handle_undo_command, True),
            "/test": (self.handle_test_command, True),
            "/apply": (self.handle_apply_command, True),
            "/read": (self.handle_read_command, True),
            "/write": (self.handle_write_command, True),
            "/edit": (self.handle_edit_command, True),
            "/run": (self.handle_run_command, True),
            "/git": (self.handle_git_command, True),
            "/code": (self.handle_code_command, True),
            "/fix": (self.handle_auto_fix_command, False),
            "/analyze": (self.handle_auto_fix_command, False),
        }

    def _status_print(self, message: str, level: str = "info") -> None:
        """
        Print status message with verbosity control.

        Args:
            message: Message to print
            level: Message level - "critical", "important", "info", "debug"
        """
        import time

        # Store message in buffer for potential later display
        self.status_buffer.append({
            "timestamp": time.time(),
            "message": message,
            "level": level
        })
        # Keep buffer size manageable
        if len(self.status_buffer) > 100:
            self.status_buffer = self.status_buffer[-50:]

        # In coding mode with verbose mode disabled
        if self.mode == "coding" and not self.verbose_mode:
            if level in ("critical", "important"):
                # Show critical/important messages immediately
                self._safe_print(message)
            elif level == "info":
                # For info messages, update single-line status
                self.current_status = message
                # Use carriage return to update line (if output is a tty)
                import sys
                if sys.stdout.isatty():
                    # Clear line and print status
                    sys.stdout.write(f"\r\033[K{message}")
                    sys.stdout.flush()
                else:
                    # Non-interactive, just print
                    self._safe_print(message)
            # debug messages are silently stored in buffer
            return

        # In chat mode OR coding mode with verbose mode enabled
        self._safe_print(message)

    def add_status_message(self, message: str, level: str = "info") -> None:
        """Add a status message to the buffer without printing."""
        import time
        self.status_buffer.append({
            "timestamp": time.time(),
            "message": message,
            "level": level
        })
        # Keep buffer size manageable
        if len(self.status_buffer) > 100:
            self.status_buffer = self.status_buffer[-50:]

    def get_status_messages(self, level: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get status messages from buffer, optionally filtered by level and limited."""
        messages = self.status_buffer
        if level:
            messages = [msg for msg in messages if msg["level"] == level]
        # Reverse chronological order (most recent first)
        messages = list(reversed(messages))
        if limit:
            messages = messages[:limit]
        return messages

    def clear_status_buffer(self) -> None:
        """Clear all status messages from buffer."""
        self.status_buffer = []

    def update_current_status(self, status: str) -> None:
        """Update the current single-line status display."""
        import time
        self.current_status = status
        self.last_status_update = time.time()

    def _clear_status_line(self) -> None:
        """Clear the single-line status display if active."""
        import sys
        if self.current_status and sys.stdout.isatty():
            # Move to beginning of line, clear it
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
            self.current_status = ""

    def _safe_print(self, message: str) -> None:
        """Print message safely, handling Unicode encoding errors on Windows."""
        import sys
        # Clear any active status line before printing
        self._clear_status_line()
        try:
            print(message)
        except UnicodeEncodeError:
            # Fallback: replace common emojis with ASCII equivalents
            replacements = {
                "🔧": "[FIX]",
                "📝": "[NOTE]",
                "❌": "[ERROR]",
                "🌐": "[WEB]",
                "🚀": "[RUN]",
                "📁": "[DIR]",
                "⏱️": "[TIME]",
                "📤": "[OUT]",
                "🔍": "[SEARCH]",
                "💡": "[INFO]",
                "📄": "[FILE]",
                "📭": "[EMPTY]",
                "🔧": "[TOOL]",
                "📝": "[DOC]",
                "❌": "[FAIL]",
                "✅": "[OK]",
                "⚠️": "[WARN]",
                "⏳": "[WAIT]",
                "🔄": "[GIT]",
                "🧪": "[TEST]",
                "🤖": "[BOT]",
            }
            safe_message = message
            for emoji, ascii_repl in replacements.items():
                safe_message = safe_message.replace(emoji, ascii_repl)
            # Also strip any other non-ASCII characters
            safe_message = safe_message.encode('ascii', 'ignore').decode('ascii')
            print(safe_message)

    def switch_mode(self, mode: str, persist: bool = True) -> bool:
        """Switch between chat and coding modes.

        Args:
            mode: Target mode ('chat' or 'coding')
            persist: Whether to save the mode change to config file (default: True)
        """
        if mode not in ("chat", "coding"):
            self._safe_print(f"❌ Invalid mode: {mode}. Use 'chat' or 'coding'.")
            return False

        if persist:
            success = agent_config.update_mode(mode)
            if not success:
                self._safe_print("❌ Failed to update configuration.")
                return False

        old_mode = self.mode
        self.mode = mode
        self._safe_print(f"🔄 Switching from {old_mode} mode to {mode} mode.")

        # Update mode-specific settings
        if mode == "coding":
            self._initialize_workspace_manager()
            # Update system prompt to coding mode system prompt
            coding_prompt = agent_config.coding_mode_system_prompt
            if coding_prompt:
                # Clear existing system prompts
                self.conversation_history = [msg for msg in self.conversation_history if msg["role"] != "system"]
                self.add_to_history("system", coding_prompt)
            # Adjust natural language confidence threshold
            if self.interpreter:
                self.interpreter.confidence_threshold = agent_config.coding_mode_natural_language_confidence_threshold
            # Adjust safety confirmations for file operations
            self.safety_confirm_file_operations = agent_config.coding_mode_safety_confirm_file_operations
            # Show status bar
            self.show_status_bar = agent_config.coding_mode_show_status_bar
            # Enable verbose mode in coding mode by default
            self.verbose_mode = True
        else:
            # Restore default system prompt
            default_prompt = agent_config.system_prompt
            if default_prompt:
                self.conversation_history = [msg for msg in self.conversation_history if msg["role"] != "system"]
                self.add_to_history("system", default_prompt)
            # Restore default natural language confidence threshold
            if self.interpreter:
                self.interpreter.confidence_threshold = agent_config.natural_language_confidence_threshold
            # Restore default safety confirmations
            self.safety_confirm_file_operations = agent_config.safety_confirm_file_operations
            # Hide status bar
            self.show_status_bar = False
            # Disable verbose mode in chat mode (all messages shown anyway)
            self.verbose_mode = False

        return True

    def toggle_verbose_mode(self) -> bool:
        """Toggle verbose mode to show/hide detailed debug messages.
        Returns new verbose mode status."""
        self.verbose_mode = not self.verbose_mode
        return self.verbose_mode

    def get_status_info(self) -> Dict[str, any]:
        """Get current status information for status bar."""
        status = {
            "mode": self.mode,
            "token_usage": self.context_manager.count_conversation_tokens() if hasattr(self, 'context_manager') else 0,
            "pending_changes": len(self.code_changes_pending),
            "recent_files": []
        }
        if self.mode == "coding" and self.workspace_manager:
            try:
                status["recent_files"] = self.workspace_manager.get_recent_files(3)
            except:
                pass
        return status

    def _initialize_workspace_manager(self):
        """Lazy initialization of workspace manager for coding mode."""
        if self.workspace_manager is None:
            try:
                from .workspace_manager import WorkspaceManager
                self.workspace_manager = WorkspaceManager()
                self._safe_print("📁 Workspace manager initialized.")
            except ImportError:
                self._safe_print("⚠️  Workspace manager not available. Install optional dependencies.")
                self.workspace_manager = None

    # Add get_code_change_instructions method here:
    def get_code_change_instructions(self) -> str:
        """Instructions for AI to propose code changes"""
        return """
📝 HOW TO PROPOSE CODE CHANGES:

When you identify code that needs fixing, use this format:

PROPOSED CHANGE:
File: /path/to/file.py
Description: Brief description of the change
Old Code: [exact code to replace]
New Code: [replacement code]
Line: 42 (optional line number)

I will add this to pending changes and ask for user confirmation.

Available commands for the user:
• /code changes - View pending changes
• /code apply - Apply changes (with confirmation)
• /code clear - Clear pending changes
• /code scan - Scan a codebase
• /code read - Read a specific file
• /code analyze - Analyze file structure

Remember: Always ask for permission before making changes!
"""
    
    
    # NEW METHODS FOR MODEL LISTING
    def list_models(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        List all available DeepSeek models via API

        Args:
            force_refresh: If True, force refresh the model list cache

        Returns:
            List of model dictionaries with id, created, and owned_by fields
        """
        # Use cache if available and not forcing refresh
        if not force_refresh and self.available_models_cache:
            return self.available_models_cache

        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        try:
            response = requests.get(self.models_url, headers=headers, timeout=10)
            response.raise_for_status()

            models_data = response.json()
            if isinstance(models_data, dict) and "data" in models_data:
                self.available_models_cache = models_data["data"]
                return self.available_models_cache
            elif isinstance(models_data, list):
                self.available_models_cache = models_data
                return self.available_models_cache
            else:
                # Fallback to known models if API response is unexpected
                return self._get_fallback_models()

        except requests.exceptions.RequestException as e:
            print(f"Error fetching models: {e}")
            # Return fallback models on error
            return self._get_fallback_models()
    
    def _get_fallback_models(self) -> List[Dict[str, Any]]:
        """Return a list of fallback models when API call fails"""
        return [
            {"id": "deepseek-chat", "created": None, "owned_by": "deepseek"},
            {"id": "deepseek-coder", "created": None, "owned_by": "deepseek"},
            {"id": "deepseek-reasoner", "created": None, "owned_by": "deepseek"}
        ]
    
    def print_models(self, force_refresh: bool = False) -> None:
        """
        Print available models in a formatted way

        Args:
            force_refresh: If True, force refresh the model list
        """
        models = self.list_models(force_refresh)

        print("\n" + "="*60)
        print("AVAILABLE DEEPSEEK MODELS")
        print("="*60)

        if not models:
            print("No models found or failed to fetch model list.")
            return

        # Group models by type for better display
        chat_models = []
        coder_models = []
        other_models = []
        
        for model in models:
            model_id = model.get("id", "").lower()

            if "chat" in model_id:
                chat_models.append(model)
            elif "coder" in model_id or "code" in model_id:
                coder_models.append(model)
            else:
                other_models.append(model)

        # Print in sections
        if chat_models:
            print("\n📝 CHAT MODELS:")
            for model in chat_models:
                print(f"  • {model['id']}")
        
        if coder_models:
            print("\n💻 CODER MODELS:")
            for model in coder_models:
                print(f"  • {model['id']}")
        
        if other_models:
            self._safe_print("\n🔧 OTHER MODELS:")
            for model in other_models:
                print(f"  • {model['id']}")

        print("\n" + "-"*60)
        print(f"Current model: {self.model}")
        print(f"Total models available: {len(models)}")
        print("="*60 + "\n")

    def set_model(self, model_id: str) -> bool:
        """
        Switch to a different model

        Args:
            model_id: The model ID to switch to

        Returns:
            True if model was switched successfully, False otherwise
        """
        models = self.list_models()
        available_ids = [m["id"] for m in models]

        if model_id in available_ids:
            old_model = self.model
            self.model = model_id

            # Update configuration file
            try:
                from agent_config import agent_config
                success = agent_config.update_value("agent.model", model_id)
                if success:
                    print(f"✓ Model switched from '{old_model}' to '{model_id}' (saved to config)")
                else:
                    print(f"✓ Model switched from '{old_model}' to '{model_id}' (but failed to save config)")
            except ImportError:
                print(f"✓ Model switched from '{old_model}' to '{model_id}' (config update failed: agent_config not found)")

            return True
        else:
            print(f"✗ Model '{model_id}' not found. Available models:")
            self.print_models()
            return False

    def with_model(self, model_id: str, func: Callable, *args, **kwargs):
        """
        Temporarily switch to a model, execute a function, then restore original model.
        Does NOT update configuration file.

        Args:
            model_id: Model ID to temporarily switch to
            func: Callable to execute with temporary model
            *args, **kwargs: Passed to func

        Returns:
            Result of func call
        """
        models = self.list_models()
        available_ids = [m["id"] for m in models]
        if model_id not in available_ids:
            raise ValueError(f"Model '{model_id}' not available")

        original_model = self.model
        try:
            if self.model != model_id:
                self.model = model_id
                # Optionally notify user
                print(f"[Model] Temporarily switched to '{model_id}' for this task")
            result = func(*args, **kwargs)
        finally:
            if self.model != original_model:
                self.model = original_model
                print(f"[Model] Restored model to '{original_model}'")
        return result

    def generate_completion(self, messages, temperature=0.7, max_tokens=2048):
        """Generate a completion using the current model (non-streaming)."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        # Context validation
        temp_context = ContextManager(messages)
        total_tokens = temp_context.count_conversation_tokens()
        max_context = agent_config.max_context_tokens
        if total_tokens + max_tokens > max_context:
            # Reduce max_tokens to fit within limit, but keep at least 1
            new_max = max(1, max_context - total_tokens)
            self._status_print(f"⚠️  Context limit: reducing max_tokens from {max_tokens} to {new_max}", "info")
            max_tokens = new_max
        elif total_tokens > agent_config.context_warning_threshold * max_context:
            self._status_print(f"⚠️  Context warning: {total_tokens}/{max_context} tokens used", "info")

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.thinking_enabled:
            payload["thinking"] = {"type": "enabled"}

        try:
            import requests
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            if "choices" in result and result["choices"]:
                return result["choices"][0]["message"]["content"]
            else:
                raise ValueError("Unexpected response format")
        except Exception as e:
            return f"Error generating completion: {str(e)}"

    # Updated stream_response to handle /models command
    def handle_search(self, query: str) -> str:
        """Procedddddss search command and return results"""
        if not self.search_enabled:
            return "Search is disabled. Enable it in config or use a different search method."
        if not query or query.strip() == "":
            return "Usage: /search <your query>"

        success, result = self.searcher.search(query.strip())
        if success:
            self.add_search_results_to_history('web', query.strip(), result)
        else:
            # Add error to history as system message
            self.add_to_history("system", f"Web search failed for '{query.strip()}': {result}")
        return result

    def handle_auto_command(self, subcommand: str) -> Optional[str]:
        """
        Handle /auto command for controlling auto-features.
        Subcommands:
          search on/off     - Toggle auto-search
          interpret on/off  - Toggle natural language interpretation
          status           - Show current auto-feature settings
        """
        subcommand = subcommand.strip().lower()
        parts = subcommand.split()
        if not parts:
            return self._show_auto_status()

        if parts[0] == 'search' and len(parts) == 2:
            value = parts[1]
            if value in ('on', 'enable', 'true'):
                self.auto_search_enabled = True
                success = agent_config.update_value("agent.auto_features.auto_search.enabled", True)
                return f"Auto-search enabled {'(config saved)' if success else '(config save failed)'}"
            elif value in ('off', 'disable', 'false'):
                self.auto_search_enabled = False
                success = agent_config.update_value("agent.auto_features.auto_search.enabled", False)
                return f"Auto-search disabled {'(config saved)' if success else '(config save failed)'}"
            else:
                return "Usage: /auto search on|off"

        elif parts[0] == 'interpret' and len(parts) == 2:
            value = parts[1]
            if value in ('on', 'enable', 'true'):
                self.natural_language_enabled = True
                if not self.interpreter:
                    self.interpreter = NaturalLanguageInterpreter(
                        confidence_threshold=self.natural_language_confidence_threshold
                    )
                success = agent_config.update_value("agent.auto_features.natural_language.enabled", True)
                return f"Natural language interpretation enabled {'(config saved)' if success else '(config save failed)'}"
            elif value in ('off', 'disable', 'false'):
                self.natural_language_enabled = False
                self.interpreter = None
                success = agent_config.update_value("agent.auto_features.natural_language.enabled", False)
                return f"Natural language interpretation disabled {'(config saved)' if success else '(config save failed)'}"
            else:
                return "Usage: /auto interpret on|off"

        elif parts[0] == 'status':
            return self._show_auto_status()

        elif parts[0] == 'help':
            return self._show_auto_help()

        else:
            return self._show_auto_help()

    def _show_auto_status(self) -> str:
        """Return status of auto-features."""
        status_lines = []
        status_lines.append("🤖 Auto-feature Status:")
        status_lines.append(f"  • Auto-search: {'ENABLED' if self.auto_search_enabled else 'DISABLED'}")
        status_lines.append(f"  • Natural language interpretation: {'ENABLED' if self.natural_language_enabled else 'DISABLED'}")
        if self.interpreter:
            status_lines.append(f"  • Confidence threshold: {self.interpreter.confidence_threshold}")
        status_lines.append(f"  • Safety confirmations: File ops={self.safety_confirm_file_operations}, Code changes={self.safety_confirm_code_changes}")
        return "\n".join(status_lines)

    def _show_auto_help(self) -> str:
        """Return help for /auto command."""
        help_lines = []
        help_lines.append("🤖 /auto command usage:")
        help_lines.append("  /auto search on|off      - Enable/disable auto-search")
        help_lines.append("  /auto interpret on|off   - Enable/disable natural language interpretation")
        help_lines.append("  /auto status            - Show current auto-feature settings")
        help_lines.append("  /auto help              - Show this help")
        return "\n".join(help_lines)

    def handle_mode_command(self, command: str) -> Optional[str]:
        """
        Handle /mode command for switching between chat and coding modes.

        Usage:
          /mode chat      - Switch to chat mode
          /mode coding    - Switch to coding mode
          /mode status    - Show current mode
          /mode help      - Show help
        """
        command = command.strip().lower()
        if not command or command == "status":
            return f"Current mode: {self.mode}"
        elif command == "chat":
            success = self.switch_mode("chat")
            return "Switched to chat mode." if success else "Failed to switch to chat mode."
        elif command == "coding":
            success = self.switch_mode("coding")
            return "Switched to coding mode." if success else "Failed to switch to coding mode."
        elif command == "help":
            return (
                "/mode command usage:\n"
                "  /mode chat      - Switch to chat mode\n"
                "  /mode coding    - Switch to coding mode\n"
                "  /mode status    - Show current mode\n"
                "  /mode help      - Show this help"
            )
        else:
            return "Invalid mode. Use 'chat', 'coding', 'status', or 'help'."

    def handle_skills_command(self, command: str) -> Optional[str]:
        """
        Handle /skills command to list available skills/MCP servers.

        Usage:
          /skills list    - List available skills
          /skills refresh - Refresh skill discovery
          /skills help    - Show help
        """
        command = command.strip().lower()
        if not command or command == "list":
            skills = self.discover_mcp_servers()
            if not skills:
                return "No skills or MCP servers found."
            result = ["Available skills:"]
            for skill in skills:
                result.append(f"  - {skill['name']} - {skill.get('description', 'No description')}")
            return "\n".join(result)
        elif command == "refresh":
            # Force rediscovery
            self._mcp_servers_cache = None
            return "Skill cache cleared. Use /skills list to refresh."
        elif command == "help":
            return (
                "/skills command usage:\n"
                "  /skills list    - List available skills\n"
                "  /skills refresh - Refresh skill discovery\n"
                "  /skills help    - Show this help"
            )
        else:
            return "Unknown subcommand. Use 'list', 'refresh', or 'help'."

    def handle_skill_command(self, command: str) -> Optional[str]:
        """
        Handle /skill command to invoke a specific skill.

        Usage:
          /skill <skill_name> [args...]
        """
        parts = command.strip().split(maxsplit=1)
        if not parts:
            return "Usage: /skill <skill_name> [args...]"
        skill_name = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        # For now, just return a placeholder
        return f"Skill '{skill_name}' invocation not yet implemented. Args: '{args}'"

    def discover_mcp_servers(self) -> List[Dict[str, str]]:
        """
        Discover MCP servers in standard locations.

        Returns:
            List of server info dictionaries
        """
        # Placeholder implementation
        # In a real implementation, this would scan ~/.claude/mcp-servers/
        # and ./.claude/mcp-servers/ for server configurations
        servers = []
        # Check for common MCP server locations
        import os
        import json
        from pathlib import Path

        locations = [
            Path.home() / ".claude" / "mcp-servers",
            Path.cwd() / ".claude" / "mcp-servers",
        ]

        for location in locations:
            if location.exists() and location.is_dir():
                for item in location.iterdir():
                    if item.is_file() and item.suffix == '.json':
                        try:
                            with open(item, 'r') as f:
                                config = json.load(f)
                            servers.append({
                                'name': config.get('name', item.stem),
                                'description': config.get('description', ''),
                                'path': str(item)
                            })
                        except:
                            pass

        # Add built-in skills
        builtin_skills = [
            {'name': 'code_analyzer', 'description': 'Code analysis and refactoring'},
            {'name': 'file_operations', 'description': 'File read/write/edit'},
            {'name': 'web_search', 'description': 'Web search via DuckDuckGo'},
        ]
        servers.extend(builtin_skills)

        return servers

    def handle_models_command(self, command: str) -> Optional[str]:
        """
        Handle /models command with various subcommands

        Args:
            command: The full command string (e.g., "/models list", "/models switch deepseek-chat")
        
        Returns:
            Response message or None
        """
        parts = command.split()
        
        if len(parts) == 1:  # Just "/models"
            self.print_models()
            return None
        elif len(parts) >= 2:
            subcommand = parts[1].lower()

            if subcommand in ["list", "show", "ls"]:
                self.print_models(force_refresh=len(parts) > 2 and parts[2] == "--refresh")
                return None
            elif subcommand in ["switch", "use", "set"]:
                # Handle: /models switch <model> (agent)
                #         /models switch agent <model>
                if len(parts) == 3:
                    # /models switch <model> - default to agent
                    model_id = parts[2]
                    success = self.set_model(model_id)
                    return "Model switched successfully." if success else "Failed to switch model."
                elif len(parts) == 4:
                    target = parts[2].lower()
                    model_id = parts[3]
                    if target in ["agent", "a"]:
                        success = self.set_model(model_id)
                        return "Model switched successfully." if success else "Failed to switch model."
                    else:
                        print(f"Unknown target: {target}. Use 'agent'.")
                        print("Usage: /models switch [agent] <model_id>")
                        return None
                else:
                    print("Usage: /models switch [agent] <model_id>")
                    print("Examples:")
                    print("  /models switch deepseek-reasoner          # Switch model")
                    print("  /models switch agent deepseek-reasoner    # Switch model (explicit)")
                    return None
            elif subcommand in ["current", "active"]:
                print(f"\nCurrent model: {self.model}")
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

    def handle_task_command(self, command: str) -> Optional[str]:
        """
        Handle /task command for task management.
        Subcommands:
          create <description> - Create a new task
          list [status]        - List tasks (optional status filter: todo, in_progress, done)
          update <id> <status> - Update task status
          delete <id>          - Delete task
          clear                - Delete all tasks
        """
        if not command.strip():
            return self._show_task_help()

        parts = command.strip().split()
        subcommand = parts[0].lower()

        if subcommand == "create":
            if len(parts) < 2:
                return "Usage: /task create <description>"
            description = " ".join(parts[1:])
            task = self.task_manager.create_task(description)
            return f"✅ Task created with ID: {task.id}\nDescription: {task.description}"

        elif subcommand == "list":
            status_filter = None
            if len(parts) > 1:
                status_filter = parts[1].lower()
                if status_filter not in ("todo", "in_progress", "done"):
                    return f"Invalid status filter '{status_filter}'. Use: todo, in_progress, done"
            tasks = self.task_manager.list_tasks(status_filter)
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
            success = self.task_manager.update_task_status(task_id, new_status)
            if success:
                return f"✅ Task {task_id} updated to '{new_status}'"
            else:
                return f"❌ Task {task_id} not found"

        elif subcommand == "delete":
            if len(parts) != 2:
                return "Usage: /task delete <task_id>"
            task_id = parts[1]
            success = self.task_manager.delete_task(task_id)
            if success:
                return f"✅ Task {task_id} deleted"
            else:
                return f"❌ Task {task_id} not found"

        elif subcommand == "clear":
            if len(parts) != 1:
                return "Usage: /task clear"
            count = self.task_manager.clear_all_tasks()
            return f"✅ Cleared {count} tasks"

        elif subcommand in ("help", "?"):
            return self._show_task_help()

        else:
            return f"Unknown subcommand: {subcommand}\n{self._show_task_help()}"

    def _show_task_help(self) -> str:
        """Return help for /task command."""
        help_lines = [
            "📋 /task command usage:",
            "  /task create <description>      - Create a new task",
            "  /task list [status]             - List tasks (optional status filter)",
            "  /task update <id> <status>      - Update task status (todo, in_progress, done)",
            "  /task delete <id>               - Delete task",
            "  /task clear                     - Delete all tasks",
            "  /task help                      - Show this help",
            "",
            "Examples:",
            "  /task create \"Refactor auth module\"",
            "  /task list",
            "  /task list in_progress",
            "  /task update abc123 done",
        ]
        return "\n".join(help_lines)

    def handle_plan_command(self, command: str) -> Optional[str]:
        """
        Handle /plan command for generating and managing plans.
        Subcommands:
          <goal>               - Generate a plan for a goal
          list [status]        - List plans (optional status filter)
          delete <id>          - Delete plan
          show <id>            - Show plan details
        """
        if not command.strip():
            return self._show_plan_help()

        parts = command.strip().split()
        # If first part is not a known subcommand, treat as goal
        if parts[0].lower() not in ("list", "delete", "show", "help"):
            goal = command.strip()
            plan = self.goal_planner.generate_plan(goal, self)
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
            plans = self.goal_planner.list_plans(status_filter)
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
            success = self.goal_planner.delete_plan(plan_id)
            if success:
                return f"✅ Plan {plan_id} deleted"
            else:
                return f"❌ Plan {plan_id} not found"

        elif subcommand == "show":
            if len(parts) != 2:
                return "Usage: /plan show <plan_id>"
            plan_id = parts[1]
            plan = self.goal_planner.get_plan(plan_id)
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
            return self._show_plan_help()

        else:
            return f"Unknown subcommand: {subcommand}\n{self._show_plan_help()}"

    def _show_plan_help(self) -> str:
        """Return help for /plan command."""
        help_lines = [
            "📋 /plan command usage:",
            "  /plan <goal>                 - Generate a plan for a goal",
            "  /plan list [status]          - List plans (optional status filter)",
            "  /plan delete <id>            - Delete plan",
            "  /plan show <id>              - Show plan details",
            "  /plan help                   - Show this help",
            "",
            "Status filters: pending, in_progress, completed, failed",
            "",
            "Examples:",
            "  /plan \"Add user authentication\"",
            "  /plan list",
            "  /plan show abc123",
        ]
        return "\n".join(help_lines)

    def handle_execute_command(self, command: str) -> Optional[str]:
        """
        Handle /execute command to execute a plan.
        Usage: /execute <plan_id>
        """
        if not command.strip():
            return "Usage: /execute <plan_id>"

        parts = command.strip().split()
        if len(parts) != 1:
            return "Usage: /execute <plan_id>"

        plan_id = parts[0]
        plan = self.goal_planner.get_plan(plan_id)
        if not plan:
            return f"❌ Plan {plan_id} not found"

        # Update plan status to in_progress if pending
        if plan.get("status") == "pending":
            self.goal_planner.update_plan_status(plan_id, "in_progress")

        current_step = self.goal_planner.get_current_step(plan_id)
        if not current_step:
            # No more steps, plan completed
            self.goal_planner.update_plan_status(plan_id, "completed")
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
        result.append("You can use commands like /write, /run, /git, etc.")
        result.append(f"After completing, run /execute {plan_id} again to advance to next step.")
        return "\n".join(result)

    def handle_switch_command(self, command: str) -> Optional[str]:
        """
        Handle /switch command to switch model.
        Usage: /switch <model_id>
        """
        if not command.strip():
            return "Usage: /switch <model_id>"

        model_id = command.strip()
        success = self.set_model(model_id)
        if success:
            return f"✅ Switched model to {model_id}"
        else:
            return f"❌ Failed to switch model to {model_id}"

    def handle_summarize_command(self, command: str) -> Optional[str]:
        """
        Handle /summarize command to summarize text or code.
        Usage: /summarize <text>
        """
        if not command.strip():
            return "Usage: /summarize <text>"

        text = command.strip()
        prompt = f"Summarize the following content concisely:\n\n{text}"
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.generate_completion(messages, temperature=0.3, max_tokens=1000)
            return f"📝 Summary:\n{response}"
        except Exception as e:
            return f"❌ Failed to generate summary: {e}"

    def handle_translate_command(self, command: str) -> Optional[str]:
        """
        Handle /translate command to translate text.
        Usage: /translate <text> [to <language>]
        Default language: English
        """
        if not command.strip():
            return "Usage: /translate <text> [to <language>]"

        # Parse language (simple)
        parts = command.strip().split()
        text = command
        target_language = "English"

        # Look for "to" keyword
        if " to " in command.lower():
            # Simple split on " to "
            import re
            match = re.search(r'^(.*?) to (.+)$', command, re.IGNORECASE)
            if match:
                text = match.group(1).strip()
                target_language = match.group(2).strip()

        prompt = f"Translate the following text to {target_language}:\n\n{text}"
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.generate_completion(messages, temperature=0.3, max_tokens=1000)
            return f"🌐 Translation to {target_language}:\n{response}"
        except Exception as e:
            return f"❌ Failed to translate: {e}"

    def handle_generate_command(self, command: str) -> Optional[str]:
        """
        Handle /generate command to generate content.
        Usage: /generate <prompt>
        """
        if not command.strip():
            return "Usage: /generate <prompt>"

        prompt = command.strip()
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.generate_completion(messages, temperature=0.7, max_tokens=2000)
            return f"🎨 Generated content:\n{response}"
        except Exception as e:
            return f"❌ Failed to generate content: {e}"

    def handle_reason_command(self, command: str) -> Optional[str]:
        """
        Handle /reason command for chain-of-thought reasoning.
        Usage: /reason <problem>
        """
        if not command.strip():
            return "Usage: /reason <problem>"

        problem = command.strip()
        prompt = f"Solve the following problem using step-by-step reasoning:\n\n{problem}"
        messages = [{"role": "user", "content": prompt}]
        try:
            # Temporarily switch to reasoning model if available
            original_model = self.model
            if "reason" not in original_model.lower():
                # Try to switch to a reasoning model
                self.set_model("deepseek-reasoner")
                response = self.generate_completion(messages, temperature=0.3, max_tokens=2000)
                # Switch back
                self.set_model(original_model)
            else:
                response = self.generate_completion(messages, temperature=0.3, max_tokens=2000)
            return f"🤔 Reasoning:\n{response}"
        except Exception as e:
            return f"❌ Failed to reason: {e}"

    def handle_debug_command(self, command: str) -> Optional[str]:
        """
        Handle /debug command to debug code.
        Usage: /debug <file_path> or /debug <code snippet>
        """
        if not command.strip():
            return "Usage: /debug <file_path> or /debug <code snippet>"

        # Check if argument is a file path
        import os
        if os.path.exists(command.strip()):
            # Read file
            safe, reason, content = self.safety_manager.safe_read_file(command.strip())
            if not safe:
                return f"❌ Cannot read file: {reason}"
            code = content
            source = f"file: {command.strip()}"
        else:
            code = command.strip()
            source = "provided code"

        prompt = f"Debug the following code from {source}. Identify bugs, errors, and suggest fixes:\n\n```\n{code}\n```"
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.generate_completion(messages, temperature=0.3, max_tokens=2000)
            return f"🐛 Debug analysis for {source}:\n{response}"
        except Exception as e:
            return f"❌ Failed to debug: {e}"

    def handle_explain_command(self, command: str) -> Optional[str]:
        """
        Handle /explain command to explain code.
        Usage: /explain <file_path> or /explain <code snippet>
        """
        if not command.strip():
            return "Usage: /explain <file_path> or /explain <code snippet>"

        import os
        if os.path.exists(command.strip()):
            safe, reason, content = self.safety_manager.safe_read_file(command.strip())
            if not safe:
                return f"❌ Cannot read file: {reason}"
            code = content
            source = f"file: {command.strip()}"
        else:
            code = command.strip()
            source = "provided code"

        prompt = f"Explain the following code from {source} in simple terms:\n\n```\n{code}\n```"
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.generate_completion(messages, temperature=0.3, max_tokens=2000)
            return f"📚 Explanation of {source}:\n{response}"
        except Exception as e:
            return f"❌ Failed to explain: {e}"

    def handle_refactor_command(self, command: str) -> Optional[str]:
        """
        Handle /refactor command to suggest refactoring improvements.
        Usage: /refactor <file_path>
        """
        if not command.strip():
            return "Usage: /refactor <file_path>"

        file_path = command.strip()
        import os
        if not os.path.exists(file_path):
            return f"❌ File not found: {file_path}"

        safe, reason, content = self.safety_manager.safe_read_file(file_path)
        if not safe:
            return f"❌ Cannot read file: {reason}"

        prompt = f"Suggest refactoring improvements for the following code. Focus on readability, performance, and maintainability:\n\n```\n{content}\n```"
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.generate_completion(messages, temperature=0.3, max_tokens=2000)
            return f"🔧 Refactoring suggestions for {file_path}:\n{response}"
        except Exception as e:
            return f"❌ Failed to generate refactoring suggestions: {e}"

    def handle_grep_command(self, command: str) -> Optional[str]:
        """
        Handle /grep command to search for text across files.
        Usage: /grep <pattern> [path]
        """
        if not command.strip():
            return "Usage: /grep <pattern> [path]"

        parts = command.strip().split()
        pattern = parts[0]
        path = parts[1] if len(parts) > 1 else "."

        # Use ripgrep if available, else Python regex
        try:
            import subprocess
            result = subprocess.run(
                ["rg", "-n", "-i", pattern, path],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                output = result.stdout
                if not output.strip():
                    return f"🔍 No matches for pattern '{pattern}' in {path}"
                return f"🔍 Grep results for '{pattern}' in {path}:\n{output}"
            else:
                # Fallback to Python regex
                return self._grep_fallback(pattern, path)
        except (subprocess.SubprocessError, FileNotFoundError):
            return self._grep_fallback(pattern, path)

    def _grep_fallback(self, pattern: str, path: str) -> str:
        """Fallback grep using Python regex."""
        import os
        import re
        matches = []
        pattern_re = re.compile(pattern, re.IGNORECASE)
        for root, dirs, files in os.walk(path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_num, line in enumerate(f, 1):
                            if pattern_re.search(line):
                                matches.append(f"{file_path}:{line_num}: {line.rstrip()}")
                except:
                    continue
        if not matches:
            return f"🔍 No matches for pattern '{pattern}' in {path}"
        return f"🔍 Grep results for '{pattern}' in {path} (Python fallback):\n" + "\n".join(matches[:50])  # Limit output

    def handle_find_command(self, command: str) -> Optional[str]:
        """
        Handle /find command to find files matching pattern.
        Usage: /find <pattern> [path]
        """
        if not command.strip():
            return "Usage: /find <pattern> [path]"

        parts = command.strip().split()
        pattern = parts[0]
        path = parts[1] if len(parts) > 1 else "."

        import os
        import fnmatch
        matches = []
        for root, dirs, files in os.walk(path):
            for name in files + dirs:
                if fnmatch.fnmatch(name, pattern):
                    full_path = os.path.join(root, name)
                    matches.append(full_path)
        if not matches:
            return f"📭 No files/directories matching '{pattern}' in {path}"
        return f"📂 Found {len(matches)} matches for '{pattern}' in {path}:\n" + "\n".join(matches[:50])

    def handle_verbose_command(self, command: str) -> Optional[str]:
        """
        Handle /verbose command to toggle verbose debug output.
        Usage: /verbose [on|off|toggle]
        """
        cmd = command.strip().lower()
        if cmd == "on":
            self.verbose_mode = True
            status = "ENABLED"
        elif cmd == "off":
            self.verbose_mode = False
            status = "DISABLED"
        elif cmd == "toggle" or cmd == "":
            self.toggle_verbose_mode()
            status = "TOGGLED"
        else:
            return f"❌ Invalid option: {cmd}. Use /verbose [on|off|toggle]"

        if self.verbose_mode and self.status_buffer:
            result = [f"🔊 Verbose mode: {status}", "📋 Recent debug messages:"]
            for entry in self.status_buffer[-10:]:  # Show last 10 messages
                result.append(f"  [{entry['level']}] {entry['message']}")
            return "\n".join(result)
        return f"🔊 Verbose mode: {status}"

    def handle_clear_command(self, command: str) -> Optional[str]:
        """
        Handle /clear command to clear conversation history.
        Usage: /clear
        """
        self.clear_history()
        return "🗑️ Conversation history cleared."

    def handle_history_command(self, command: str) -> Optional[str]:
        """
        Handle /history command to show conversation history.
        Usage: /history
        """
        if not self.conversation_history:
            return "📭 No conversation history."

        result = ["📜 Conversation History:"]
        for i, msg in enumerate(self.conversation_history, 1):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            preview = content[:100] + "..." if len(content) > 100 else content
            result.append(f"{i}. [{role}] {preview}")
        return "\n".join(result)

    def handle_context_command(self, command: str) -> Optional[str]:
        """
        Handle /context command to manage conversation context.
        Usage: /context [status|compress|clear|help]
        """
        command = command.strip().lower()
        if not command or command == "status":
            stats = self.context_manager.get_context_usage()
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
            result = self.context_manager.compress_history()
            return f"✅ Compressed history: {result['original_tokens']} → {result['compressed_tokens']} tokens (-{result['token_reduction']})"
        elif command == "clear":
            self.conversation_history.clear()
            self._ensure_system_prompt()
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

    def handle_think_command(self, command: str) -> Optional[str]:
        """
        Handle /think command to toggle thinking mode.
        Usage: /think
        """
        self.toggle_thinking_mode()
        status = "enabled" if self.thinking_enabled else "disabled"
        return f"🤔 Thinking mode {status}."

    def handle_quit_command(self, command: str) -> Optional[str]:
        """
        Handle /quit command to exit (signal to CLI).
        Usage: /quit or /exit
        """
        # Return special message that CLI can interpret
        return "🛑 Quit command received. Use Ctrl+C or type /quit in the CLI to exit."

    def handle_exit_command(self, command: str) -> Optional[str]:
        """
        Handle /exit command (alias for /quit).
        """
        return self.handle_quit_command(command)

    # NEW: Webpage reading capabilities

    def read_webpage(self, url: str, max_length: int = 20000) -> str:
        """
        Read webpage content using multiple strategies for maximum compatibility
        """
        # Normalize URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        print(f"🌐 Fetching: {url}")

        # Try multiple strategies in order
        # Try multiple strategies in order
        strategies = []
        if HAS_TRAFILATURA:
            strategies.append(self._try_trafilatura)
        strategies.append(self._try_beautifulsoup)
        if HAS_HTML2TEXT:
            strategies.append(self._try_html2text)
        if HAS_REQUESTS_HTML:
            strategies.append(self._try_requests_html)
        strategies.append(self._try_fallback)
        
        best_result = None
        best_score = 0

        for strategy in strategies:
            try:
                content = strategy(url, max_length)
                if content:
                    # Score the content quality
                    score = self._score_content(content)
                    if score > best_score:
                        best_result = content
                        best_score = score

                    # If we have good content, stop trying
                    if score > 50:  # Good enough threshold
                        break
            except Exception as e:
                continue  # Try next strategy

        if best_result:
            return self._format_result(url, best_result, best_score)
        else:
            return self.formatter.error(f"Failed to extract content from {url}. All strategies failed.")

    def _try_trafilatura(self, url: str, max_length: int) -> Optional[str]:
        """Try using trafilatura with encoding handling"""
        if not HAS_TRAFILATURA:
            return None

        try:
            downloaded = trafilatura.fetch_url(url)
            text = trafilatura.extract(
                downloaded,
                include_links=False,
                include_images=False,
                include_tables=False,
                no_fallback=False,
                include_formatting=False,  # Cleaner output
                output_format='txt',       # Plain text
            )

            if text:
                # Clean the text
                text = self._clean_text(text)

            return text
        except:
            return None

    def _try_beautifulsoup(self, url: str, max_length: int) -> Optional[str]:
        """Try BeautifulSoup extraction with proper encoding handling"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
                'Accept-Charset': 'utf-8, iso-8859-1, utf-16, *;q=0.7',
            }

            # Special headers for specific sites
            if 'github.com' in url:
                headers['Accept'] = 'application/vnd.github.v3+json'
            elif 'bilibili.com' in url:
                headers['Referer'] = 'https://www.bilibili.com'
                headers['Accept-Charset'] = 'utf-8, gb2312, gbk, *;q=0.7'

            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            # Detect encoding
            encoding = None

            # 1. Check HTTP header
            if response.encoding:
                encoding = response.encoding.lower()

            # 2. Check HTML meta tag
            soup_for_encoding = BeautifulSoup(response.content[:5000], 'html.parser')
            meta_charset = soup_for_encoding.find('meta', charset=True)
            if meta_charset:
                encoding = meta_charset['charset'].lower()
            else:
                meta_http_equiv = soup_for_encoding.find('meta', attrs={'http-equiv': 'Content-Type'})
                if meta_http_equiv and 'content' in meta_http_equiv.attrs:
                    content_value = meta_http_equiv['content'].lower()
                    if 'charset=' in content_value:
                        encoding = content_value.split('charset=')[1].split(';')[0].strip()

            # 3. Use chardet as fallback
            if not encoding:
                detected = chardet.detect(response.content)
                encoding = detected.get('encoding', 'utf-8').lower()

            # Normalize encoding names
            encoding_map = {
                'gb2312': 'gbk',
                'gbk': 'gbk',
                'gb18030': 'gb18030',
                'big5': 'big5',
                'shift_jis': 'shift_jis',
                'euc-jp': 'euc-jp',
                'utf-8': 'utf-8',
                'utf8': 'utf-8',
                'ascii': 'utf-8',
            }

            encoding = encoding_map.get(encoding, 'utf-8')

            # Decode with proper encoding
            try:
                content = response.content.decode(encoding, errors='replace')
            except (UnicodeDecodeError, LookupError):
                # Try UTF-8 as fallback
                content = response.content.decode('utf-8', errors='replace')

            # Now parse with BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')

            # Remove unwanted elements
            for tag in ['script', 'style', 'nav', 'footer', 'header', 
                       'aside', 'form', 'iframe', 'noscript', 'svg']:
                for element in soup.find_all(tag):
                    element.decompose()

            # Try to find main content first
            main_selectors = [
                'main', 'article', '[role="main"]', '.main-content',
                '.content', '.post-content', '.article-content',
                '#content', '.markdown-body',  # GitHub
                '.video-info', '.video-desc',   # Bilibili
            ]

            main_content = None
            for selector in main_selectors:
                main_content = soup.select_one(selector)
                if main_content:
                    break

            if main_content:
                text = main_content.get_text(separator='\n', strip=True)
            else:
                # Fallback to body
                body = soup.find('body')
                text = body.get_text(separator='\n', strip=True) if body else ""

            # Clean the text
            text = self._clean_text(text)

            return text.strip()
        except Exception as e:
            print(f"Debug: BeautifulSoup error for {url}: {str(e)}")
            return None

    def _try_html2text(self, url: str, max_length: int) -> Optional[str]:
        """Try html2text conversion with encoding handling"""
        if not HAS_HTML2TEXT or self.html_converter is None:
            return None
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            # Detect encoding
            try:
                detected = chardet.detect(response.content)
                encoding = detected.get('encoding', 'utf-8').lower()
                content = response.content.decode(encoding, errors='replace')
            except:
                content = response.content.decode('utf-8', errors='replace')

            # Configure html2text for better Chinese support
            self.html_converter.unicode_snob = True  # Use Unicode
            self.html_converter.escape_snob = False  # Don't escape
            self.html_converter.links_each_paragraph = False
            self.html_converter.body_width = 0  # No width limit

            # Convert HTML to markdown-like text
            text = self.html_converter.handle(content)

            # Clean the text
            text = self._clean_text(text)

            return text.strip()
        except:
            return None

    def _try_requests_html(self, url: str, max_length: int) -> Optional[str]:
        """Try JavaScript rendering for dynamic sites"""
        if not self.session:
            return None

        try:
            r = self.session.get(url, timeout=20)
            # Render JavaScript (adjust timeout based on site)
            render_timeout = 30 if 'bilibili.com' in url else 15
            r.html.render(timeout=render_timeout, sleep=2)

            # Try to get text
            text = r.html.text

            # Clean up
            text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
            return text.strip()
        except:
            return None

    def _try_fallback(self, url: str, max_length: int) -> Optional[str]:
        """Last resort fallback"""
        try:
            response = requests.get(url, timeout=10)
            # Try to extract text between tags
            text = re.sub(r'<[^>]+>', ' ', response.text)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()
        except:
            return None

    def _score_content(self, content: str) -> int:
        """Score content quality (0-100) with language checking"""
        if not content:
            return 0

        # First, clean the content
        content = self._clean_text(content)

        score = 0

        # Check for valid text (not just gibberish)
        # Count Chinese characters
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', content))
        # Count English words (basic detection)
        english_words = len(re.findall(r'\b[a-zA-Z]{2,}\b', content))

        # Penalize if there are weird character sequences
        weird_sequences = len(re.findall(r'[Ã©äåçèéêëìíîïðñòóôõöøùúûüýþÿ]', content))
        if weird_sequences > len(content) * 0.1:  # More than 10% weird chars
            return 0  # Definitely gibberish

        # If we have both Chinese and English, that's good
        if chinese_chars > 10 and english_words > 10:
            score += 30
        elif chinese_chars > 20:
            score += 25
        elif english_words > 20:
            score += 25
        else:
            # Might not be meaningful content
            return 10

        # Length score (more content is better)
        length = len(content)
        if length > 1000:
            score += 40
        elif length > 500:
            score += 20
        elif length > 100:
            score += 10

        # Sentence structure score
        sentences = re.findall(r'[.!?。！？]+', content)
        if len(sentences) > 5:
            score += 30

        return min(score, 100)

    def _format_result(self, url: str, content: str, score: int) -> str:
        """Format the final result with language info"""
        if len(content) > 20000:
            content = content[:20000] + f"\n\n[Content truncated. Original: {len(content)} chars]"
        
        # Clean content one more time
        content = self._clean_text(content)

        # Get page title if possible
        title = "Unknown Title"
        try:
            response = requests.get(url, timeout=5)
            soup = BeautifulSoup(response.content, 'html.parser')
            if soup.title and soup.title.string:
                title = self._clean_text(soup.title.string.strip())
        except:
            pass

        # Detect language
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', content))
        english_words = len(re.findall(r'\b[a-zA-Z]{3,}\b', content))

        if chinese_chars > english_words:
            language = "中文 (Chinese)"
        elif english_words > chinese_chars:
            language = "English"
        else:
            language = "Mixed/Unknown"
        
        # Quality indicator
        quality = "🟢 High" if score > 70 else "🟡 Medium" if score > 40 else "🔴 Low"
        
        result = f"""📄 PAGE: {title}
🔗 URL: {url}
🌐 Language: {language}
📊 Quality: {quality} ({score}/100)
📏 Length: {len(content)} characters
{"-" * 60}

{content}

{"-" * 60}
✅ End of content from: {url}"""
        
        return result
    
    def _clean_text(self, text: str) -> str:
        """
        Clean text by fixing encoding issues, removing HTML entities, and normalizing
        """
        if not text:
            return ""
        
        # 1. Unescape HTML entities (convert &lt; to <, etc.)
        text = html.unescape(text)

        # 2. Fix common encoding issues
        # Replace common mojibake patterns
        replacements = {
            'Ã¡': 'á', 'Ã©': 'é', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ',
            'Ã': 'Á', 'Ã': 'É', 'Ã': 'Ó', 'Ã': 'Ú', 'Ã': 'Ñ',
            'Ã¤': 'ä', 'Ã«': 'ë', 'Ã¶': 'ö', 'Ã¼': 'ü', 'Ã': 'ß',
            'Ã': 'Ä', 'Ã': 'Ë', 'Ã': 'Ö', 'Ã': 'Ü',
            'â€™': "'", 'â€œ': '"', 'â€': '"', 'â€"': '-', 'â€¢': '•',
            'â€¦': '…', 'â€"': '—', 'â€"': '–',
            'Â': ' ',  # Remove extra spaces from UTF-8 BOM issues
        }

        for wrong, correct in replacements.items():
            text = text.replace(wrong, correct)
        
        # 3. Remove control characters and excessive whitespace
        # Remove non-printable characters except common whitespace
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        
        # 4. Normalize line endings and whitespace
        text = re.sub(r'\r\n', '\n', text)  # Windows to Unix
        text = re.sub(r'\r', '\n', text)    # Old Mac to Unix
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Multiple blank lines
        text = re.sub(r'[ \t]{2,}', ' ', text)        # Multiple spaces/tabs

        # 5. Clean up specific patterns
        # Remove HTML comments
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        # Remove inline JavaScript
        text = re.sub(r'javascript:', '', text, flags=re.IGNORECASE)
        # Remove data URLs
        text = re.sub(r'data:[^ ]+;base64,[^ ]+', '', text)

        # 6. Preserve Chinese and other Unicode characters
        # Keep Chinese, Japanese, Korean characters and common punctuation
        text = re.sub(r'[^\u0000-\uFFFF]', '', text)  # Remove non-BMP characters if any

        # 7. Remove empty lines at start/end
        text = text.strip()

        return text

    def handle_read_command(self, url_or_command: str) -> str:
        """
        Handle /read command for webpage reading with enhanced capabilities
        Automatically adds content to conversation history for AI awareness
        """
        if not url_or_command or url_or_command.strip() == "":
            help_text = """
    📚 /read Command Usage:
    /read <url>                     - Read webpage content and make AI aware of it
    /read <file_path>               - Read local file (supports line ranges: file.py:10-20)
    /read --debug <url>            - Show debugging info (doesn't add to AI memory)
    /read --strategy <n> <url>     - Use specific strategy (0-4)
    /read --no-ai <url|file>       - Read without adding to AI memory

    Strategies (for webpages only):
    0: trafilatura (best for articles)
    1: beautifulsoup (smart extraction)
    2: html2text (markdown conversion)
    3: requests-html (JavaScript sites)
    4: fallback (basic extraction)

    Note: By default, all content is added to AI memory so you can ask questions about it.
            """.strip()
            return help_text

        parts = url_or_command.split()

        # Parse flags
        debug = False
        strategy = None
        no_ai = False  # New flag to prevent adding to AI memory
        url = None

        # Parse flags
        i = 0
        while i < len(parts):
            if parts[i] == '--debug':
                debug = True
                parts.pop(i)
            elif parts[i] == '--strategy':
                if i + 1 < len(parts):
                    try:
                        strategy = int(parts[i + 1])
                        parts.pop(i)  # Remove --strategy
                        parts.pop(i)  # Remove the number
                    except ValueError:
                        return self.formatter.error(f"Invalid strategy number. Must be 0-4.")
                else:
                    return self.formatter.error("Missing strategy number. Use: /read --strategy <0-4> <url>")
            elif parts[i] == '--no-ai':
                no_ai = True
                parts.pop(i)
            else:
                i += 1

        # The remaining parts should form the URL
        if not parts:
            return self.formatter.error("Please provide a URL")
        
        url = ' '.join(parts)

        # Check if this is a local file path
        if self._is_likely_file_path(url):
            return self._handle_file_read(url, no_ai)

        print(f"🌐 Processing: {url}")
        
        if debug:
            # Run all strategies and show results
            results = []
            strategies = []
            if HAS_TRAFILATURA:
                strategies.append(("trafilatura", self._try_trafilatura))
            strategies.append(("beautifulsoup", self._try_beautifulsoup))
            if HAS_HTML2TEXT:
                strategies.append(("html2text", self._try_html2text))
            if HAS_REQUESTS_HTML:
                strategies.append(("requests-html", self._try_requests_html))
            strategies.append(("fallback", self._try_fallback))

            best_content = None
            best_score = 0

            for name, strategy_func in strategies:
                try:
                    content = strategy_func(url, 5000)
                    if content:
                        score = self._score_content(content)
                        results.append(f"{name}: {score}/100, {len(content)} chars")
                        if score > best_score:
                            best_content = content
                            best_score = score
                except Exception as e:
                    results.append(f"{name}: ERROR - {str(e)}")

            if best_content:
                debug_info = "\n".join(results)
                final_result = self._format_result(url, best_content, best_score)
                return f"🔍 Debug Results:\n{debug_info}\n\n{final_result}"
            else:
                return self.formatter.error(f"All strategies failed for {url}")
        
        elif strategy is not None:
            # Use specific strategy
            strategies = [
                self._try_trafilatura,
                self._try_beautifulsoup,
                self._try_html2text,
                self._try_requests_html,
                self._try_fallback,
            ]

            if 0 <= strategy < len(strategies):
                content = strategies[strategy](url, 20000)
                if content:
                    score = self._score_content(content)
                    formatted_content = self._format_result(url, content, score)

                    # Add to conversation history unless --no-ai flag is set
                    if not no_ai:
                        self._add_webpage_to_memory(url, content)

                    return formatted_content
                else:
                    return self.formatter.error(f"Strategy {strategy} failed to extract content")
            else:
                return self.formatter.error(f"Invalid strategy number. Use 0-{len(strategies)-1}")

        else:
            # Normal reading with best strategy (default behavior)
            content = self.read_webpage(url)

            # Add to conversation history unless --no-ai flag is set
            if not no_ai:
                self._add_webpage_to_memory(url, content)
            
            return content

    def _read_interactive_content(self, prompt: str = "Enter content (end with EOF: Ctrl+D on Unix, Ctrl+Z on Windows):") -> str:
        """Read multiline content from stdin until EOF."""
        import sys
        lines = []
        if sys.stdin.isatty():
            print(prompt)
            print("Type your content line by line. Press Ctrl+D (Unix) or Ctrl+Z (Windows) when done.")
        try:
            for line in sys.stdin:
                lines.append(line)
        except KeyboardInterrupt:
            print("\nInput interrupted.")
            return ""
        return "".join(lines)

    def handle_write_command(self, command: str) -> str:
        """
        Handle /write command for creating or overwriting files.

        Usage:
          /write <file_path> [content]   - Write content to file (content optional)
          /write --interactive <file_path> - Enter content interactively

        If content is not provided, reads from stdin until EOF (Ctrl+D on Unix, Ctrl+Z on Windows).
        """
        if not command or command.strip() == "":
            help_text = """
📝 /write Command Usage:
  /write <file_path> [content]   - Write content to file
  /write --interactive <file_path> - Enter content interactively (end with EOF)

Examples:
  /write hello.txt "Hello World"
  /write script.py "print('hello')"
  /write --interactive notes.md
            """.strip()
            return help_text

        # Auto-switch to coding mode for write command
        if self.mode != 'coding':
            self.switch_mode('coding', persist=False)

        # Parse flags
        interactive = False
        parts = command.split()
        # Check for --interactive flag
        if parts[0] == '--interactive':
            interactive = True
            parts.pop(0)

        if not parts:
            return self.formatter.error("Please provide a file path")

        file_path = parts[0]
        content = ' '.join(parts[1:]) if len(parts) > 1 else ""

        # If interactive mode or no content provided, read from stdin
        if interactive or not content:
            content = self._read_interactive_content()
            if not content:
                return self.formatter.warning("No content provided. File not written.")

        # Ensure code analyzer is initialized
        if not self.code_analyzer:
            self.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=self.safety_manager)

        # Write file
        success, message = self.code_analyzer.write_file_safe(file_path, content)
        if success:
            return self.formatter.success(message)
        else:
            return self.formatter.error(message)

    def handle_edit_command(self, command: str) -> str:
        """
        Handle /edit command for editing files with code changes.

        Usage:
          /edit <file_path> "<old_code>" "<new_code>" [--description "desc"]
          /edit --help

        Examples:
          /edit test.py "print('hello')" "print('Hello World')"
        """
        import shlex
        import os
        from .code_analyzer import CodeAnalyzer
        if not command or command.strip() == "":
            help_text = """
📝 /edit Command Usage:
  /edit <file_path> "<old_code>" "<new_code>"   - Replace old code with new code
  /edit --help                                  - Show this help

Examples:
  /edit script.py "print('old')" "print('new')"
  /edit script.py "def old():" "def new():"
            """.strip()
            return help_text

        # Auto-switch to coding mode for edit command
        if self.mode != 'coding':
            self.switch_mode('coding', persist=False)

        # Parse flags
        parts = []
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return self.formatter.error(f"Invalid command syntax: {e}")

        if not parts:
            return self.formatter.error("Please provide a file path")

        file_path = parts[0]
        description = "Manual edit via /edit command"
        line = None
        old_code = ""
        new_code = ""

        # Parse flags
        i = 1
        while i < len(parts):
            if parts[i] == '--description':
                if i + 1 < len(parts):
                    description = parts[i + 1]
                    i += 2
                else:
                    return self.formatter.error("Missing description after --description")
            else:
                # Treat as old_code and new_code positional arguments
                if i + 1 < len(parts):
                    old_code = parts[i]
                    new_code = parts[i + 1]
                    i += 2
                else:
                    return self.formatter.error("Need both old_code and new_code arguments")
                break  # No more flags after positional args

        # Ensure we have old_code and new_code
        if not old_code or not new_code:
            return self.formatter.error("Missing old_code or new_code")

        # Initialize code analyzer if needed
        if not self.code_analyzer:
            self.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=self.safety_manager)

        # Validate change
        is_valid, error_msg = self.validate_proposed_change(old_code, new_code, file_path)
        if not is_valid:
            return self.formatter.error(f"Change validation failed: {error_msg}")

        # Propose change
        result = self.propose_code_change(file_path, old_code, new_code, description, line)
        return result

    def handle_run_command(self, command: str) -> str:
        """
        Handle /run command for executing shell commands safely.

        Usage:
          /run <command> [args...]

        Example:
          /run ls -la
          /run python --version
        """
        if not command or command.strip() == "":
            help_text = """
🔧 /run Command Usage:
  /run <command> [args...]   - Execute a shell command safely

Examples:
  /run ls -la
  /run python --version
  /run echo "Hello"
            """.strip()
            return help_text

        # Auto-switch to coding mode for run command
        if self.mode != 'coding':
            self.switch_mode('coding', persist=False)

        # Determine working directory
        import os
        cwd = os.getcwd()
        if self.code_analyzer:
            cwd = self.code_analyzer.root_path

        # Execute using command executor
        result = self.command_executor.execute(command, cwd=cwd)
        # Log command execution
        log_operation('execute', command, result['success'],
                     f"cwd={cwd}, exit_code={result['returncode']}, time={result['execution_time']:.2f}s")

        # Format result using formatter
        if not result['success']:
            return self.formatter.error(result['error_message'])

        # Build formatted output
        output = f"🚀 Command: {command}\n"
        output += f"📁 Working directory: {cwd}\n"
        output += f"⏱️  Execution time: {result['execution_time']:.2f}s\n"
        output += f"📤 Exit code: {result['returncode']}\n"

        if result['stdout']:
            output += f"\n📤 STDOUT:\n{result['stdout'].rstrip()}\n"
        if result['stderr']:
            output += f"\n📤 STDERR:\n{result['stderr'].rstrip()}\n"

        if result['returncode'] == 0:
            output += f"\n{self.formatter.success('Command completed successfully.')}"
        else:
            output += f"\n{self.formatter.warning('Command failed (non-zero exit code).')}"

        return output

    def handle_git_command(self, command: str) -> str:
        """
        Handle /git command for version control operations.

        Usage:
          /git <subcommand> [args...]

        Examples:
          /git status
          /git diff
          /git log --oneline -5
          /git commit -m "message"
          /git push origin main
        """
        if not command or command.strip() == "":
            help_text = """
🔄 /git Command Usage:
  /git <subcommand> [args...]   - Execute git command safely

Common subcommands:
  status, diff, log, commit, push, pull, branch, checkout, clone, init

Examples:
  /git status
  /git diff
  /git log --oneline -5
  /git commit -m "message"
  /git push origin main
            """.strip()
            return help_text

        # Auto-switch to coding mode for git command
        if self.mode != 'coding':
            self.switch_mode('coding', persist=False)

        # Determine working directory
        import os
        cwd = os.getcwd()
        if self.code_analyzer:
            cwd = self.code_analyzer.root_path

        # Execute using command executor's git-specific method
        result = self.command_executor.execute_git(command, cwd=cwd)

        # Format result using formatter
        if not result['success']:
            return self.formatter.error(result['error_message'])

        # Build formatted output
        output = f"🔄 Git command: git {command}\n"
        output += f"📁 Working directory: {cwd}\n"
        output += f"⏱️  Execution time: {result['execution_time']:.2f}s\n"
        output += f"📤 Exit code: {result['returncode']}\n"

        if result['stdout']:
            output += f"\n📤 STDOUT:\n{result['stdout'].rstrip()}\n"
        if result['stderr']:
            output += f"\n📤 STDERR:\n{result['stderr'].rstrip()}\n"

        if result['returncode'] == 0:
            output += f"\n{self.formatter.success('Git command completed successfully.')}"
        else:
            output += f"\n{self.formatter.warning('Git command failed (non-zero exit code).')}"

        return output

    def handle_help_command(self, command: str = "") -> str:
        """
        Handle /help command.
        Usage: /help [command]
        Examples:
          /help          - Show all available commands
          /help write    - Show detailed help for /write command
        """
        help_texts = {
            "write": """
📝 /write Command:
  /write <file_path> [content]   - Write content to file
  /write --interactive <file_path> - Enter content interactively

Examples:
  /write hello.txt "Hello World"
  /write script.py "print('hello')"
""",
            "edit": """
📝 /edit Command:
  /edit <file_path> "<old_code>" "<new_code>"   - Replace old code with new code

Examples:
  /edit script.py "print('old')" "print('new')"
""",
            "read": """
📚 /read Command:
  /read <url>                     - Read webpage content
  /read <file_path>               - Read local file (supports line ranges)
  /read --debug <url>            - Show debugging info
  /read --strategy <n> <url>     - Use specific strategy (0-4)
""",
            "run": """
🔧 /run Command:
  /run <command> [args...]   - Execute a shell command safely

Examples:
  /run ls -la
  /run python --version
""",
            "git": """
🔄 /git Command:
  /git <subcommand> [args...]   - Execute git command safely

Common subcommands: status, diff, log, commit, push, pull, branch, checkout
""",
            "code": """
📁 /code Command:
  /code scan [path]              - Scan codebase
  /code summary                  - Show codebase summary
  /code find <pattern>          - Find files matching pattern
  /code read <file_path>        - Read and analyze a file
  /code analyze <file_path>     - Analyze file structure
  /code search <text>           - Search for text in code
  /code changes                 - Show pending changes
  /code apply                   - Apply pending changes
  /code clear                   - Clear pending changes
  /code self-scan              - Scan agent's own codebase
  /code self-improve <feature> - Suggest improvements
  /code self-apply             - Apply self-improvements safely
""",
            "search": """
🔍 /search Command:
  /search <query>   - Search the web using DuckDuckGo
""",
            "models": """
🤖 /models Command:
  /models list      - List available DeepSeek models
  /models switch <model> - Switch to a different model
""",
            "fix": """
🔧 /fix Command:
  /fix <file_path> [description] - Automatically fix code issues
""",
            "analyze": """
🔬 /analyze Command:
  /analyze <file_path> - Analyze code for issues and suggest improvements
""",
            "diff": """
📝 /diff Command:
  /diff <file1> <file2>        - Compare two files
  /diff --git <file>           - Show git diff for file
  /diff --backup <file>        - Compare with latest backup

Examples:
  /diff old.py new.py
  /diff --git agent/core.py
""",
            "browse": """
📁 /browse Command:
  /browse [path]              - Browse directory (default: current)
  /browse --details [path]    - Show detailed listing with sizes
  /browse --filter <ext>      - Filter by extension (e.g., .py)

Examples:
  /browse
  /browse agent/
  /browse --details src/
""",
            "undo": """
↩️ /undo Command:
  /undo list [n]              - List recent changes (default: 5)
  /undo last                  - Revert last change
  /undo <change_id>           - Revert specific change by index

Examples:
  /undo list
  /undo last
  /undo 2
""",
            "test": """
🧪 /test Command:
  /test                       - Run basic development tests (dev_test.py)
  /test unit                  - Run unit tests (if available)
  /test all                   - Run all available tests

Examples:
  /test
  /test unit
""",
            "apply": """
🔧 /apply Command (alias for /code apply):
  /apply              - Apply pending changes with confirmation
  /apply force        - Apply without interactive confirmation
  /apply confirm      - Apply with confirmation (same as /apply)

Note: This is an alias for /code apply.
""",
        }

        if not command:
            # Show all commands
            result = "🤖 Available Commands:\n\n"
            for cmd in sorted(help_texts.keys()):
                # Extract first line of each help text
                first_line = help_texts[cmd].strip().split('\n')[0]
                result += f"{first_line}\n"
            result += "\n💡 Use /help <command> for detailed usage."
            return result
        else:
            cmd = command.strip().lower()
            if cmd in help_texts:
                return help_texts[cmd].strip()
            else:
                return self.formatter.error(f"No help available for '{command}'. Available commands: {', '.join(sorted(help_texts.keys()))}")

    def handle_diff_command(self, command: str) -> str:
        """Handle /diff command.

        Usage:
          /diff <file1> <file2>        - Compare two files
          /diff --git <file>           - Show git diff for file
          /diff --backup <file>        - Compare with latest backup

        Examples:
          /diff old.py new.py
          /diff --git agent/core.py
        """
        if not command or command.strip() == "":
            help_text = """
📝 /diff Command Usage:
  /diff <file1> <file2>        - Compare two files
  /diff --git <file>           - Show git diff for file
  /diff --backup <file>        - Compare with latest backup
  /diff --help                 - Show this help

Examples:
  /diff old.py new.py
  /diff --git agent/core.py
            """.strip()
            return help_text

        parts = command.split()
        if parts[0] == '--git':
            # Git diff implementation
            if len(parts) < 2:
                return self.formatter.error("Please specify a file for git diff")
            file_path = parts[1]
            try:
                import subprocess
                result = subprocess.run(
                    ['git', 'diff', file_path],
                    capture_output=True,
                    text=True,
                    cwd=os.getcwd()
                )
                if result.stdout:
                    return f"🔀 Git diff for {file_path}:\n\n{result.stdout}"
                else:
                    return f"📭 No changes for {file_path} in git"
            except Exception as e:
                return self.formatter.error(f"Error running git diff: {str(e)}")
        elif parts[0] == '--backup':
            # Compare with backup
            if len(parts) < 2:
                return self.formatter.error("Please specify a file for backup comparison")
            file_path = parts[1]
            # Find latest backup
            backup_dir = os.path.join(self.safety_manager.workspace_root, '.safety_backups')
            if not os.path.exists(backup_dir):
                return f"📭 No backup directory found at {backup_dir}"
            base_name = os.path.basename(file_path)
            import glob
            pattern = os.path.join(backup_dir, f"{base_name}.backup_*")
            backups = glob.glob(pattern)
            if not backups:
                return f"📭 No backups found for {file_path}"
            # Extract timestamp from filename: {base}.backup_{timestamp}
            def extract_timestamp(path):
                import re
                match = re.search(r'\.backup_(\d+)$', os.path.basename(path))
                return int(match.group(1)) if match else 0
            latest_backup = max(backups, key=extract_timestamp)
            # Read backup content
            safe, reason, backup_content = self.safety_manager.safe_read_file(latest_backup)
            if not safe:
                return f"❌ Cannot read backup file {latest_backup}: {reason}"
            # Read current file
            if not self.code_analyzer:
                self.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=self.safety_manager)
            success, msg, current_content = self.code_analyzer.read_file_safe(file_path)
            if not success:
                return self.formatter.error(f"Cannot read {file_path}: {msg}")
            # Generate diff
            lines1 = backup_content.splitlines(keepends=True)
            lines2 = current_content.splitlines(keepends=True)
            diff = difflib.unified_diff(
                lines1, lines2,
                fromfile=f"backup: {os.path.basename(latest_backup)}",
                tofile=f"current: {file_path}",
                lineterm=''
            )
            diff_result = ''.join(diff)
            if diff_result:
                return f"🔀 Diff between backup and current {file_path}:\n\n{diff_result}"
            else:
                return self.formatter.success(f"File {file_path} is identical to latest backup")
        else:
            # Compare two files
            if len(parts) < 2:
                return self.formatter.error("Please specify two files to compare")
            file1, file2 = parts[0], parts[1]
            try:
                # Read both files
                if not self.code_analyzer:
                    self.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=self.safety_manager)
                success1, msg1, content1 = self.code_analyzer.read_file_safe(file1)
                success2, msg2, content2 = self.code_analyzer.read_file_safe(file2)
                if not success1:
                    return self.formatter.error(f"Cannot read {file1}: {msg1}")
                if not success2:
                    return self.formatter.error(f"Cannot read {file2}: {msg2}")

                # Generate diff
                lines1 = content1.splitlines(keepends=True)
                lines2 = content2.splitlines(keepends=True)
                diff = difflib.unified_diff(
                    lines1, lines2,
                    fromfile=file1,
                    tofile=file2,
                    lineterm=''
                )
                diff_result = ''.join(diff)
                if diff_result:
                    return f"🔀 Diff between {file1} and {file2}:\n\n{diff_result}"
                else:
                    return self.formatter.success(f"Files {file1} and {file2} are identical")
            except Exception as e:
                return self.formatter.error(f"Error comparing files: {str(e)}")

    def handle_browse_command(self, command: str) -> str:
        """Handle /browse command.

        Usage:
          /browse [path]              - Browse directory (default: current)
          /browse --details [path]    - Show detailed listing
          /browse --filter <ext>      - Filter by extension (e.g., .py)
          /browse --help              - Show help

        Examples:
          /browse
          /browse agent/
          /browse --details src/
          /browse --filter .py
        """
        if not command or command.strip() == "":
            path = os.getcwd()
        else:
            path = command.strip()

        # Parse flags
        details = False
        filter_ext = None
        parts = path.split()
        actual_path = os.getcwd()

        i = 0
        while i < len(parts):
            if parts[i] == '--details':
                details = True
                parts.pop(i)
            elif parts[i] == '--filter':
                if i + 1 < len(parts):
                    filter_ext = parts[i + 1]
                    parts.pop(i)  # Remove --filter
                    parts.pop(i)  # Remove the extension
                else:
                    return self.formatter.error("Missing extension after --filter")
            elif parts[i] == '--help':
                help_text = """
📁 /browse Command Usage:
  /browse [path]              - Browse directory (default: current)
  /browse --details [path]    - Show detailed listing with sizes
  /browse --filter <ext>      - Filter by extension (e.g., .py)
  /browse --help              - Show this help

Examples:
  /browse                     # Browse current directory
  /browse agent/              # Browse agent directory
  /browse --details src/      # Detailed listing of src/
  /browse --filter .py        # Show only Python files
                """.strip()
                return help_text
            else:
                # This is the path
                if i == len(parts) - 1:  # Last part
                    actual_path = parts[i]
                    if not os.path.isabs(actual_path):
                        actual_path = os.path.join(os.getcwd(), actual_path)
                i += 1

        # If no path specified and we consumed all parts with flags
        if actual_path is None:
            actual_path = os.getcwd()

        try:
            if not os.path.exists(actual_path):
                return self.formatter.error(f"Path does not exist: {actual_path}")
            if not os.path.isdir(actual_path):
                return self.formatter.error(f"Not a directory: {actual_path}")

            # List directory
            items = os.listdir(actual_path)

            # Separate directories and files
            dirs = []
            files = []
            for item in items:
                item_path = os.path.join(actual_path, item)
                if os.path.isdir(item_path):
                    dirs.append(item)
                else:
                    if filter_ext and not item.endswith(filter_ext):
                        continue
                    files.append(item)

            # Sort
            dirs.sort()
            files.sort()

            # Build result
            result = f"📁 Directory: {actual_path}\n"
            result += f"📊 Items: {len(dirs)} directories, {len(files)} files"
            if filter_ext:
                result += f" (filtered: *{filter_ext})"
            result += "\n\n"

            # Show directories
            if dirs:
                result += "📂 Directories:\n"
                for d in dirs[:20]:  # Limit to 20
                    result += f"  • {d}/\n"
                if len(dirs) > 20:
                    result += f"  ... and {len(dirs) - 20} more directories\n"
                result += "\n"

            # Show files
            if files:
                result += "📄 Files:\n"
                for f in files[:30]:  # Limit to 30
                    if details:
                        try:
                            size = os.path.getsize(os.path.join(actual_path, f))
                            size_str = f"{size:,} bytes"
                            if size > 1024:
                                size_str = f"{size/1024:.1f} KB"
                            result += f"  • {f} ({size_str})\n"
                        except:
                            result += f"  • {f}\n"
                    else:
                        result += f"  • {f}\n"
                if len(files) > 30:
                    result += f"  ... and {len(files) - 30} more files\n"

            result += f"\n💡 Use '/browse --details {actual_path}' for detailed listing"
            result += f"\n💡 Use '/read {actual_path}/<file>' to read a file"

            return result
        except Exception as e:
            return self.formatter.error(f"Error browsing directory: {str(e)}")

    def handle_undo_command(self, command: str) -> str:
        """Handle /undo command.

        Usage:
          /undo list [n]              - List recent changes (default: 5)
          /undo last                  - Revert last change
          /undo <change_id>           - Revert specific change by index
          /undo --help                - Show help

        Change ID is shown in /undo list output.
        """
        if not command or command.strip() == "":
            command = "list 5"

        parts = command.split()
        action = parts[0].lower()

        if action == '--help':
            help_text = """
↩️ /undo Command Usage:
  /undo list [n]              - List recent changes (default: 5)
  /undo last                  - Revert last change
  /undo <change_id>           - Revert specific change by index
  /undo --help                - Show this help

Examples:
  /undo list                 # List 5 most recent changes
  /undo list 10              # List 10 most recent changes
  /undo last                 # Revert last change
  /undo 2                    # Revert change with ID 2
            """.strip()
            return help_text

        if action == 'list':
            limit = 5
            if len(parts) > 1:
                try:
                    limit = int(parts[1])
                except ValueError:
                    return self.formatter.error(f"Invalid limit: {parts[1]}")

            si = self._get_self_iteration()
            changes = si.get_change_history(limit=limit)
            if not changes:
                return "📭 No change history found."

            result = f"📜 Recent Changes (last {len(changes)}):\n\n"
            for i, change in enumerate(changes):
                timestamp = change.get('timestamp', 0)
                dt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
                file_path = change.get('file_path', 'unknown')
                desc = change.get('description', 'No description')
                backup = change.get('backup', 'No backup')
                result += f"{i+1}. [{dt}] {file_path}\n"
                result += f"   Description: {desc}\n"
                if backup and os.path.exists(backup):
                    result += f"   Backup: {backup} ✓\n"
                result += "\n"
            result += "💡 Use '/undo <number>' to revert a specific change"
            return result

        elif action == 'last':
            # Revert last change
            si = self._get_self_iteration()
            changes = si.get_change_history(limit=1)
            if not changes:
                return "📭 No changes to undo."
            change = changes[0]
            return self._revert_change(change)

        else:
            # Try to parse as number
            try:
                change_id = int(action)
                si = self._get_self_iteration()
                changes = si.get_change_history(limit=change_id + 10)  # Get enough
                if change_id < 1 or change_id > len(changes):
                    return self.formatter.error(f"Invalid change ID. Use '/undo list' to see available IDs.")
                change = changes[change_id - 1]  # 1-indexed
                return self._revert_change(change)
            except ValueError:
                return self.formatter.error(f"Invalid command: {command}. Use '/undo --help' for usage.")

    def _revert_change(self, change: dict) -> str:
        """Revert a change by restoring from backup."""
        try:
            file_path = change.get('file_path')
            backup_path = change.get('backup')
            description = change.get('description', 'Unknown change')

            if not file_path:
                return self.formatter.error("Cannot revert: missing file path in change record")
            if not backup_path:
                return self.formatter.error("Cannot revert: no backup path in change record")
            if not os.path.exists(backup_path):
                return self.formatter.error(f"Cannot revert: backup file not found: {backup_path}")

            # Read backup content
            success, message, backup_content = self.safety_manager.safe_read_file(backup_path)
            if not success:
                return self.formatter.error(f"Cannot read backup: {message}")

            # Write back to original file
            success, message, _ = self.safety_manager.safe_write_file(file_path, backup_content, create_backup=False)
            if not success:
                return self.formatter.error(f"Cannot write original file: {message}")

            # Log the revert
            si = self._get_self_iteration()
            si.log_change({
                'timestamp': time.time(),
                'file_path': file_path,
                'description': f'Reverted: {description}',
                'backup': backup_path,
                'status': 'reverted',
                'original_change': change.get('timestamp')
            })

            return f"{self.formatter.success(f'Reverted change: {description}')}\n📄 File restored from: {backup_path}"
        except Exception as e:
            return self.formatter.error(f"Error reverting change: {str(e)}")

    def handle_test_command(self, command: str) -> str:
        """Handle /test command.

        Usage:
          /test                       - Run basic development tests (dev_test.py)
          /test unit                  - Run unit tests (if available)
          /test all                   - Run all available tests
          /test --help                - Show help
        """
        if not command or command.strip() == "":
            command = "basic"

        cmd = command.strip().lower()
        if cmd == '--help':
            help_text = """
🧪 /test Command Usage:
  /test                       - Run basic development tests (dev_test.py)
  /test unit                  - Run unit tests (if available)
  /test all                   - Run all available tests
  /test --help                - Show this help

Examples:
  /test              # Run basic tests
  /test unit         # Run unit tests
            """.strip()
            return help_text

        try:
            if cmd == 'basic' or cmd == 'dev' or cmd == '':
                # Run dev_test.py
                test_path = os.path.join(self.agent_root, "..", "dev_test.py")
                test_path = os.path.abspath(test_path)
                if not os.path.exists(test_path):
                    return self.formatter.error(f"Test file not found: {test_path}")

                import subprocess
                result = subprocess.run(
                    [sys.executable, test_path],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=os.path.dirname(test_path)
                )

                output = result.stdout
                if result.stderr:
                    output += f"\n\nSTDERR:\n{result.stderr}"

                if result.returncode == 0:
                    return self.formatter.success(f"Tests passed:\n\n{output}")
                else:
                    return self.formatter.error(f"Tests failed (exit code: {result.returncode}):\n\n{output}")

            elif cmd == 'unit':
                # Try to run pytest
                try:
                    import subprocess
                    result = subprocess.run(
                        [sys.executable, "-m", "pytest", "tests/", "-v"],
                        capture_output=True,
                        text=True,
                        timeout=120,
                        cwd=os.getcwd()
                    )
                    output = result.stdout
                    if result.stderr:
                        output += f"\n\nSTDERR:\n{result.stderr}"

                    if result.returncode == 0:
                        return self.formatter.success(f"Unit tests passed:\n\n{output}")
                    else:
                        return self.formatter.error(f"Unit tests failed (exit code: {result.returncode}):\n\n{output}")
                except FileNotFoundError:
                    return self.formatter.error("pytest not found. Install with: pip install pytest")
                except Exception as e:
                    return self.formatter.error(f"Error running unit tests: {str(e)}")

            elif cmd == 'all':
                # Run both
                basic_result = self.handle_test_command('basic')
                unit_result = self.handle_test_command('unit')
                return f"🧪 ALL TESTS\n\n{'='*60}\nBASIC TESTS:\n{basic_result}\n\n{'='*60}\nUNIT TESTS:\n{unit_result}"
            else:
                return self.formatter.error(f"Unknown test command: {command}. Use '/test --help' for usage.")
        except subprocess.TimeoutExpired:
            return self.formatter.error("Test execution timed out")
        except Exception as e:
            return self.formatter.error(f"Error running tests: {str(e)}")

    def handle_apply_command(self, command: str) -> str:
        """Handle /apply command (alias for /code apply).

        Usage:
          /apply              - Apply pending changes with confirmation
          /apply force        - Apply without interactive confirmation
          /apply confirm      - Apply with confirmation (same as /apply)
          /apply --help       - Show help
        """
        if command and command.strip().lower() in ['--help', 'help']:
            help_text = """
🔧 /apply Command (alias for /code apply):
  /apply              - Apply pending changes with confirmation
  /apply force        - Apply without interactive confirmation
  /apply confirm      - Apply with confirmation (same as /apply)
  /apply --help       - Show this help

Note: This is an alias for /code apply. See '/help code' for more details.
            """.strip()
            return help_text

        # Map to /code apply subcommand
        if command and 'force' in command.lower():
            return self._code_apply_changes_confirm(force=True)
        else:
            return self._code_apply_changes()

    def _add_webpage_to_memory(self, url: str, content: str) -> None:
        """
        Add webpage content to conversation history for AI awareness
        """
        # Extract just the main text content (remove formatting headers)
        # Find where the actual content starts (after the "-" * 60 line)
        lines = content.split('\n')
        content_start = 0

        for i, line in enumerate(lines):
            if '-' * 60 in line or '=' * 60 in line:
                content_start = i + 1
                break

        main_content = '\n'.join(lines[content_start:])
        
        # Remove trailing separator if present
        if '-' * 60 in main_content or '=' * 60 in main_content:
            main_content = main_content[:main_content.rfind('-' * 60)]

        # Clean up whitespace
        main_content = main_content.strip()

        # Truncate to avoid token limits (adjust based on your context window)
        max_chars = 6000
        if len(main_content) > max_chars:
            # Try to find a good truncation point
            truncated = main_content[:max_chars]
            last_period = truncated.rfind('.')
            last_newline = truncated.rfind('\n')

            if last_period > max_chars * 0.8:
                main_content = truncated[:last_period + 1]
            elif last_newline > max_chars * 0.8:
                main_content = truncated[:last_newline]
            else:
                main_content = truncated + "\n\n[Content truncated for context]"

        # Add to conversation history
        self.add_to_history("user", f"""I've read the following webpage:

    URL: {url}

    Content:
    {main_content}

    Please remember this content. I may ask you questions about it.""")

        print("💡 Content added to AI memory. You can now ask questions about it!")

    def _is_likely_file_path(self, path: str) -> bool:
        """
        Determine if the given string is likely a local file path rather than a URL.
        """
        # Check for URL indicators
        if '://' in path:
            return False
        if path.startswith(('http://', 'https://', 'ftp://', 'file://')):
            return False

        # Check for file path indicators
        if '/' in path or '\\' in path:
            return True
        if path.startswith(('./', '../', '~/')):
            return True
        # Check for file extension (common code/text extensions)
        import os
        ext = os.path.splitext(path)[1].lower()
        if ext in {'.py', '.js', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css', '.java', '.cpp', '.c', '.h', '.go', '.rs', '.rb', '.php', '.swift'}:
            return True
        # Check if path exists (relative to current directory or code analyzer root)
        if os.path.exists(path):
            return True
        # Default to URL assumption (but could be a domain)
        return False

    def _get_self_iteration(self):
        """Initialize and return SelfIteration instance."""
        if self.self_iteration is None:
            self.self_iteration = SelfIteration(self.agent_root, self.code_analyzer)
        return self.self_iteration

    def _is_self_modification(self, file_path: str) -> bool:
        """Check if file is within agent's own codebase."""
        try:
            abs_path = os.path.abspath(file_path)
            return abs_path.startswith(self.agent_root)
        except:
            return False

    def _handle_file_read(self, file_path: str, no_ai: bool = False) -> str:
        """
        Read a local file and optionally add to conversation history.
        Supports line ranges: file.py:10-20
        """
        import os
        import re

        # Parse line range (e.g., file.py:10-20)
        line_range = None
        match = re.match(r'^(.+):(\d+)(?:-(\d+))?$', file_path)
        if match:
            file_path = match.group(1)
            start_line = int(match.group(2))
            end_line = int(match.group(3)) if match.group(3) else start_line
            line_range = (start_line, end_line)

        # Ensure code analyzer is initialized
        if not self.code_analyzer:
            self.code_analyzer = CodeAnalyzer(os.getcwd(), safety_manager=self.safety_manager)

        # Read file
        success, message, content = self.code_analyzer.read_file_safe(file_path)
        if not success:
            return self.formatter.error(f"Cannot read file: {message}")

        # Apply line range if specified
        if line_range:
            lines = content.split('\n')
            start, end = line_range
            if start < 1 or end > len(lines) or start > end:
                return self.formatter.error(f"Invalid line range: {start}-{end} (file has {len(lines)} lines)")
            # Convert to 0-index and slice
            content = '\n'.join(lines[start-1:end])
            line_info = f" (lines {start}-{end})"
        else:
            line_info = ""

        # Add to conversation history unless --no-ai flag is set
        if not no_ai:
            self.add_to_history("user", f"""I've read the following file:

    File: {file_path}{line_info}
    Lines: {len(content.splitlines())}

    ```python
    {content[:2000]}{'...' if len(content) > 2000 else ''}
    ```

    Please remember this code. I may ask you to analyze or fix it.

    Note: If I ask you to propose changes to this code, use the PROPOSED CHANGE format with exact Old Code and New Code.""")

        # Return formatted result
        result = f"📄 File: {file_path}{line_info}\n"
        result += f"📏 Size: {len(content)} characters, {len(content.splitlines())} lines\n"
        if len(content) > 2000:
            result += f"📝 Preview (first 2000 chars):\n```\n{content[:2000]}...\n```\n"
        else:
            result += f"📝 Content:\n```\n{content}\n```\n"
        if not no_ai:
            result += "\n💡 Content added to AI memory. You can now ask questions about it!"
        return result

    # NEW: Code analysis methods
    def handle_code_command(self, command: str) -> str:
        """
        Handle /code command for code analysis and refactoring

        Available commands:
          /code scan [path]              - Scan codebase (default: current directory)
          /code summary                  - Show codebase summary
          /code find <pattern>          - Find files matching pattern
          /code read <file_path>        - Read and analyze a specific file
          /code analyze <file_path>     - Analyze file structure
          /code search <text>           - Search for text in code
          /code changes                 - Show pending changes
          /code apply                   - Apply pending changes (with confirmation)
          /code clear                   - Clear pending changes
          /code help                    - Show help
        """
        if not command or command.strip() == "":
            return self._code_help()

        parts = command.split()
        subcommand = parts[0].lower() if parts else ""

        # Auto-switch to coding mode for code commands (except help)
        if subcommand != 'help' and self.mode != 'coding':
            self.switch_mode('coding', persist=False)

        if subcommand == 'help':
            return self._code_help()
        elif subcommand == 'scan':
            path = ' '.join(parts[1:]) if len(parts) > 1 else os.getcwd()
            return self._code_scan(path)
        elif subcommand == 'summary':
            return self._code_summary()
        elif subcommand == 'find':
            pattern = ' '.join(parts[1:]) if len(parts) > 1 else ""
            return self._code_find(pattern)
        elif subcommand == 'read':
            file_path = ' '.join(parts[1:]) if len(parts) > 1 else ""
            return self._code_read(file_path)
        elif subcommand == 'analyze':
            file_path = ' '.join(parts[1:]) if len(parts) > 1 else ""
            return self._code_analyze(file_path)
        elif subcommand == 'search':
            text = ' '.join(parts[1:]) if len(parts) > 1 else ""
            return self._code_search(text)
        elif subcommand == 'changes':
            return self._code_show_changes()
        elif subcommand == 'apply':
            return self._code_apply_changes()
        elif subcommand == 'clear':
            return self._code_clear_changes()
        elif subcommand == 'self-scan':
            return self._code_self_scan()
        elif subcommand == 'self-improve':
            feature = ' '.join(parts[1:]) if len(parts) > 1 else ""
            return self._code_self_improve(feature)
        elif subcommand == 'self-apply':
            return self._code_self_apply()
        elif subcommand == 'reason':
            file_path = ' '.join(parts[1:]) if len(parts) > 1 else ""
            return self._code_reason(file_path)
        else:
            return self.formatter.error(f"Unknown subcommand: {subcommand}\n{self._code_help()}")

    def _code_help(self) -> str:
        return """
📁 CODE ANALYSIS COMMANDS:
  /code scan [path]          - Scan codebase (default: current directory)
  /code summary              - Show codebase summary (size, file types)
  /code find <pattern>       - Find files (supports wildcards: *.py, *test*)
  /code read <file_path>     - Read and display a file
  /code analyze <file_path>  - Analyze file structure (imports, functions, classes)
  /code search <text>        - Search for text in code files
  /code changes              - Show pending code changes
  /code apply                - Apply pending changes (requires confirmation)
  /code clear                - Clear pending changes
  /code self-scan            - Scan agent's own codebase
  /code self-improve [target]- Suggest improvements to agent's own code
  /code self-apply           - Apply vetted self-improvements with safety checks
  /code reason <file_path>   - Deep analysis using reasoning model (chain-of-thought)
  /code help                 - Show this help

💡 TIPS:
  • Use relative paths from current directory
  • Changes are grouped and require confirmation
  • Large codebases (>500 files) require specific file targeting
  • Use /code reason for complex analysis with deepseek-reasoner
        """.strip()

    def _code_scan(self, path: str) -> str:
        """Initialize code analyzer with given path"""
        try:
            abs_path = os.path.abspath(path)
            if not os.path.exists(abs_path):
                return self.formatter.error(f"Path does not exist: {abs_path}")

            self.code_analyzer = CodeAnalyzer(abs_path, safety_manager=self.safety_manager)

            # Count files to warn if too many
            total_files, total_dirs = self.code_analyzer.count_files()

            result = f"{self.formatter.success(f'Codebase scanned: {abs_path}')}\n"
            result += f"📊 Statistics:\n"
            result += f"  • Total files: {total_files}\n"
            result += f"  • Total directories: {total_dirs}\n"

            if total_files > self.code_analyzer.max_files_before_warning:
                result += f"\n{self.formatter.warning(f'LARGE CODEBASE: {total_files} files detected')}\n"
                result += f"💡 Use '/code find <pattern>' to search for specific files\n"
                result += f"   or '/code read <specific_file>' to analyze individual files\n"

            # Check threshold and ask for confirmation to show detailed summary
            should_continue, _ = self._check_file_threshold(total_files, "scan codebase for detailed summary")
            if should_continue and total_files <= 1000:
                summary = self.code_analyzer.get_code_summary()
                if 'file_types' in summary:
                    result += f"\n📁 File Types:\n"
                    for ext, count in summary['file_types'].items():
                        result += f"  • {ext or 'no ext'}: {count} files\n"

            return result

        except Exception as e:
            return self.formatter.error(f"Error scanning path: {str(e)}")
    
    def _code_summary(self) -> str:
        """Show codebase summary"""
        if not self.code_analyzer:
            return self.formatter.error("No codebase scanned. Use '/code scan <path>' first.")
        
        summary = self.code_analyzer.get_code_summary()
        
        result = f"📊 CODEBASE SUMMARY\n"
        result += f"────────────────────────\n"
        result += f"Root: {summary['root_path']}\n"
        result += f"Total files: {summary['total_files']}\n"

        if 'warning' in summary:
            result += f"\n{self.formatter.warning(summary['warning'])}\n"
            result += f"💡 {summary['suggestion']}\n"

        if 'file_types' in summary:
            result += f"\n📁 File Types:\n"
            for ext, count in summary['file_types'].items():
                percentage = (count / summary['total_files']) * 100
                result += f"  • {ext or 'no ext'}: {count} ({percentage:.1f}%)\n"

        if 'total_lines' in summary:
            result += f"\n📝 Total lines (est.): {summary['total_lines']:,}\n"
        
        if 'total_size' in summary:
            result += f"💾 Total size: {summary['total_size']}\n"

        result += f"\n💡 Use '/code find <pattern>' to explore specific files"
        
        return result

    def _code_find(self, pattern: str) -> str:
        """Find files matching pattern"""
        if not self.code_analyzer:
            return self.formatter.error("No codebase scanned. Use '/code scan <path>' first.")

        if not pattern:
            return self.formatter.error("Please specify a pattern. Examples:\n" \
                   "  /code find *.py\n" \
                   "  /code find *test*\n" \
                   "  /code find agent.py")
        
        # Check total files and ask for confirmation if large
        total_files, _ = self.code_analyzer.count_files()
        should_continue, limit = self._check_file_threshold(total_files, f"find files matching '{pattern}'")
        # Even if user declined full operation, we continue with reduced limit
        # Smart search with appropriate limit
        results = self.code_analyzer.smart_find_files(pattern, max_results=20, search_limit=limit)
        
        if not results:
            return f"🔍 No files found matching: {pattern}"

        result = f"🔍 Found {len(results)} files matching: {pattern}\n"
        result += "────────────────────────\n"

        for i, file_info in enumerate(results[:10], 1):
            size_kb = file_info['size'] / 1024
            result += f"{i}. {file_info['relative']}\n"
            result += f"   Size: {size_kb:.1f} KB\n"

        if len(results) > 10:
            result += f"\n... and {len(results) - 10} more files\n"

        result += f"\n💡 Use '/code read <file_path>' to read a specific file"
        
        return result

    def _code_read(self, file_path: str) -> str:
        """Read and display a file"""
        if not self.code_analyzer:
            return self.formatter.error("No codebase scanned. Use '/code scan <path>' first.")
        
        if not file_path:
            return self.formatter.error("Please specify a file path")
        
        try:
            # ... existing file reading code ...
            
            # Add to AI memory with context that this is code
            self.add_to_history("user", f"""I've read the following code file:

    File: {abs_path}
    Lines: {line_count}

    ```python
    {truncated}
    ```

    Please remember this code. I may ask you to analyze or fix it.

    Note: If I ask you to propose changes to this code, use the PROPOSED CHANGE format with exact Old Code and New Code.""")

            return result

        except Exception as e:
            return self.formatter.error(f"Error reading file: {str(e)}")
    
    def add_code_context_instructions(self):
        """
        Add code-specific instructions to the current conversation
        This is called when user is asking about code but not using /fix or /analyze
        """
        code_instructions = """
        IMPORTANT: For code changes, use this format:

        PROPOSED CHANGE:
        File: [file_path]
        Description: [brief description]
        Old Code: [EXACT code from the file to replace]
        New Code: [improved replacement code]
        Line: [line number if known]

        Old Code must be exact code from the file, not comments or truncated text.
        """
        
        self.add_to_history("system", code_instructions)
        
    def is_code_related_query(self, prompt: str) -> bool:
        """
        Detect if user is asking about code
        """
        code_keywords = [
            'fix', 'bug', 'error', 'code', 'function', 'class', 'method',
            'def ', 'import ', 'try:', 'except', 'file', 'line', 
            'syntax', 'compile', 'run', 'execute', 'debug',
            'improve', 'optimize', 'refactor', 'review'
        ]
        
        prompt_lower = prompt.lower()

        # Check for code file extensions
        if any(ext in prompt_lower for ext in ['.py', '.js', '.java', '.cpp', '.c', '.go', '.rs', '.rb']):
            return True

        # Check for code keywords
        if any(keyword in prompt_lower for keyword in code_keywords):
            return True

        # Check if it's about a specific file path
        import re
        file_patterns = [
            r'[\w/\\.-]+\.py',
            r'[\w/\\.-]+\.js',
            r'[\w/\\.-]+\.java',
            r'file:\s*[\w/\\.-]+',
            r'line\s+\d+',
        ]

        for pattern in file_patterns:
            if re.search(pattern, prompt_lower):
                return True

        return False

    def _code_analyze(self, file_path: str) -> str:
        """Analyze a file's structure"""
        if not self.code_analyzer:
            return self.formatter.error("No codebase scanned. Use '/code scan <path>' first.")

        if not file_path:
            return self.formatter.error("Please specify a file path")
        
        try:
            abs_path = os.path.abspath(file_path)
            analysis = self.code_analyzer.analyze_file(abs_path)

            if not analysis['success']:
                return self.formatter.error(f"{analysis['error']}")

            result = f"🔬 FILE ANALYSIS: {os.path.basename(abs_path)}\n"
            result += f"📁 Path: {abs_path}\n"
            result += f"📊 Stats: {analysis['lines']} lines, {analysis['size']:,} bytes\n"
            result += "────────────────────────\n"

            # Show imports
            if analysis['imports']:
                result += f"\n📦 IMPORTS ({len(analysis['imports'])}):\n"
                for imp in analysis['imports'][:10]:  # Show first 10
                    result += f"  • Line {imp['line']}: {imp['content']}\n"
                if len(analysis['imports']) > 10:
                    result += f"  ... and {len(analysis['imports']) - 10} more imports\n"

            # Show classes
            if analysis['classes']:
                result += f"\n🏛 ️  CLASSES ({len(analysis['classes'])}):\n"
                for cls in analysis['classes']:
                    result += f"  • Line {cls['line']}: {cls['name']}\n"

            # Show functions
            if analysis['functions']:
                result += f"\n⚙️  FUNCTIONS ({len(analysis['functions'])}):\n"
                for func in analysis['functions'][:15]:  # Show first 15
                    result += f"  • Line {func['line']}: {func['name']}()\n"
                if len(analysis['functions']) > 15:
                    result += f"  ... and {len(analysis['functions']) - 15} more functions\n"

            # Show preview
            result += f"\n📄 CONTENT PREVIEW (first 50 lines):\n"
            result += "```\n"
            result += analysis['content_preview']
            result += "\n```\n"

            if analysis['has_more_lines']:
                result += f"\n💡 File has {analysis['lines']} total lines. Use '/code read {file_path}' to see full content."

            # Add to AI memory for analysis
            self.add_to_history("user", f"""I've analyzed the following code file:

File: {abs_path}
Lines: {analysis['lines']}
Imports: {len(analysis['imports'])}
Classes: {len(analysis['classes'])}
Functions: {len(analysis['functions'])}

```{os.path.splitext(abs_path)[1][1:] or 'text'}
{analysis['content_preview']}
```

Please analyze this code structure.""")

            return result

        except Exception as e:
            return self.formatter.error(f"Error analyzing file: {str(e)}")

    def _code_search(self, search_text: str) -> str:
        """Search for text in code files"""
        if not self.code_analyzer:
            return self.formatter.error("No codebase scanned. Use '/code scan <path>' first.")
        
        if not search_text:
            return self.formatter.error("Please specify search text")

        # Check total files and ask for confirmation if large
        total_files, _ = self.code_analyzer.count_files()

        should_continue, limit = self._check_file_threshold(
            total_files, f"search for '{search_text}'"
        )
        # Even if user declined full operation, we continue with reduced limit

        # Find code files with appropriate limit
        code_files = self.code_analyzer.find_code_files(limit=limit)

        if not code_files:
            return self.formatter.error("No code files found in the scanned codebase.")

        results = []
        self._safe_print(f"🔍 Searching in {len(code_files)} files...")
        
        for file_path in code_files:
            try:
                success, message, content = self.code_analyzer.read_file_safe(file_path)
                if success and search_text.lower() in content.lower():
                    # Count occurrences
                    occurrences = content.lower().count(search_text.lower())

                    # Get context lines
                    lines = content.split('\n')
                    matching_lines = []
                    for i, line in enumerate(lines):
                        if search_text.lower() in line.lower():
                            context_start = max(0, i - 1)
                            context_end = min(len(lines), i + 2)
                            context = "\n".join(f"{j+1:4d}: {lines[j]}" for j in range(context_start, context_end))
                            matching_lines.append(context)

                    results.append({
                        'path': file_path,
                        'occurrences': occurrences,
                        'relative': os.path.relpath(file_path, self.code_analyzer.root_path),
                        'sample': matching_lines[0] if matching_lines else ""
                    })

                    if len(results) >= 20:  # Limit results
                        break
            except:
                continue

        if not results:
            result_msg = f"🔍 No matches found for '{search_text}' in {len(code_files)} files."
            self.add_search_results_to_history('code', search_text, result_msg)
            return result_msg
        
        result = f"🔍 SEARCH RESULTS for '{search_text}'\n"
        result += f"📁 Found in {len(results)} files (searched {len(code_files)} files)\n"
        result += "────────────────────────\n"

        for i, res in enumerate(results, 1):
            result += f"\n{i}. {res['relative']}\n"
            result += f"   Matches: {res['occurrences']}\n"
            if res['sample']:
                result += f"   Sample:\n{res['sample']}\n"

        self.add_search_results_to_history('code', search_text, result)
        return result

    def _code_show_changes(self) -> str:
        """Show pending code changes"""
        if not self.code_changes_pending:
            return "📭 No pending changes. Use the AI to suggest code fixes."
        
        result = f"📋 PENDING CODE CHANGES ({len(self.code_changes_pending)})\n"
        result += "────────────────────────\n"

        # Order changes by dependencies
        ordered_changes = self._order_changes_by_dependencies(self.code_changes_pending)

        # Group changes by file, preserving file order
        changes_by_file = {}
        file_order = []
        for change in ordered_changes:
            file_path = change['file_path']
            if file_path not in changes_by_file:
                changes_by_file[file_path] = []
                file_order.append(file_path)
            changes_by_file[file_path].append(change)

        for file_path, changes in changes_by_file.items():
            result += f"\n📄 File: {file_path}\n"
            for change in changes:
                result += f"  • {change['description']}\n"
                if 'old_code' in change and 'new_code' in change:
                    result += f"    Change:\n"
                    result += f"    - {change['old_code'][:100]}{'...' if len(change['old_code']) > 100 else ''}\n"
                    result += f"    + {change['new_code'][:100]}{'...' if len(change['new_code']) > 100 else ''}\n"
        
        result += f"\n💡 Apply changes with: /code apply"
        result += f"\n💡 Clear changes with: /code clear"

        return result

    def _code_apply_changes(self) -> str:
        """Apply pending code changes with confirmation"""
        if not self.code_changes_pending:
            return "📭 No pending changes to apply."

        # Show what will be changed
        result = self._code_show_changes()
        result += "\n\n" + "="*60 + "\n"
        result += f"{self.formatter.warning('WARNING: This will modify files on disk!')}\n"
        result += "="*60 + "\n\n"

        # Ask for confirmation
        result += "Are you sure you want to apply these changes? (yes/no): "

        # In the CLI, we would handle this interactively
        # For now, return instructions
        result += "\n\n💡 To apply, type 'yes' and then run '/code apply confirm'"
        result += "\n💡 Or use '/code apply force' to apply without interactive confirmation"
        
        return result
    def _order_changes_by_dependencies(self, changes):
        """Order changes based on file dependencies."""
        if not changes:
            return changes
        # Determine root path: use agent_root for self-modifications, else code_analyzer.root_path
        import os
        root_path = self.agent_root if hasattr(self, 'agent_root') else (self.code_analyzer.root_path if self.code_analyzer else os.getcwd())
        planner = Planner(root_path)
        ordered = planner.plan_changes(changes)
        return ordered

    def _code_apply_changes_confirm(self, force: bool = False) -> str:
        """Actually apply the changes (called after confirmation)"""
        if not self.code_changes_pending:
            return " No pending changes to apply."

        applied = []
        failed = []

        # Order changes by dependencies
        ordered_changes = self._order_changes_by_dependencies(self.code_changes_pending)

        # Group changes by file, preserving file order
        changes_by_file = {}
        file_order = []
        for change in ordered_changes:
            file_path = change['file_path']
            if file_path not in changes_by_file:
                changes_by_file[file_path] = []
                file_order.append(file_path)
            changes_by_file[file_path].append(change)

        # Apply changes to each file
        for file_path in file_order:
            changes = changes_by_file[file_path]
            try:
                # Check if this is a self-modification
                if self._is_self_modification(file_path):
                    # Use self-iteration framework for safety
                    si = self._get_self_iteration()
                    file_applied = False
                    for change in changes:
                        if 'old_code' in change and 'new_code' in change:
                            success, msg, backup = si.apply_change(
                                file_path,
                                change['old_code'],
                                change['new_code'],
                                change.get('description', 'Unknown change')
                            )
                            if success:
                                file_applied = True
                            else:
                                failed.append(f"{file_path}: {msg}")
                    if file_applied:
                        applied.append(file_path)
                    continue  # Skip original logic

                # Original logic for non-self modifications
                # Read current file
                success, message, content = self.code_analyzer.read_file_safe(file_path)
                if not success:
                    failed.append(f"{file_path}: {message}")
                    continue

                original_content = content

                # Apply changes in reverse order (to preserve line numbers)
                # FIX: Handle None values in sorting
                changes_sorted = sorted(
                    changes, 
                    key=lambda x: x.get('line') if x.get('line') is not None else 0, 
                    reverse=True
                )

                for change in changes_sorted:
                    if 'old_code' in change and 'new_code' in change:
                        # Simple string replacement (could be more sophisticated)
                        if change['old_code'] in content:
                            content = content.replace(change['old_code'], change['new_code'])
                        else:
                            # Try line-based replacement
                            lines = content.split('\n')
                            line_num = change.get('line')
                            if line_num and 0 < line_num <= len(lines):
                                lines[line_num - 1] = change['new_code']
                                content = '\n'.join(lines)
                            else:
                                # Try fuzzy matching - find similar code
                                old_code_stripped = change['old_code'].strip()
                                lines = content.split('\n')
                                for i, line in enumerate(lines):
                                    if old_code_stripped in line.strip():
                                        lines[i] = change['new_code']
                                        content = '\n'.join(lines)
                                        break
                                else:
                                    failed.append(f"{file_path}: Could not find '{change['old_code'][:50]}...' in file")

                # Write back only if changes were made
                if content != original_content:
                    success, message, _ = self.safety_manager.safe_write_file(file_path, content, create_backup=True)
                    if not success:
                        failed.append(f"{file_path}: {message}")
                        continue
                    applied.append(file_path)
                else:
                    failed.append(f"{file_path}: No changes were made (old_code not found)")

            except Exception as e:
                failed.append(f"{file_path}: {str(e)}")
        
        # Clear pending changes
        self.code_changes_pending = []

        # Build result
        result = " APPLYING CODE CHANGES\n"
        result += "\n"
        
        if applied:
            result += f"\n{self.formatter.success(f'Successfully applied changes to {len(applied)} files:')}\n"
            for file_path in applied:
                result += f"   📄 {file_path}\n"

        if failed:
            result += f"\n{self.formatter.error(f'Failed to apply changes to {len(failed)} files:')}\n"
            for error in failed:
                result += f"   {self.formatter.warning(error)}\n"

        if not applied and not failed:
            result += "\n📭 No changes were applied."
        
        return result

    def _code_clear_changes(self) -> str:
        """Clear all pending changes"""
        count = len(self.code_changes_pending)
        self.code_changes_pending = []
        return f"🧹 Cleared {count} pending changes."

    def _code_self_scan(self) -> str:
        """Scan the agent's own codebase."""
        if not self.code_analyzer:
            self.code_analyzer = CodeAnalyzer(self.agent_root, safety_manager=self.safety_manager)
        summary = self.code_analyzer.get_code_summary()
        result = "🔍 SELF-SCAN: Agent's own codebase\n"
        result += f"Root: {self.agent_root}\n"
        result += f"Total files: {summary['total_files']}\n"
        if 'file_types' in summary:
            result += "\nFile types:\n"
            for ext, count in summary['file_types'].items():
                result += f"  {ext or 'no ext'}: {count}\n"
        return result

    def _code_self_improve(self, feature: str) -> str:
        """Suggest improvements to the agent's own code."""
        try:
            si = self._get_self_iteration()
            # Determine target files
            target_files = []
            if feature and os.path.isfile(feature):
                target_files.append(feature)
            elif feature and os.path.isdir(feature):
                # Directory: find Python files
                for root, dirs, files in os.walk(feature):
                    dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', '.git')]
                    for f in files:
                        if f.endswith('.py'):
                            target_files.append(os.path.join(root, f))
            else:
                # Default: agent's own Python files
                for root, dirs, files in os.walk(self.agent_root):
                    dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', '.git')]
                    for f in files:
                        if f.endswith('.py'):
                            target_files.append(os.path.join(root, f))

            if not target_files:
                return self.formatter.error("No Python files found to improve.")

            total_suggestions = 0
            result = f"🔍 Self-improvement scan: {len(target_files)} Python files\n"

            for file_path in target_files:
                suggestions = si.suggest_improvements(file_path)
                if suggestions:
                    result += f"\n📄 {os.path.relpath(file_path, self.agent_root)}:\n"
                    for sugg in suggestions:
                        # Propose change
                        self.propose_code_change(
                            file_path=file_path,
                            old_code=sugg['old_code'],
                            new_code=sugg['new_code'],
                            description=sugg['description']
                        )
                        result += f"  • {sugg['description']}\n"
                        total_suggestions += 1

            if total_suggestions == 0:
                result += f"\n{self.formatter.success('No improvements suggested (code looks good!).')}"
            else:
                result += f"\n💡 {total_suggestions} improvement(s) proposed. Use '/code changes' to review, '/code apply' to apply."

            return result
        except Exception as e:
            return self.formatter.error(f"Error during self-improvement: {str(e)}")

    def _code_self_apply(self) -> str:
        """Apply vetted self-improvements with safety checks."""
        # Check if there are pending changes
        if not self.code_changes_pending:
            return "📭 No pending changes to apply."

        # Ensure all changes are self-modifications (optional)
        non_self = []
        for change in self.code_changes_pending:
            if not self._is_self_modification(change['file_path']):
                non_self.append(change['file_path'])
        if non_self:
            return self.formatter.error(f"Self-apply only works on agent's own code. Non-self files: {', '.join(set(non_self))}")

        # Run pre-tests using self-iteration framework
        si = self._get_self_iteration()
        test_success, test_msg = si.run_basic_tests()
        if not test_success:
            return self.formatter.error(f"Pre-test suite failed: {test_msg}. Aborting self-apply.")

        # Apply changes using existing logic (which will use self-iteration with tests)
        result = self._code_apply_changes_confirm(force=True)

        # Run post-tests (optional) - already done per file in apply_change
        # Add note about tests
        return "🔧 Self-apply completed with safety checks.\n" + result
    def _code_reason(self, file_path: str) -> str:
        """Deep analysis of a file using reasoning model (chain-of-thought)."""
        if not file_path:
            return self.formatter.error("Please specify a file path")

        # Read file
        if not self.code_analyzer:
            return self.formatter.error("No codebase scanned. Use '/code scan <path>' first.")

        success, message, content = self.code_analyzer.read_file_safe(file_path)
        if not success:
            return self.formatter.error(f"Cannot read file: {message}")

        # Use deepseek-reasoner for deep analysis (temporary switch)
        reasoner_model = "deepseek-reasoner"
        model_used = self.model  # default

        # Construct prompt for analysis
        prompt = f"""Please analyze the following code file using chain-of-thought reasoning.
Provide a detailed analysis covering:
1. Code structure and organization
2. Potential bugs or issues
3. Performance considerations
4. Readability and maintainability
5. Suggested improvements with reasoning

File: {file_path}
Code:
```python
{content}
```

Please think step by step and provide your analysis:"""

        messages = [
            {"role": "user", "content": prompt}
        ]

        # Define analysis function to run with temporary model
        def perform_analysis():
            print(f"[Reasoner] Using model '{self.model}' for deep analysis...")
            return self.generate_completion(messages, temperature=0.3, max_tokens=4000)

        try:
            analysis = self.with_model(reasoner_model, perform_analysis)
            model_used = reasoner_model
        except ValueError as e:
            # Fallback to current model if reasoner not available
            print(f"Warning: {e}. Falling back to current model '{self.model}'.")
            analysis = perform_analysis()
            model_used = self.model

        if analysis.startswith("Error generating completion"):
            return self.formatter.error(analysis)

        result = f"[Analysis] DEEP ANALYSIS (using {model_used}): {os.path.basename(file_path)}\n"
        result += f"Path: {file_path}\n"
        line_count = content.count('\n')
        result += f"Stats: Content length: {len(content)} characters, {line_count} lines\n"
        result += "────────────────────────\n"
        result += analysis
        result += "\n\nTip: Use '/code analyze' for structural analysis or '/code self-improve' to propose changes."

        return result

    def propose_code_change(self, file_path: str, old_code: str, new_code: str,
                           description: str, line: int = None) -> str:
        """
        Propose a code change (called by AI analysis)
        Returns: Confirmation message and adds to pending changes
        """
        change = {
            'file_path': file_path,
            'old_code': old_code,
            'new_code': new_code,
            'description': description,
            'line': line,
            'proposed_at': time.time()
        }
        
        self.code_changes_pending.append(change)
        
        result = f"💡 CODE CHANGE PROPOSED\n"
        result += f"File: {file_path}\n"
        result += f"Description: {description}\n"
        result += f"\nChange Preview:\n"
        result += f"- {old_code[:100]}{'...' if len(old_code) > 100 else ''}\n"
        result += f"+ {new_code[:100]}{'...' if len(new_code) > 100 else ''}\n"
        result += f"\n💡 View all pending changes with: /code changes"
        result += f"\n💡 Apply changes with: /code apply"
        
        return result
    
    def search_sync(self, query: str) -> str:
        """Run async search from sync code"""
        if not self.search_loop:
            self.search_loop = asyncio.new_event_loop()

        return self.search_loop.run_until_complete(
            self.searcher.search(query)
        )

    def add_to_history(self, role: str, content: str):
        """Add message to conversation history"""
        self.conversation_history.append({"role": role, "content": content})

    def add_search_results_to_history(self, search_type: str, query: str, results: str):
        """
        Add search results to conversation history as system message.

        Args:
            search_type: 'web' or 'code'
            query: The search query
            results: The search results text
        """
        if search_type == 'web':
            prefix = "🔍 Web search results for"
        elif search_type == 'code':
            prefix = "📁 Code search results for"
        else:
            prefix = "Search results for"

        message = f"{prefix} '{query}':\n\n{results}"
        self.add_to_history("system", message)

    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []

    def get_conversation_summary(self) -> str:
        """Return a summary of the conversation history."""
        total_messages = len(self.conversation_history)
        token_count = self.context_manager.count_conversation_tokens()
        return f"Conversation summary: {total_messages} messages, {token_count} tokens."

    def get_token_count(self) -> int:
        """Return total token count of conversation history."""
        return self.context_manager.count_conversation_tokens()

    def _ensure_system_prompt(self):
        """Ensure system prompt is present in conversation history."""
        if not agent_config.system_prompt:
            return
        # Check if any system prompt already exists
        system_prompt_text = agent_config.system_prompt
        for msg in self.conversation_history:
            if msg["role"] == "system" and msg["content"] == system_prompt_text:
                return
        # Add system prompt at the beginning
        self.conversation_history.insert(0, {"role": "system", "content": system_prompt_text})

    def toggle_thinking_mode(self):
        """Toggle thinking mode on/off and save to config"""
        self.thinking_enabled = not self.thinking_enabled
        try:
            success = agent_config.update_value("agent.thinking_enabled", self.thinking_enabled)
            if success:
                print(f"✓ Thinking mode {'enabled' if self.thinking_enabled else 'disabled'} (saved to config)")
            else:
                print(f"✓ Thinking mode {'enabled' if self.thinking_enabled else 'disabled'} (but failed to save config)")
        except Exception as e:
            print(f"✓ Thinking mode {'enabled' if self.thinking_enabled else 'disabled'} (config update error: {e})")
        return self.thinking_enabled

    def debug_agent_status(self):
        """Show current agent status for debugging"""
        print(f"\n🔍 AGENT DEBUG INFO:")
        print(f"  • Model: {self.model}")
        print(f"  • API Key: {'Set' if self.api_key else 'Not set'}")
        print(f"  • Conversation history length: {len(self.conversation_history)}")
        print(f"  • Code analyzer: {'Initialized' if self.code_analyzer else 'Not initialized'}")
        print(f"  • Auto-fix mode: {'ACTIVE' if hasattr(self, 'auto_fix_mode') and self.auto_fix_mode else 'Inactive'}")
        
        if hasattr(self, 'current_fix_file'):
            print(f"  • Current fix file: {self.current_fix_file}")
        
        print(f"  • Pending changes: {len(self.code_changes_pending)}")

    def stream_response(self, prompt: str, temperature: float = 0.7, max_tokens: int = 2048 * 4):
        """Stream response with auto-file detection, analysis, and auto-fix capabilities"""
        import re
        import sys
        import os

        # Color support for thinking content (light gray)
        COLORS_ENABLED = sys.stdout.isatty() and os.getenv('TERM') not in ('dumb', '')
        COLOR_THINKING = '\033[90m'  # Light gray
        COLOR_RESET = '\033[0m'

        # Auto-detect if this is a code-related query
        if not prompt.startswith(('/fix', '/analyze', '/code', '/read', '/search', '/models')):
            if self.is_code_related_query(prompt):
                self._status_print(f"🔍 Detected code-related query. Adding code context...", "debug")
                self.add_code_context_instructions()

        self._status_print(f"🔄 Processing command: {prompt[:50]}{'...' if len(prompt) > 50 else ''}", "info")

        # Quick input classification (URLs, file paths, etc.)
        modified_prompt = prompt
        classified_cmd = self.classify_and_enhance_input(prompt)
        if classified_cmd:
            self._status_print(f"🎯 Classified as: {classified_cmd}", "debug")
            modified_prompt = classified_cmd
            # Skip natural language interpretation since we already classified
            skip_natural_language = True
        else:
            skip_natural_language = False

        # Natural language interpretation (skip if already classified)
        if not skip_natural_language and self.natural_language_enabled and self.interpreter:
            suggested_cmd, confidence = self.interpreter.interpret(prompt, self.mode)
            if suggested_cmd and confidence >= self.interpreter.confidence_threshold:
                self._status_print(f"🤖 Interpreting as: {suggested_cmd} (confidence: {confidence:.2f})", "debug")
                log_operation("natural_language_interpretation", prompt, True,
                             f"interpreted_as={suggested_cmd}, confidence={confidence:.2f}")
                modified_prompt = suggested_cmd

        # Auto-search detection (skip if already a command)
        if (self.auto_search_enabled and
            not modified_prompt.startswith('/') and
            self.searcher.should_search(modified_prompt)):
            self._status_print(f"🔍 Auto-detected search needed for: {modified_prompt[:50]}...", "debug")
            log_operation("auto_search_triggered", modified_prompt, True,
                         f"query_length={len(modified_prompt)}")
            success, results = self.search_sync(modified_prompt)
            if success:
                log_operation("auto_search_results", modified_prompt, True,
                             f"results_length={len(results)}")
                self.add_search_results_to_history('web', modified_prompt, results)
                modified_prompt = f"Web search results:\n{results}\n\nUser question: {modified_prompt}"
            else:
                log_operation("auto_search_failed", modified_prompt, False,
                             "search returned no results or error")
                self.add_to_history("system", f"Web search failed for '{modified_prompt}': {results}")

        # Update prompt with modifications
        prompt = modified_prompt

        # Auto-detect file paths before handling commands (skip if already a read command)
        file_content = None
        if not prompt.startswith(('/read', '/code read', '/fix', '/analyze')):
            file_content = self.auto_detect_and_read_file(prompt)
        if file_content:
            # Extract just the filename from path
            file_match = re.search(r'([^\\/]+\.\w+)$', prompt)
            if file_match:
                filename = file_match.group(1)
                self._safe_print(f"🔍 Detected file reference: {filename}")
                self._safe_print(f"📄 Auto-loaded file content into conversation")

        # Handle commands using registry
        skip_user_add = False
        command_handled = False
        # Sort prefixes by length descending to match longest first
        for prefix in sorted(self.command_handlers.keys(), key=len, reverse=True):
            if prompt.startswith(prefix):
                handler, strip_prefix = self.command_handlers[prefix]
                arg = prompt[len(prefix):].strip() if strip_prefix else prompt
                response = handler(arg)
                command_handled = True

                # Special handling for /fix and /analyze
                if prefix in ["/fix", "/analyze"]:
                    skip_user_add = True
                    if response is not None:
                        self._safe_print(f"\n{response}\n")
                    # Continue to API call
                    break

                # Special handling for /code apply confirm
                if prefix == "/code":
                    subcommand = arg
                    if subcommand.startswith("apply confirm") or subcommand == "apply force":
                        force = "force" in subcommand
                        response = self._code_apply_changes_confirm(force)

                # For other commands, print response and return
                if response is not None:
                    self._safe_print(f"\n{response}\n")
                return None

        # If no command matched
        if not command_handled:
            skip_user_add = False
            skip_user_add = False

        # Regular chat processing (skip if we already added in handle_auto_fix_command)
        if not skip_user_add:
            self.add_to_history("user", prompt)

        # Context management check
        actual_max_tokens = max_tokens or agent_config.max_tokens
        should_continue = self.context_manager.interactive_context_management(additional_tokens=actual_max_tokens)
        # Ensure system prompt is present regardless of choice (unless cancelled)
        self._ensure_system_prompt()
        # Re-add user prompt if it was removed during compression/clear
        user_prompt_exists = any(
            msg["role"] == "user" and msg["content"] == prompt
            for msg in self.conversation_history
        )
        if not user_prompt_exists and not skip_user_add:
            self.add_to_history("user", prompt)
        if not should_continue:
            return None

        self._status_print(f"🤖 Preparing to contact DeepSeek API...", "debug")
        self._status_print(f"📊 Current conversation has {len(self.conversation_history)} messages", "debug")

        # Debug: Show last message
        if self.conversation_history:
            last_msg = self.conversation_history[-1]
            self._status_print(f"📝 Last message role: {last_msg['role']}", "debug")
            self._status_print(f"📝 Last message preview: {last_msg['content'][:100]}...", "debug")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        # Context validation after possible compression
        total_tokens = self.context_manager.count_conversation_tokens()
        max_context = agent_config.max_context_tokens
        actual_max_tokens = max_tokens or agent_config.max_tokens
        if total_tokens + actual_max_tokens > max_context:
            # Reduce max_tokens to fit within limit, but keep at least 1
            new_max = max(1, max_context - total_tokens)
            self._status_print(f"⚠️  Context limit: reducing max_tokens from {actual_max_tokens} to {new_max}", "info")
            actual_max_tokens = new_max
        elif total_tokens > agent_config.context_warning_threshold * max_context:
            self._status_print(f"⚠️  Context warning: {total_tokens}/{max_context} tokens used", "info")

        payload = {
            "model": self.model,
            "messages": self.conversation_history,
            "stream": True,
            "temperature": temperature or agent_config.temperature,
            "max_tokens": actual_max_tokens,
        }

        if self.thinking_enabled:
            payload["thinking"] = {"type": "enabled"}
            self._status_print(f"💭 Thinking mode: ENABLED", "debug")

        try:
            self._status_print(f"📡 Sending request to DeepSeek API...", "debug")
            self._status_print(f"⏱️  Timeout set to: 60 seconds", "debug")
            
            # Start timing
            start_time = time.time()

            # Add progress indicator in background (only in chat mode)
            import threading
            progress_thread = None

            if self.mode == "chat":
                def show_progress():
                    dots = 0
                    while not getattr(self, '_request_complete', False):
                        print(f"\r⏳ Waiting for AI response{'.' * dots}{' ' * (3-dots)}", end="", flush=True)
                        dots = (dots + 1) % 4
                        time.sleep(0.5)

                self._request_complete = False
                progress_thread = threading.Thread(target=show_progress, daemon=True)
                progress_thread.start()
            
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=60  # Increased timeout
            )

            # Stop progress indicator (only if it was started)
            if self.mode == "chat":
                self._request_complete = True
                # Clear the progress line
                print("\r" + " " * 60 + "\r", end="", flush=True)

            elapsed_time = time.time() - start_time
            self._status_print(f"✅ Request sent in {elapsed_time:.1f}s. Status: {response.status_code}", "debug")

            if response.status_code != 200:
                self._status_print(f"❌ Error {response.status_code}: {response.text}", "critical")
                self.conversation_history.pop()
                return None

            self._status_print(f"📥 Starting to receive stream...", "debug")
            self._status_print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "debug")

            full_response = ""
            reasoning_content = ""
            is_reasoning_active = False
            is_final_response_active = False
            has_seen_reasoning = False
            chars_received = 0
            last_update_time = time.time()

            try:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                self._status_print(f"✅ Stream complete", "debug")
                                break
                            try:
                                json_data = json.loads(data)
                                if "choices" in json_data and json_data["choices"]:
                                    delta = json_data["choices"][0].get("delta", {})
                                    reasoning_chunk = delta.get("reasoning_content")

                                    if reasoning_chunk is not None:
                                        if reasoning_chunk and not is_reasoning_active:
                                            if COLORS_ENABLED:
                                                print(f"\n{COLOR_THINKING}💭 THINKING:{COLOR_RESET}")
                                            else:
                                                print(f"\n💭 THINKING:")
                                            if COLORS_ENABLED:
                                                print(f"{COLOR_THINKING}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{COLOR_RESET}")
                                            else:
                                                print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                                            is_reasoning_active = True
                                            is_final_response_active = False
                                            has_seen_reasoning = True

                                        if reasoning_chunk:
                                            if COLORS_ENABLED and is_reasoning_active:
                                                print(f"{COLOR_THINKING}{reasoning_chunk}{COLOR_RESET}", end="", flush=True)
                                            else:
                                                print(f"{reasoning_chunk}", end="", flush=True)
                                            reasoning_content += reasoning_chunk

                                    content = delta.get("content", "")
                                    if content:
                                        if not is_final_response_active:
                                            if has_seen_reasoning and is_reasoning_active:
                                                print(f"\n\n🤖 RESPONSE:")
                                                print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                                            elif not self.thinking_enabled:
                                                print(f"\n🤖 Assistant: ", end="", flush=True)
                                            is_final_response_active = True
                                            is_reasoning_active = False

                                        print(content, end="", flush=True)
                                        full_response += content
                                        chars_received += len(content)

                                        # Show progress every 500 characters
                                        if chars_received % 500 == 0:
                                            print(f"\n📊 Received: {chars_received} chars")
                                            
                            except json.JSONDecodeError:
                                continue
            except KeyboardInterrupt:
                print("\n\n⏹️ [Streaming interrupted by user]")
                response.close()

                save_partial = input("\n💾 Save partial response? (y/n): ").strip().lower()
                if save_partial == 'y' and full_response:
                    self.add_to_history("assistant", full_response + "\n[Response interrupted by user]")
                    return full_response + "\n[Response interrupted by user]"
                else:
                    self.conversation_history.pop()
                    return None

            # Add the complete response to history
            if full_response:
                self.add_to_history("assistant", full_response)

                print(f"\n\n✅ Response saved to conversation history")
                print(f"📊 Stats: {len(full_response)} characters")

            # ============================================
            # AUTO-FIX LOGIC
            # ============================================

            # Check if we're in auto-fix mode and have a file to fix
            if (hasattr(self, 'auto_fix_mode') and self.auto_fix_mode and 
                hasattr(self, 'current_fix_file') and self.current_fix_file and 
                full_response):

                print(f"\n{'='*80}")
                self._safe_print(f"🔧 AUTO-FIX MODE: Processing AI response...")
                print(f"{'='*80}")

                # Parse the AI response for PROPOSED CHANGE blocks
                changes_found = self._parse_ai_changes_for_file(full_response, self.current_fix_file)

                if changes_found > 0:
                    print(f"✅ Found {changes_found} proposed change(s)")
                    self._handle_auto_fix_confirmation()
                else:
                    print(f"📭 No PROPOSED CHANGE blocks found")
                    print(f"💡 Tip: Ask the AI to use the PROPOSED CHANGE format")

                # Reset auto-fix mode
                self.auto_fix_mode = False
                self.current_fix_file = None

            print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print(f"✅ Command completed. Ready for next input.")
            print()

            return full_response

        except requests.exceptions.Timeout:
            print(f"\n❌ Request timed out after 60 seconds")
            print(f"💡 Try reducing the file size or using a simpler query")
            self.conversation_history.pop()
            return None
        except requests.exceptions.RequestException as e:
            print(f"\n❌ Network error: {e}")
            self.conversation_history.pop()
            return None
        except Exception as e:
            print(f"\n⚠️  Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return None

        except requests.exceptions.Timeout:
            print("\nRequest timed out. Please try again.")
            self.conversation_history.pop()
            return None
        except requests.exceptions.RequestException as e:
            print(f"\nRequest failed: {e}")
            self.conversation_history.pop()
            return None

    async def stream_response_async(self, prompt: str, **kwargs):
        """Async version - handles search and model commands asynchronously"""
        # Special case for /search (native async)
        if prompt.startswith("/search"):
            query = prompt[7:].strip()
            self._safe_print(f"\n🔍 Searching for: {query}")
            success, result = await self.searcher.search(query)
            if success:
                self.add_search_results_to_history('web', query, result)
            else:
                # Add error to history as system message
                self.add_to_history("system", f"Web search failed for '{query}': {result}")
            self._safe_print(f"\n{result}\n")
            return None

        # Use command registry for other commands (excluding /search, /fix, /analyze)
        for prefix in sorted(self.command_handlers.keys(), key=len, reverse=True):
            if prefix in ["/search", "/fix", "/analyze"]:
                continue
            if prompt.startswith(prefix):
                handler, strip_prefix = self.command_handlers[prefix]
                arg = prompt[len(prefix):].strip() if strip_prefix else prompt
                # Run sync handler in thread pool
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, handler, arg)

                # Special handling for /code apply confirm
                if prefix == "/code":
                    subcommand = arg
                    if subcommand.startswith("apply confirm") or subcommand == "apply force":
                        force = "force" in subcommand
                        response = self._code_apply_changes_confirm(force)

                if response is not None:
                    self._safe_print(f"\n{response}\n")
                return None

        # No command matched, fall back to sync stream_response
        return self.stream_response(prompt, **kwargs)

        return self.stream_response(prompt, **kwargs)

    def run_async(self, prompt: str, **kwargs):
        """Helper to run async from sync code"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                self.stream_response_async(prompt, **kwargs)
            )
            return result
        finally:
            loop.close()

    def _handle_auto_fix_confirmation(self):
        """Handle the auto-fix confirmation flow"""
        if not self.code_changes_pending:
            print(f"📭 No changes to apply")
            return

        print(f"\n📋 CHANGES TO APPLY:")
        print(f"{'-'*80}")

        # Group changes by file
        changes_by_file = {}
        for change in self.code_changes_pending:
            file_path = change['file_path']
            if file_path not in changes_by_file:
                changes_by_file[file_path] = []
            changes_by_file[file_path].append(change)

        for file_path, changes in changes_by_file.items():
            print(f"\n📄 {file_path}:")
            for i, change in enumerate(changes, 1):
                print(f"  {i}. {change['description']}")
                if 'old_code' in change and 'new_code' in change:
                    # Show first line of change
                    old_first = change['old_code'].split('\n')[0][:50]
                    new_first = change['new_code'].split('\n')[0][:50]
                    print(f"     - {old_first}{'...' if len(old_first) >= 50 else ''}")
                    print(f"     + {new_first}{'...' if len(new_first) >= 50 else ''}")
        
        print(f"\n{'='*80}")

        # Get user confirmation
        print(f"\n❓ Apply these changes?")
        print(f"   Options:")
        print(f"   1. Type 'yes' to apply all changes")
        print(f"   2. Type 'diff' to see the changes before applying")
        print(f"   3. Type 'no' to save as pending changes")
        print(f"   4. Type 'cancel' to discard changes")
        print(f"\n   Your choice: ", end="", flush=True)
        
        try:
            import sys
            if sys.stdin.isatty():
                choice = input().strip().lower()

                if choice in ['yes', 'y', 'ok', 'apply', '1']:
                    print(f"\n🔄 Applying changes...")

                    # Show diff before applying
                    if hasattr(self, 'original_file_content'):
                        success, message, current_content = self.code_analyzer.read_file_safe(self.current_fix_file)
                        if success:
                            print(f"\n📊 Showing changes:")
                            self.show_diff(self.original_file_content, current_content, self.current_fix_file)

                    # Apply the changes
                    result = self._code_apply_changes_confirm(force=True)
                    print(f"\n{result}")

                elif choice in ['diff', 'show', 'preview', '2']:
                    if hasattr(self, 'original_file_content'):
                        success, message, current_content = self.code_analyzer.read_file_safe(self.current_fix_file)
                        if success:
                            print(f"\n📊 DIFF VIEW:")
                            self.show_diff(self.original_file_content, current_content, self.current_fix_file)

                            # Ask again after showing diff
                            if self.get_user_confirmation("\nApply these changes now?", "no"):
                                print(f"\n🔄 Applying changes...")
                                result = self._code_apply_changes_confirm(force=True)
                                print(f"\n{result}")
                            else:
                                print(f"\n⏸️  Changes saved as pending.")
                                print(f"💡 Use '/code changes' to review or '/code apply' to apply later.")
                        else:
                            print(f"\n⚠️  Could not show diff: {message}")
                    else:
                        print(f"\n⚠️  Original content not available for diff")

                elif choice in ['no', 'n', 'save', '3']:
                    print(f"\n⏸️  Changes saved as pending.")
                    print(f"💡 Use '/code changes' to review or '/code apply' to apply later.")

                elif choice in ['cancel', 'discard', '4']:
                    count = len(self.code_changes_pending)
                    self.code_changes_pending = []
                    print(f"\n🗑 ️  Discarded {count} pending changes")

                else:
                    print(f"\n❓ Unknown option. Changes saved as pending.")
                    print(f"💡 Use '/code changes' to review or '/code apply' to apply.")
            
            else:
                print(f"\n⚠️  Non-interactive mode. Changes saved as pending.")
                print(f"💡 Use '/code changes' to review or '/code apply' to apply.")
        
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n⏸️  Input interrupted. Changes saved as pending.")
            print(f"💡 Use '/code changes' to review or '/code apply' to apply.")

        except Exception as e:
            print(f"\n⚠️  Error: {e}")
            print(f"💡 Changes saved as pending. Use '/code changes' to review.")
    
    def auto_detect_and_read_file(self, text: str) -> Optional[str]:
        """
        Automatically detect file paths in text and read them
        Returns: File content if found and readable
        """
        import re  # ADD THIS LINE at the beginning of the method!

        # Patterns for file paths
        patterns = [
            r'[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+\.\w+',  # Windows absolute
            r'/(?:[^/]+\/)*[^/]+\.[a-zA-Z0-9]+',  # Unix absolute
            r'(?:\.{1,2}/)?(?:[^/\s]+/)*[^/\s]+\.[a-zA-Z0-9]+',  # Relative
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                # Check if it looks like a real file path (not just random text)
                if any(ext in match for ext in ['.py', '.js', '.java', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css']):
                    # Safety confirmation for auto-file operations
                    if self.safety_confirm_file_operations:
                        print(f"🔍 Detected file reference: {match}")
                        response = input("Read file? (y/n): ").strip().lower()
                        if response not in ('y', 'yes'):
                            log_operation("auto_file_read", match, False, "user_denied_confirmation")
                            continue
                        else:
                            log_operation("auto_file_read", match, True, "user_confirmed")
                    try:
                        # Try to read the file
                        if not self.code_analyzer:
                            self.code_analyzer = CodeAnalyzer(safety_manager=self.safety_manager)

                        success, message, content = self.code_analyzer.read_file_safe(match)
                        if success:
                            self._safe_print(f"📄 Auto-reading detected file: {match}")
                            log_operation("auto_file_read", match, True, f"size={len(content)}")
                            return content
                        else:
                            log_operation("auto_file_read", match, False, f"reason={message}")
                    except Exception as e:
                        log_operation("auto_file_read", match, False, f"exception={str(e)}")
                        continue

        return None

    def classify_and_enhance_input(self, text: str) -> Optional[str]:
        """
        Classify input type and convert to appropriate command if it's a direct object.
        Returns command string or None if no classification.
        """
        import re
        text = text.strip()

        # If it's already a command, don't reclassify
        if text.startswith('/'):
            return None

        # 1. URL detection
        url_pattern = r'^(https?://[^\s]+)$'
        if re.match(url_pattern, text, re.IGNORECASE):
            self._safe_print(f"🔗 Detected URL: {text}")
            log_operation("url_detection", text, True, "auto_classified_as_url")
            return f"/read {text}"

        # 2. File path with optional line numbers (e.g., file.py:15, file.py:10-20)
        # Match whole string as a file path
        file_line_pattern = r'^([A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+\.\w+)(?::(\d+)(?:-(\d+))?)?$'
        file_line_pattern_unix = r'^(/(?:[^/]+/)*[^/]+\.[a-zA-Z0-9]+)(?::(\d+)(?:-(\d+))?)?$'
        file_line_pattern_rel = r'^((?:\.{1,2}/)?(?:[^/\s]+/)*[^/\s]+\.[a-zA-Z0-9]+)(?::(\d+)(?:-(\d+))?)?$'

        for pattern in [file_line_pattern, file_line_pattern_unix, file_line_pattern_rel]:
            match = re.match(pattern, text)
            if match:
                file_path = match.group(1)
                line_start = match.group(2) if match.group(2) else None
                line_end = match.group(3) if match.group(3) else None

                # Check if it's a known file extension
                if any(ext in file_path for ext in ['.py', '.js', '.java', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css']):
                    self._safe_print(f"📄 Detected file path with line numbers: {text}")
                    log_operation("file_path_detection", text, True, f"path={file_path}, lines={line_start}-{line_end}")

                    # Build appropriate command
                    if line_start:
                        if line_end:
                            return f"/read {file_path}:{line_start}-{line_end}"
                        else:
                            return f"/read {file_path}:{line_start}"
                    else:
                        return f"/read {file_path}"

        # 3. Simple filename (just a filename without path)
        simple_file_pattern = r'^([^/\s]+\.\w+)$'
        match = re.match(simple_file_pattern, text)
        if match:
            filename = match.group(1)
            if any(ext in filename for ext in ['.py', '.js', '.java', '.txt', '.md', '.json', '.yaml', '.yml', '.html', '.css']):
                self._safe_print(f"📄 Detected simple filename: {filename}")
                log_operation("filename_detection", text, True, f"filename={filename}")
                return f"/read {filename}"

        # 4. Code reference pattern (e.g., "function_name()", "ClassName.method", "module.Class")
        # This is more speculative - might trigger false positives
        code_ref_pattern = r'^([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*\(\)?)$'
        match = re.match(code_ref_pattern, text)
        if match and len(text.split()) == 1:  # Single token only
            self._safe_print(f"🔍 Detected possible code reference: {text}")
            log_operation("code_reference_detection", text, True, "possible_code_reference")
            # Could trigger code search, but might be too aggressive
            # Let's not auto-convert this, as it could be many things

        return None

    def handle_auto_file_analysis(self, file_path: str) -> str:
        """
        Automatically handle file analysis when mentioned
        """
        if not self.code_analyzer:
            self.code_analyzer = CodeAnalyzer(safety_manager=self.safety_manager)
        
        # Try to read the file
        success, message, content = self.code_analyzer.read_file_safe(file_path)
        
        if not success:
            return self.formatter.error(f"Could not read file {file_path}: {message}")
        
        # Add to conversation history
        self.add_to_history("user", f"""I want to analyze this file:

File: {file_path}

```python
{content[:5000]}  # Limit to avoid token overflow
```

Please analyze this code and suggest any improvements, fixes, or optimizations.""")

        return self.formatter.success(f"Successfully loaded {file_path} for analysis. Please continue with your request.")
    
    def handle_auto_fix_command(self, command: str) -> Optional[str]:
        """
        Handle automatic fixing commands:
        /fix <file_path> - Analyze and fix file
        /analyze <file_path> - Analyze file without auto-fix
        """
        parts = command.split()
        if len(parts) < 2:
            print("Usage: /fix <file_path> [description]\nExample: /fix agent/core.py 'fix the error handling'")
            return None

        cmd_type = parts[0]  # /fix or /analyze
        file_path = parts[1]
        description = " ".join(parts[2:]) if len(parts) > 2 else "Please analyze and fix any issues"

        # Auto-switch to coding mode for fix/analyze commands
        if self.mode != 'coding':
            self.switch_mode('coding', persist=False)

        self._safe_print(f"🔧 {'Fixing' if cmd_type == '/fix' else 'Analyzing'}: {file_path}")
        self._safe_print(f"📝 Description: {description}")

        # Initialize code analyzer if needed
        if not self.code_analyzer:
            self.code_analyzer = CodeAnalyzer(safety_manager=self.safety_manager)

        # Read the file
        success, message, content = self.code_analyzer.read_file_safe(file_path)
        if not success:
            self._safe_print(f"❌ Cannot read file: {message}")
            return None

        # Store original content for diff
        self.original_file_content = content

        # CODE-SPECIFIC INSTRUCTIONS - Only added for code actions
        code_instructions = """
        CRITICAL INSTRUCTIONS FOR PROPOSING CHANGES:

        1. **Only propose changes to ACTUAL CODE** that exists in the file
        2. **NEVER include "Truncated for large files"** or similar comments in Old Code
        3. **Old Code must be EXACT code** from the file, with proper indentation
        4. **New Code should be the replacement** with improvements
        5. **Line numbers should be accurate** if provided

        When analyzing code, look for:
        - Missing error handling (try/except blocks)
        - Resource leaks (files, sessions not closed)
        - Security issues (hardcoded secrets, input validation)
        - Performance issues (inefficient loops, duplicate code)
        - Code quality (long functions, missing comments)

        ALWAYS use this exact format for proposing changes:

        PROPOSED CHANGE:
        File: [file_path]
        Description: [brief description]
        Old Code: [EXACT code from the file to replace]
        New Code: [improved replacement code]
        Line: [line number if known]

        Example of CORRECT format:
        PROPOSED CHANGE:
        File: agent/core.py
        Description: Add error handling for file reading
        Old Code: with open(file_path, 'r') as f:
                    content = f.read()
        New Code: try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except FileNotFoundError:
                    return "File not found"
                except PermissionError:
                    return "Permission denied"
        Line: 123

        Do NOT include comments about truncation or sample code!
        """

        # Create analysis prompt with code-specific instructions
        analysis_prompt = f"""I want to {cmd_type[1:]} this file:

    File: {file_path}

    {description}

    Here's the current code (first 4000 characters):
    ```python
    {content[:4000]}
    ```

    {code_instructions}

    Please analyze the code and provide specific fixes. If you find issues, propose changes in the PROPOSED CHANGE format."""

        # Add to history and trigger analysis
        self.add_to_history("user", analysis_prompt)

        # Set auto-fix mode
        self.auto_fix_mode = (cmd_type == '/fix')
        self.current_fix_file = file_path

        self._safe_print(f"🤖 AI is analyzing the file. It will propose changes automatically...")

        # Return None to let the normal streaming handle the response
        return None
    
    def _parse_ai_changes_for_file(self, ai_response: str, file_path: str) -> int:
        """Parse AI response for proposed changes and add to pending changes"""
        import re

        # Pattern to find PROPOSED CHANGE blocks
        pattern = r'PROPOSED CHANGE:\s*File:\s*(.+?)\s*Description:\s*(.+?)\s*Old Code:\s*(?:```(?:\w+)?)?\s*(.+?)\s*(?:```)?\s*New Code:\s*(?:```(?:\w+)?)?\s*(.+?)\s*(?:```)?\s*(?:Line:\s*(\d+))?'
        
        changes = re.findall(pattern, ai_response, re.DOTALL | re.IGNORECASE)

        change_count = 0
        for match in changes:
            match_file = match[0].strip()
            description = match[1].strip()
            old_code = match[2].strip()
            new_code = match[3].strip()
            line = int(match[4].strip()) if match[4] and match[4].strip().isdigit() else None

            # Clean code blocks
            old_code = re.sub(r'^```\w*\s*|\s*```$', '', old_code).strip()
            new_code = re.sub(r'^```\w*\s*|\s*```$', '', new_code).strip()

            self._safe_print(f"\n🔍 Validating change: {description}")
            
            # Skip if old_code is clearly invalid
            if "# truncated for large files" in old_code.lower() or "# sample code" in old_code.lower():
                self._safe_print(f"❌ Skipping invalid change (contains truncation comment)")
                continue

            # Try to validate, but be more lenient
            is_valid, error_msg = self.validate_proposed_change(old_code, new_code, file_path)

            if not is_valid:
                self._safe_print(f"⚠️  Change validation warning: {error_msg}")
                self._safe_print(f"💡 Still adding to pending changes for manual review")
                # Still add it, but mark as needs review
                description = f"[Needs Review] {description}"
            
            # Add to pending changes
            self.propose_code_change(file_path, old_code, new_code, description, line)
            change_count += 1
            self._safe_print(f"✅ Added change to pending changes")

        return change_count

    def _auto_apply_changes_with_confirmation(self):
        """
        Automatically apply changes after user confirmation
        """
        if not self.code_changes_pending:
            self._safe_print("📭 No changes to apply.")
            return

        # Show what will be changed
        print("\n" + "="*60)
        self._safe_print("📋 PROPOSED CHANGES:")
        print("="*60)
        
        for change in self.code_changes_pending:
            self._safe_print(f"\n📄 File: {change['file_path']}")
            self._safe_print(f"📝 {change['description']}")
            if 'old_code' in change and 'new_code' in change:
                print(f"   - {change['old_code'][:80]}{'...' if len(change['old_code']) > 80 else ''}")
                print(f"   + {change['new_code'][:80]}{'...' if len(change['new_code']) > 80 else ''}")

        print("\n" + "="*60)
        print("❓ Apply these changes? (yes/no/cancel): ", end="", flush=True)
        
        # Get user response
        try:
            import sys
            if sys.stdin.isatty():
                response = input()
            else:
                # If running in non-interactive mode
                print("\n⚠️  Running in non-interactive mode. Changes will not be applied.")
                return
        except:
            print("\n⚠️  Could not get user input. Changes will not be applied.")
            return

        if response.lower() in ['yes', 'y', 'ok', 'apply']:
            print("\n🔄 Applying changes...")
            result = self._code_apply_changes_confirm(force=True)
            print(f"\n{result}")
        elif response.lower() in ['no', 'n']:
            print("\n❌ Changes not applied. You can view them with /code changes")
        else:
            print("\n⏸️  Changes kept pending. Use /code changes to review or /code apply to apply.")

    def get_user_confirmation(self, question: str, default: str = "no") -> bool:
        """
        Get yes/no confirmation from user
        """
        import sys

        if not sys.stdin.isatty():
            print(f"⚠️  Non-interactive mode. Assuming '{default}'")
            return default.lower() in ['yes', 'y']

        valid_responses = {'yes': True, 'y': True, 'no': False, 'n': False}

        while True:
            print(f"\n{question} (yes/no): ", end="", flush=True)
            try:
                response = input().strip().lower()
                if response in valid_responses:
                    return valid_responses[response]
                elif response == '':
                    return default.lower() in ['yes', 'y']
                else:
                    print("Please answer 'yes' or 'no'")
            except (EOFError, KeyboardInterrupt):
                print("\n\nInterrupted. Assuming 'no'")
                return False

    def _check_file_threshold(self, total_files: int, operation_description: str = "process files") -> Tuple[bool, Optional[int]]:
        """
        Check if total files exceeds thresholds and ask user for confirmation.

        Args:
            total_files: Total number of files detected
            operation_description: Description of the operation for the prompt

        Returns:
            Tuple[bool, Optional[int]]: (should_continue, limit)
                - should_continue: True if user wants to continue, False otherwise
                - limit: Suggested limit for file operations (None for no limit)
        """
        # Thresholds for confirmation
        thresholds = [100, 200, 300]
        exceeded_threshold = None

        for threshold in sorted(thresholds, reverse=True):
            if total_files >= threshold:
                exceeded_threshold = threshold
                break

        limit = 200  # Default limit for performance

        if exceeded_threshold is not None:
            self._safe_print(f"📊 Found {total_files} total files in codebase (exceeds threshold: {exceeded_threshold})")
            if self.get_user_confirmation(f"Continue to {operation_description} for all {total_files} files?", "no"):
                limit = None  # No limit, process all files
                self._safe_print(f"✅ Processing all {total_files} files...")
                return True, limit
            else:
                limit = 100  # Reduced limit for safety
                self._safe_print(f"⚠️  Using reduced limit of {limit} files for safety.")
                return False, limit  # User declined full operation

        # If no threshold exceeded, continue with default limit
        return True, limit

    def show_diff(self, old_content: str, new_content: str, filename: str = "file"):
        """
        Show colored diff between old and new content
        """
        try:
            import difflib

            print(f"\n📊 DIFF: {filename}")
            print("="*60)
            
            old_lines = old_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)

            # Generate unified diff
            diff = difflib.unified_diff(
                old_lines, new_lines,
                fromfile=f'Original: {filename}',
                tofile=f'Modified: {filename}',
                lineterm='',
                n=3  # Context lines
            )
            
            # Print with colors
            for line in diff:
                if line.startswith('---') or line.startswith('+++'):
                    print(f"\033[90m{line}\033[0m")  # Gray for headers
                elif line.startswith('-'):
                    print(f"\033[91m{line}\033[0m")  # Red for deletions
                elif line.startswith('+'):
                    print(f"\033[92m{line}\033[0m")  # Green for additions
                else:
                    print(f"\033[90m{line}\033[0m")  # Gray for context

            # Also show summary
            print(f"\n📈 Summary:")
            print(f"  Original: {len(old_lines)} lines")
            print(f"  Modified: {len(new_lines)} lines")
            print(f"  Changes: {abs(len(new_lines) - len(old_lines))} lines added/removed")
            print("="*60)
            
        except Exception as e:
            print(f"⚠️ Could not generate diff: {e}")
            print(f"📄 Showing simple comparison instead:")
            print("="*60)
            print(f"Original (first 200 chars):\n{old_content[:200]}")
            print(f"\nModified (first 200 chars):\n{new_content[:200]}")
            print("="*60)

    def validate_proposed_change(self, old_code: str, new_code: str, file_path: str) -> Tuple[bool, str]:
        """
        Validate that a proposed change is valid

        Returns: (is_valid, error_message)
        """
        # Check if old_code is empty or just a comment
        if not old_code or old_code.strip() == "":
            return False, "Old Code cannot be empty"

        # Check if old_code contains truncation comments
        truncation_phrases = [
            "truncated for large files",
            "truncated for context",
            "first 4000 characters",
            "first 3000 characters",
            "sample code",
            "example code",
            "..."
        ]

        old_code_lower = old_code.lower()
        for phrase in truncation_phrases:
            if phrase in old_code_lower:
                return False, f"Old Code contains truncation comment: '{phrase}'"

        # Check if old_code looks like actual code (not just a comment)
        lines = old_code.split('\n')
        code_lines = [line for line in lines if line.strip() and not line.strip().startswith('#')]
        
        if len(code_lines) == 0:
            # Only comments, not actual code
            return False, "Old Code contains no actual code (only comments)"
        
        # Read the actual file to check if old_code exists
        success, message, actual_content = self.code_analyzer.read_file_safe(file_path)
        if not success:
            return False, f"Cannot read file to validate: {message}"
        
        # Check if old_code exists in the file (allow for minor whitespace differences)
        normalized_old = re.sub(r'\s+', ' ', old_code.strip())
        normalized_file = re.sub(r'\s+', ' ', actual_content)

        if normalized_old not in normalized_file:
            # Try to find similar code
            similar = self.find_similar_code(old_code, actual_content)
            if similar:
                return False, f"Old Code not found. Did you mean:\n{similar[:200]}"
            else:
                return False, "Old Code not found in the file"
        
        return True, "Valid"
    
    def find_similar_code(self, old_code: str, file_content: str, context_lines: int = 3) -> str:
        """
        Find code similar to old_code in file_content
        Returns: Similar code snippet with context
        """
        import difflib

        # Clean the old_code
        old_code_clean = old_code.strip()

        # Split into lines
        file_lines = file_content.splitlines()

        # If old_code is very short, just return empty
        if len(old_code_clean) < 10:
            return ""
        
        # Try to find exact or similar matches
        best_match = None
        best_ratio = 0

        # Check if any line contains the old_code
        for i, line in enumerate(file_lines):
            if old_code_clean in line:
                # Found exact substring
                start = max(0, i - context_lines)
                end = min(len(file_lines), i + context_lines + 1)
                return "\n".join(file_lines[start:end])

        # Try to find similar code using difflib
        # Break the file into chunks and compare
        chunk_size = min(10, len(file_lines))
        
        for i in range(0, len(file_lines) - chunk_size + 1, chunk_size // 2):
            chunk = "\n".join(file_lines[i:i+chunk_size])
            
            # Calculate similarity ratio
            ratio = difflib.SequenceMatcher(None, old_code_clean, chunk).ratio()
            
            if ratio > best_ratio:
                best_ratio = ratio
                start = max(0, i - context_lines)
                end = min(len(file_lines), i + chunk_size + context_lines)
                best_match = "\n".join(file_lines[start:end])
        
        # If we found something reasonably similar (ratio > 0.3)
        if best_match and best_ratio > 0.3:
            return best_match
        else:
            # Return a snippet around the middle of the file
            middle = len(file_lines) // 2
            start = max(0, middle - context_lines * 2)
            end = min(len(file_lines), middle + context_lines * 2)
            return "\n".join(file_lines[start:end])