# cli/interface.py
import os
import sys
from typing import Optional

# Fix for Windows terminal detection in MINGW/Cygwin before any prompt_toolkit imports
if sys.platform == "win32" and "xterm" in os.environ.get("TERM", ""):
    # Force prompt_toolkit to use VT100 output instead of Win32 console API
    os.environ["PROMPT_TOOLKIT_NO_WIN32_CONSOLE"] = "1"
    os.environ["PROMPT_TOOLKIT_FORCE_VT100_OUTPUT"] = "1"

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.output.defaults import create_output
    from prompt_toolkit.key_binding import KeyBindings
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False
    print("Note: For better experience, install prompt_toolkit: pip install prompt_toolkit")

from agent import DeepSeekStreamingChat
from agent.help_system import HelpSystem
from agent_config import agent_config
from .input_handlers import get_multiline_input_with_prompt_toolkit, get_multiline_input_fallback
from .completers import CommandCompleter
from .progress_display import ProgressDisplay, get_global_progress, format_simple_status, TaskStatus
import time

# Try to import readline for basic tab completion in fallback mode
try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False


def display_status_bar(chat):
    """Display status bar for coding mode."""
    if not chat.show_status_bar:
        return
    status = chat.get_status_info()
    lines = []
    lines.append(f"Mode: {status['mode']}")
    lines.append(f"Tokens: {status['token_usage']}")
    if status['pending_changes']:
        lines.append(f"Pending changes: {status['pending_changes']}")
    if status['recent_files']:
        lines.append(f"Recent: {', '.join(status['recent_files'][:2])}")
    status_line = " | ".join(lines)
    print(f"\033[90m{status_line}\033[0m")  # Gray color


def display_command_status(command: str, status: str = "executing"):
    """Display command execution status."""
    # status can be: executing, completed, failed
    colors = {
        "executing": "\033[93m",  # Yellow
        "completed": "\033[92m",  # Green
        "failed": "\033[91m",     # Red
    }
    # Use ASCII symbols for Windows compatibility
    status_symbols = {
        "executing": "->",
        "completed": "[OK]",
        "failed": "[ERROR]",
    }
    color = colors.get(status, "\033[90m")
    symbol = status_symbols.get(status, " ")
    print(f"{color}{symbol} {command}...\033[0m")

def display_welcome_banner(mode: str = "chat"):
    """Display welcome banner with instructions"""
    mode_display = f"[{mode.upper()} MODE]"
    print("\n" + "="*60)
    print(f"DeepSeek Streaming Chat (Enhanced with Thinking Stream) {mode_display}")
    print("="*60)
    print("Commands:")
    print("  /clear   - Clear conversation history")
    print("  /history - Show conversation history")
    print("  /think   - Toggle thinking mode")
    print("  /test    - Run development tests")
    print("  /search  - Search web")
    print("  /quit    - Exit the chat")
    print("  /auto    - Control auto-features (search/interpret)")
    print("  /mode    - Switch between chat and coding modes")
    print("="*60)
    print("Features:")
    print("   Thinking process streams in subtle gray")
    print("   Clear visual separation between thinking and response")
    print("   Use \\ + Enter for line continuation")
    print("   Press Ctrl+C during input to cancel")
    print("   Press Ctrl+C during streaming to interrupt response")
    if mode == "coding":
        print("   Auto-file operations enabled")
        print("   Workspace context awareness")
        print("   Enhanced natural language interpretation")
    print("\nSearch Usage:")
    print("  /search <query>    - Search DuckDuckGo")
    print("  Example: /search latest AI news")
    print("="*60 + "\n")


def get_api_key() -> Optional[str]:
    """Get API key from environment or user input"""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY environment variable not found.")
        print("Please set it in your .env file or enter it now.")
        api_key = input("Enter your DeepSeek API key: ").strip()
        if not api_key:
            print("API key is required!")
            return None
    return api_key


