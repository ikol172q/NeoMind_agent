# Please install required packages first:
# pip install openai python-dotenv requests prompt_toolkit

import os
from dotenv import load_dotenv
load_dotenv()

import requests
import json
import os
from typing import Optional

# Try to import prompt_toolkit
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.styles import Style
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False
    print("Note: For better experience, install prompt_toolkit: pip install prompt_toolkit")


class DeepSeekStreamingChat:
    def __init__(self, api_key: Optional[str] = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = model
        self.base_url = "https://api.deepseek.com/chat/completions"
        self.conversation_history = []
        self.thinking_enabled = False  # Add thinking mode flag

        if not self.api_key:
            raise ValueError("API key is required. Set DEEPSEEK_API_KEY environment variable or pass it as argument.")

    def add_to_history(self, role: str, content: str):
        """Add message to conversation history"""
        self.conversation_history.append({"role": role, "content": content})

    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []

    def toggle_thinking_mode(self):
        """Toggle thinking mode on/off"""
        self.thinking_enabled = not self.thinking_enabled
        return self.thinking_enabled

    def stream_response(self, prompt: str, temperature: float = 0.7, max_tokens: int = 2048 * 4):
        """Stream response with separate thinking and final response streams"""
        # Add user message to history
        self.add_to_history("user", prompt)

        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        # Prepare payload with conversation history
        payload = {
            "model": self.model,
            "messages": self.conversation_history,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        # Add thinking parameter if thinking mode is enabled
        if self.thinking_enabled:
            payload["thinking"] = {"type": "enabled"}

        try:
            # Make streaming request
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=30
            )

            if response.status_code != 200:
                print(f"\nError {response.status_code}: {response.text}")
                # Remove failed user message from history
                self.conversation_history.pop()
                return None

            full_response = ""
            reasoning_content = ""
            is_reasoning_active = False
            is_final_response_active = False
            has_seen_reasoning = False

            try:
                # Process streaming chunks
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                json_data = json.loads(data)
                                if "choices" in json_data and json_data["choices"]:
                                    delta = json_data["choices"][0].get("delta", {})

                                    # Check for reasoning content
                                    reasoning_chunk = delta.get("reasoning_content")

                                    # Handle reasoning content (could be string or null)
                                    if reasoning_chunk is not None:
                                        if reasoning_chunk and not is_reasoning_active:
                                            # Start of reasoning - subtle header
                                            print("\n\033[90m" + "─" * 40 + "🤔 THINKING" + "─" * 40 + "\033[0m")
                                            is_reasoning_active = True
                                            is_final_response_active = False
                                            has_seen_reasoning = True
                                        
                                        if reasoning_chunk:  # Only if it's not empty string
                                            # Print reasoning in a subtle gray color
                                            print(f"\033[90m{reasoning_chunk}\033[0m", end="", flush=True)
                                            reasoning_content += reasoning_chunk

                                    # Get regular content
                                    content = delta.get("content", "")
                                    if content:
                                        if not is_final_response_active:
                                            # Start of final response
                                            if has_seen_reasoning and is_reasoning_active:
                                                print("\n\033[90m" + "-" * 40 + "💬 RESPONSE" + "-" * 40 + "\033[0m\n")
                                            elif not self.thinking_enabled:
                                                print("\nAssistant: ", end="", flush=True)
                                            is_final_response_active = True
                                            is_reasoning_active = False
                                        
                                        # Print final response in normal style
                                        print(content, end="", flush=True)
                                        full_response += content
                            except json.JSONDecodeError:
                                continue
            except KeyboardInterrupt:
                # User pressed Ctrl+C to interrupt streaming
                print("\n\n[Streaming interrupted by user]")
                response.close()

                save_partial = input("\nSave partial response? (y/n): ").strip().lower()
                if save_partial == 'y' and full_response:
                    self.add_to_history("assistant", full_response + "\n[Response interrupted by user]")
                    return full_response + "\n[Response interrupted by user]"
                else:
                    self.conversation_history.pop()
                    return None

            # Add assistant response to history
            if full_response:
                self.add_to_history("assistant", full_response)

            # Print closing separator if thinking was shown
            if has_seen_reasoning or is_final_response_active:
                print("\n\033[90m" + "=" * 90 + "\033[0m")

            print()
            return full_response

        except requests.exceptions.Timeout:
            print("\nRequest timed out. Please try again.")
            self.conversation_history.pop()
            return None
        except requests.exceptions.RequestException as e:
            print(f"\nRequest failed: {e}")
            self.conversation_history.pop()
            return None
    
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
    print("  /quit    - Exit the chat")
    print("="*60)
    print("Features:")
    print("   Thinking process streams in yellow color")
    print("   Final response streams in normal color")
    print("   Clear visual separation between thinking and response")
    print("   Use \\ + Enter for line continuation")
    print("   Press Ctrl+C during input to cancel")
    print("   Press Ctrl+C during streaming to interrupt response")
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


if __name__ == "__main__":
    # Choose the appropriate version based on available packages
    if PROMPT_TOOLKIT_AVAILABLE:
        interactive_chat_with_prompt_toolkit()
    else:
        interactive_chat_fallback()