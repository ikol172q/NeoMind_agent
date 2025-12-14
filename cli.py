# cli.py - CLI/UI interface and main program
import os
from dotenv import load_dotenv
load_dotenv()

# Try to import prompt_toolkit
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False
    print("Note: For better experience, install prompt_toolkit: pip install prompt_toolkit")

from agent import DeepSeekStreamingChat


def get_multiline_input_with_prompt_toolkit(session):
    """Get multiline input with prompt_toolkit, supporting \ + Enter for line continuation"""
    lines = []
    prompt = "You: "
    continuation_prompt = "... "

    while True:
        try:
            # Get input line
            line = session.prompt(
                continuation_prompt if lines else prompt,
                multiline=False,
                enable_history_search=False if lines else True  # Only search history on first line
            )

            # Check if line ends with backslash for continuation
            if line.rstrip().endswith('\\'):
                # Remove the trailing backslash and add the line
                lines.append(line.rstrip()[:-1])
                # Continue to next line
                continue
            else:
                # Add the final line
                lines.append(line)
                break

        except KeyboardInterrupt:
            # User pressed Ctrl+C to cancel input
            print("\n[Input cancelled]")
            return None
        except EOFError:
            # User pressed Ctrl+D
            print()
            break

    if not lines:
        return None

    # Join all lines
    return '\n'.join(lines)


def interactive_chat_with_prompt_toolkit():
    """Interactive chat using prompt_toolkit for best cross-platform experience"""
    # Try to get API key from environment
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY environment variable not found.")
        api_key = input("Enter your DeepSeek API key: ").strip()
        if not api_key:
            print("API key is required!")
            return

    # Initialize chat
    chat = DeepSeekStreamingChat(api_key=api_key)

    print("\n" + "="*60)
    print("DeepSeek Streaming Chat (Enhanced with Thinking Stream)")
    print("="*60)
    print("Commands:")
    print("  /clear   - Clear conversation history")
    print("  /history - Show conversation history")
    print("  /think   - Toggle thinking mode (currently: OFF)")
    print("  /search  - Search web (new!)")
    print("  /quit    - Exit the chat")
    print("="*60)
    print("Features:")
    print("   Thinking process streams in yellow color")
    print("   Final response streams in normal color")
    print("   Clear visual separation between thinking and response")
    print("   Use \\ + Enter for line continuation")
    print("   Press Ctrl+C during input to cancel")
    print("   Press Ctrl+C during streaming to interrupt response")
    print("   Use / arrows to navigate through previous queries")
    print("\nSearch Usage:")
    print("  /search <query>    - Search DuckDuckGo")
    print("  Example: /search latest AI news")
    print("="*60 + "\n")

    # Create prompt session with history
    session = PromptSession(history=InMemoryHistory())

    while True:
        try:
            # Get multiline user input
            user_input = get_multiline_input_with_prompt_toolkit(session)

            # Handle cancelled input
            if user_input is None:
                continue

            user_input = user_input.strip()

            # Handle commands
            if user_input.lower() in ['/quit', '/exit', 'quit', 'exit']:
                print("Goodbye!")
                break
            elif user_input.lower() == '/clear':
                chat.clear_history()
                session.history = InMemoryHistory()  # Clear prompt history too
                print("Conversation history cleared.")
                continue
            elif user_input.lower() == '/history':
                print("\nConversation History:")
                for i, msg in enumerate(chat.conversation_history):
                    role = "System" if msg["role"] == "system" else "User" if msg["role"] == "user" else "Assistant"
                    content = msg["content"]
                    preview = content[:150] + "..." if len(content) > 150 else content
                    print(f"{i+1}. {role}: {preview}")
                print()
                continue
            elif user_input.lower() == '/think':
                thinking_status = chat.toggle_thinking_mode()
                status_text = "ON" if thinking_status else "OFF"
                print(f"\nThinking mode is now: {status_text}")
                continue

            # Skip empty input
            if not user_input:
                continue

            # Stream response
            if user_input.startswith("/search"):
                # Run search asynchronously
                print(f"\n Running async search...")
                chat.run_async(user_input)  # This runs async version
            else:
                # Normal chat stays synchronous
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


def get_multiline_input_fallback():
    """Fallback multiline input without prompt_toolkit"""
    lines = []
    print("You: ", end="", flush=True)

    while True:
        try:
            line = input()

            # Check if line ends with backslash for continuation
            if line.rstrip().endswith('\\'):
                # Remove the trailing backslash and add the line
                lines.append(line.rstrip()[:-1])
                # Show continuation prompt
                print("... ", end="", flush=True)
                continue
            else:
                # Add the final line
                lines.append(line)
                break

        except KeyboardInterrupt:
            # User pressed Ctrl+C to cancel input
            print("\n[Input cancelled]")
            return None
        except EOFError:
            # User pressed Ctrl+D
            print()
            break

    if not lines:
        return None

    # Join all lines
    return '\n'.join(lines)


def interactive_chat_fallback():
    """Fallback interactive chat without prompt_toolkit"""
    # Try to get API key from environment
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY environment variable not found.")
        api_key = input("Enter your DeepSeek API key: ").strip()
        if not api_key:
            print("API key is required!")
            return

    # Initialize chat
    chat = DeepSeekStreamingChat(api_key=api_key)

    print("\n" + "="*60)
    print("DeepSeek Streaming Chat (Enhanced with Thinking Stream)")
    print("="*60)
    print("Commands:")
    print("  /clear   - Clear conversation history")
    print("  /history - Show conversation history")
    print("  /think   - Toggle thinking mode (currently: OFF)")
    print("  /search  - Search web (new!)")
    print("  /quit    - Exit the chat")
    print("="*60)
    print("Features:")
    print("   Thinking process streams in yellow color")
    print("   Final response streams in normal color")
    print("   Clear visual separation between thinking and response")
    print("   Use \\ + Enter for line continuation")
    print("   Press Ctrl+C during input to cancel")
    print("   Press Ctrl+C during streaming to interrupt response")
    print("\nSearch Usage:")
    print("  /search <query>    - Search DuckDuckGo")
    print("  Example: /search latest AI news")
    print("="*60 + "\n")

    while True:
        try:
            # Get multiline user input
            user_input = get_multiline_input_fallback()

            # Handle cancelled input
            if user_input is None:
                continue

            user_input = user_input.strip()

            # Handle commands
            if user_input.lower() in ['/quit', '/exit', 'quit', 'exit']:
                print("Goodbye!")
                break
            elif user_input.lower() == '/clear':
                chat.clear_history()
                print("Conversation history cleared.")
                continue
            elif user_input.lower() == '/history':
                print("\nConversation History:")
                for i, msg in enumerate(chat.conversation_history):
                    role = "System" if msg["role"] == "system" else "User" if msg["role"] == "user" else "Assistant"
                    content = msg["content"]
                    preview = content[:150] + "..." if len(content) > 150 else content
                    print(f"{i+1}. {role}: {preview}")
                print()
                continue
            elif user_input.lower() == '/think':
                thinking_status = chat.toggle_thinking_mode()
                status_text = "ON" if thinking_status else "OFF"
                print(f"\nThinking mode is now: {status_text}")
                continue

            # Skip empty input
            if not user_input:
                continue

            # Stream response
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


def main():
    """Main entry point"""
    # Choose the appropriate version based on available packages
    if PROMPT_TOOLKIT_AVAILABLE:
        interactive_chat_with_prompt_toolkit()
    else:
        interactive_chat_fallback()


if __name__ == "__main__":
    main()