def handle_command(chat: DeepSeekStreamingChat, command: str, session=None) -> bool:
    """Handle CLI commands, returns True if should continue"""
    if command.lower() in ['/quit', '/exit', 'quit', 'exit']:
        print("Goodbye!")
        return False
    elif command.lower() == '/clear':
        chat.clear_history()
        if session:
            session.history = InMemoryHistory()
        print("Conversation history cleared.")
        return True
    elif command.lower() == '/history':
        print("\nConversation History:")
        for i, msg in enumerate(chat.conversation_history):
            role = "System" if msg["role"] == "system" else "User" if msg["role"] == "user" else "Assistant"
            content = msg["content"]
            preview = content[:150] + "..." if len(content) > 150 else content
            print(f"{i+1}. {role}: {preview}")
        print()
        return True
    elif command.lower() == '/think':
        thinking_status = chat.toggle_thinking_mode()
        status_text = "ON" if thinking_status else "OFF"
        print(f"\nThinking mode is now: {status_text}")
        return True
    elif command.lower() == '/test':
        print("\nRunning development tests...")
        try:
            import dev_test
            success = dev_test.run_tests()
            if success:
                print("\nTests completed successfully.")
            else:
                print("\nTests failed.")
        except ImportError as e:
            print(f"Failed to run tests: {e}")
        return True

    return None  # Not a command


