# cli/interface.py
import os
from typing import Optional

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False
    print("Note: For better experience, install prompt_toolkit: pip install prompt_toolkit")

from agent import DeepSeekStreamingChat
from .input_handlers import get_multiline_input_with_prompt_toolkit, get_multiline_input_fallback


def display_welcome_banner():
    """Display welcome banner with instructions"""
    print("\n" + "="*60)
    print("DeepSeek Streaming Chat (Enhanced with Thinking Stream)")
    print("="*60)
    print("Commands:")
    print("  /clear   - Clear conversation history")
    print("  /history - Show conversation history")
    print("  /think   - Toggle thinking mode")
    print("  /test    - Run development tests")
    print("  /search  - Search web")
    print("  /quit    - Exit the chat")
    print("="*60)
    print("Features:")
    print("   Thinking process streams in subtle gray")
    print("   Clear visual separation between thinking and response")
    print("   Use \\ + Enter for line continuation")
    print("   Press Ctrl+C during input to cancel")
    print("   Press Ctrl+C during streaming to interrupt response")
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


def interactive_chat_with_prompt_toolkit():
    """Interactive chat using prompt_toolkit"""
    api_key = get_api_key()
    if not api_key:
        return

    try:
        chat = DeepSeekStreamingChat(api_key=api_key)
    except ValueError as e:
        print(f"Error initializing chat: {e}")
        return

    display_welcome_banner()

    session = PromptSession(history=InMemoryHistory())

    while True:
        try:
            user_input = get_multiline_input_with_prompt_toolkit(session)

            if user_input is None:
                continue

            user_input = user_input.strip()

            # Handle commands
            command_result = handle_command(chat, user_input, session)
            if command_result is False:
                break
            elif command_result is True:
                continue

            if not user_input:
                continue

            # Process input
            if user_input.startswith("/search"):
                print(f"\n Running async search...")
                chat.run_async(user_input)
            else:
                chat.stream_response(user_input)

        except KeyboardInterrupt:
            print("\n\nCtrl+C detected. Exiting...")
            break
        except EOFError:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            continue


def interactive_chat_fallback():
    """Fallback interactive chat without prompt_toolkit"""
    api_key = get_api_key()
    if not api_key:
        return

    try:
        chat = DeepSeekStreamingChat(api_key=api_key)
    except ValueError as e:
        print(f"Error initializing chat: {e}")
        return

    display_welcome_banner()

    while True:
        try:
            user_input = get_multiline_input_fallback()

            if user_input is None:
                continue

            user_input = user_input.strip()

            # Handle commands
            command_result = handle_command(chat, user_input)
            if command_result is False:
                break
            elif command_result is True:
                continue

            if not user_input:
                continue

            # Process input
            chat.stream_response(user_input)

        except KeyboardInterrupt:
            print("\n\nCtrl+C detected. Exiting...")
            break
        except EOFError:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            continue