def interactive_chat_with_prompt_toolkit(mode: str = "chat"):
    """Interactive chat using prompt_toolkit"""

    api_key = get_api_key()
    if not api_key:
        return

    try:
        chat = DeepSeekStreamingChat(api_key=api_key)
    except ValueError as e:
        print(f"Error initializing chat: {e}")
        return

    # Ensure mode is set (chat object reads from config)
    if chat.mode != mode:
        chat.switch_mode(mode)

    display_welcome_banner(chat.mode)

    try:
        # Try to create output explicitly to handle MinGW/Cygwin environments
        try:
            output = create_output()
            session = PromptSession(history=InMemoryHistory(), output=output)
        except Exception as output_error:
            # If explicit output creation fails, try default initialization
            print(f"\033[90m[Output creation failed: {output_error}, trying default]\033[0m")
            session = PromptSession(history=InMemoryHistory())
    except Exception as e:
        print(f"Warning: prompt_toolkit failed to initialize: {e}")
        print("Falling back to basic input mode...")
        interactive_chat_fallback(mode)
        return

    # Initialize auto-completion system
    completer = None
    if chat.mode == "coding" and agent_config.coding_mode_enable_auto_complete:
        try:
            help_system = HelpSystem()
            workspace_manager = chat.workspace_manager
            # Ensure workspace manager is initialized for coding mode
            if workspace_manager is None and chat.mode == "coding":
                chat._initialize_workspace_manager()
                workspace_manager = chat.workspace_manager

            completer = CommandCompleter(
                help_system=help_system,
                workspace_manager=workspace_manager
            )
            print(f"\033[92m[Auto-completion enabled] Type '/' and see suggestions, press Tab to complete\033[0m")
        except Exception as e:
            print(f"\033[90m[Auto-completion error: {e}]\033[0m")

    # Initialize progress display system
    progress = get_global_progress(language="en")
    task_registry = {}  # Map command -> task_id

    # Create key bindings for ctrl+o to toggle task expansion
    kb = KeyBindings()

    @kb.add('c-o')
    def _(event):
        # Debug: print to see if binding fires
        import sys
        sys.stderr.write("\n[Ctrl+O pressed]\n")
        sys.stderr.flush()
        # Get most recent task with description
        task_id = progress.get_most_recent_task_with_description()
        if task_id is None:
            sys.stderr.write("[No task with description found]\n")
            sys.stderr.flush()
            return
        # Toggle expansion for this specific task
        if progress.toggle_task_expansion(task_id):
            task = progress.get_task(task_id)
            if task and task.get("expanded"):
                # Task is now expanded - show description
                desc = task.get("description", "")
                if desc:
                    # Print description directly
                    sys.stderr.write(f"\n--- Expanded thinking content ---\n")
                    sys.stderr.write(desc[:2000])  # Limit length
                    if len(desc) > 2000:
                        sys.stderr.write("\n[... truncated]\n")
                    sys.stderr.write("\n--------------------------------\n")
                    sys.stderr.flush()
            else:
                sys.stderr.write("[Task collapsed]\n")
                sys.stderr.flush()
        else:
            sys.stderr.write("[Failed to toggle expansion]\n")
            sys.stderr.flush()

    # Helper function to display progress and status bar
    def display_interface():
        """Display progress and status bar."""
        progress_display = progress.display(clear_previous=False)
        if progress_display:
            print(progress_display)
        display_status_bar(chat)

    while True:
        try:
            # Clear completed tasks before displaying (keep for 30 seconds)
            progress.clear_completed(retention_seconds=30.0)

            # Display interface
            display_interface()

            user_input = get_multiline_input_with_prompt_toolkit(session, chat.mode, completer, debug=agent_config.debug, key_bindings=kb)

            if user_input is None:
                break

            user_input = user_input.strip()

            # Handle commands
            command_name = None
            if user_input.startswith("/"):
                # Extract command name (first word without slash)
                parts = user_input.split()
                if parts:
                    command_name = parts[0]

            # Create task for progress display
            task_id = None
            if user_input:
                # Determine task title based on input
                if user_input.startswith("/"):
                    if command_name:
                        task_title = command_name
                    else:
                        task_title = "Command"
                else:
                    task_title = "AI Processing" if len(user_input) > 20 else f"Query: {user_input[:30]}..."

                # Create task
                task_id = progress.start_task(
                    title=task_title,
                    description=user_input[:100],
                    tool_uses=0,
                    tokens=0
                )
                # Store task ID for this command
                task_registry[user_input] = task_id
                chat.current_task_id = task_id

                # Display progress for non-command inputs
                if not command_name:
                    progress_display = progress.display(clear_previous=False)
                    if progress_display:
                        print(progress_display)

            # Show executing status for commands (legacy)
            if command_name:
                display_command_status(command_name, "executing")

            # Record start time for duration calculation
            start_time = time.time()

            # Handle command
            command_result = handle_command(chat, user_input, session)

            # Update task if command was handled by handle_command
            if command_result is not None and task_id:
                if command_result is False:
                    progress.fail_task(task_id)
                else:
                    progress.complete_task(task_id)
                # Remove from registry
                if user_input in task_registry:
                    del task_registry[user_input]
                # Clear current task ID from chat
                if hasattr(chat, 'current_task_id'):
                    del chat.current_task_id

            # Update status if command was handled by handle_command (legacy)
            if command_result is not None and command_name:
                display_command_status(command_name, "completed" if command_result is not False else "failed")

            if command_result is False:
                break
            elif command_result is True:
                continue

            if not user_input:
                continue

            # Process input (commands not handled by handle_command)
            if user_input.startswith("/search"):
                # search command already has its own output
                # For async operations, we'll mark task as in progress
                chat.run_async(user_input)
                if task_id:
                    # Search is async, so we can't know when it completes
                    # Mark as completed after a short delay or keep in progress?
                    # For now, complete it immediately
                    progress.complete_task(task_id)
                    if user_input in task_registry:
                        del task_registry[user_input]
                    # Clear current task ID from chat
                    if hasattr(chat, 'current_task_id'):
                        del chat.current_task_id
                if command_name:
                    display_command_status(command_name, "completed")
            else:
                # AI response or other commands
                try:
                    chat.stream_response(user_input)
                except Exception as e:
                    if task_id:
                        progress.fail_task(task_id)
                        if user_input in task_registry:
                            del task_registry[user_input]
                        # Clear current task ID from chat
                        if hasattr(chat, 'current_task_id'):
                            del chat.current_task_id
                    raise

                if task_id:
                    progress.complete_task(task_id)
                    if user_input in task_registry:
                        del task_registry[user_input]
                    # Clear current task ID from chat
                    if hasattr(chat, 'current_task_id'):
                        del chat.current_task_id
                if command_name:
                    display_command_status(command_name, "completed")

        except KeyboardInterrupt:
            print("\n\nCtrl+C detected. Exiting...")
            break
        except EOFError:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            continue


def interactive_chat_fallback(mode: str = "chat"):
    """Fallback interactive chat without prompt_toolkit"""
    api_key = get_api_key()
    if not api_key:
        return

    try:
        chat = DeepSeekStreamingChat(api_key=api_key)
    except ValueError as e:
        print(f"Error initializing chat: {e}")
        return

    # Ensure mode is set (chat object reads from config)
    if chat.mode != mode:
        chat.switch_mode(mode)

    # Setup readline tab completion if available
    if READLINE_AVAILABLE:
        try:
            help_system = HelpSystem()
            commands = list(help_system.help_texts.keys())

            def readline_completer(text, state):
                """Simple tab completer for commands starting with /"""
                # Only complete command names starting with /
                if not text.startswith('/'):
                    return None
                # Remove the leading / for matching
                partial = text[1:].lower()
                matches = [f'/{cmd}' for cmd in commands if cmd.startswith(partial)]
                if state < len(matches):
                    return matches[state]
                return None

            readline.set_completer(readline_completer)
            readline.parse_and_bind("tab: complete")
            # Set completion delimiter to include / as part of word
            readline.set_completer_delims(' \t\n`~!@#$%^&*()-=+[{]}\\|;:\'",<>?')
            print("\033[90m[Basic tab completion enabled for commands]\033[0m")
        except Exception as e:
            print(f"\033[90m[Readline completion error: {e}]\033[0m")

    display_welcome_banner(chat.mode)

    # Initialize progress display system
    progress = get_global_progress(language="en")
    task_registry = {}  # Map command -> task_id

    # Helper function to display progress and status bar
    def display_interface():
        """Display progress and status bar."""
        progress_display = progress.display(clear_previous=False)
        if progress_display:
            print(progress_display)
        display_status_bar(chat)

    while True:
        try:
            # Clear completed tasks before displaying (keep for 30 seconds)
            progress.clear_completed(retention_seconds=30.0)

            # Display interface
            display_interface()

            user_input = get_multiline_input_fallback(chat.mode, debug=agent_config.debug)

            if user_input is None:
                break

            user_input = user_input.strip()

            # Handle commands
            command_name = None
            if user_input.startswith("/"):
                # Extract command name (first word without slash)
                parts = user_input.split()
                if parts:
                    command_name = parts[0]

            # Create task for progress display
            task_id = None
            if user_input:
                # Determine task title based on input
                if user_input.startswith("/"):
                    if command_name:
                        task_title = command_name
                    else:
                        task_title = "Command"
                else:
                    task_title = "AI Processing" if len(user_input) > 20 else f"Query: {user_input[:30]}..."

                # Create task
                task_id = progress.start_task(
                    title=task_title,
                    description=user_input[:100],
                    tool_uses=0,
                    tokens=0
                )
                # Store task ID for this command
                task_registry[user_input] = task_id
                chat.current_task_id = task_id

                # Display progress for non-command inputs
                if not command_name:
                    progress_display = progress.display(clear_previous=False)
                    if progress_display:
                        print(progress_display)

            # Show executing status for commands (legacy)
            if command_name:
                display_command_status(command_name, "executing")

            # Record start time for duration calculation
            start_time = time.time()

            # Handle command
            command_result = handle_command(chat, user_input)

            # Update task if command was handled by handle_command
            if command_result is not None and task_id:
                if command_result is False:
                    progress.fail_task(task_id)
                else:
                    progress.complete_task(task_id)
                # Remove from registry
                if user_input in task_registry:
                    del task_registry[user_input]
                # Clear current task ID from chat
                if hasattr(chat, 'current_task_id'):
                    del chat.current_task_id

            # Update status if command was handled by handle_command (legacy)
            if command_result is not None and command_name:
                display_command_status(command_name, "completed" if command_result is not False else "failed")

            if command_result is False:
                break
            elif command_result is True:
                continue

            if not user_input:
                continue

            # Process input (commands not handled by handle_command)
            try:
                chat.stream_response(user_input)
            except Exception as e:
                if task_id:
                    progress.fail_task(task_id)
                    if user_input in task_registry:
                        del task_registry[user_input]
                raise

            if task_id:
                progress.complete_task(task_id)
                if user_input in task_registry:
                    del task_registry[user_input]
            if command_name:
                display_command_status(command_name, "completed")

        except KeyboardInterrupt:
            print("\n\nCtrl+C detected. Exiting...")
            break
        except EOFError:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            continue