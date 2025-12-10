# Please install required packages first:
# pip install openai python-dotenv requests prompt_toolkit

import os
from openai import OpenAI
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
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
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

        if not self.api_key:
            raise ValueError("API key is required. Set DEEPSEEK_API_KEY environment variable or pass it as argument.")

    def add_to_history(self, role: str, content: str):
        """Add message to conversation history"""
        self.conversation_history.append({"role": role, "content": content})
    
    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []

    def stream_response(self, prompt: str, temperature: float = 0.7, max_tokens: int = 2048 * 4):
        """Stream response with Ctrl+C interruption support"""
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

            print("\nAssistant: ", end="", flush=True)
            full_response = ""

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
                                    content = delta.get("content", "")
                                    if content:
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
    print("DeepSeek Streaming Chat (Enhanced)")
    print("="*60)
    print("Commands:")
    print("  /clear   - Clear conversation history")
    print("  /history - Show conversation history")
    print("  /quit    - Exit the chat")
    print("="*60)
    print("Tip: Press Ctrl+C during streaming to interrupt current response")
    print("Tip: Use ↑/↓ arrows to navigate through previous queries")
    print("="*60 + "\n")

    # Create prompt session with history
    session = PromptSession(history=InMemoryHistory())
    
    # Create custom key bindings
    kb = KeyBindings()
    
    @kb.add(Keys.ControlC)
    def _(event):
        """Handle Ctrl+C in prompt"""
        event.app.exit(exception=KeyboardInterrupt)
    
    while True:
        try:
            # Get user input with prompt_toolkit
            user_input = session.prompt(
                "You: ",
                key_bindings=kb,
                enable_history_search=True
            ).strip()

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
    print("DeepSeek Streaming Chat")
    print("="*60)
    print("Commands:")
    print("  /clear   - Clear conversation history")
    print("  /history - Show conversation history")
    print("  /quit    - Exit the chat")
    print("="*60)
    print("Tip: Press Ctrl+C during streaming to interrupt current response")
    print("Note: Install prompt_toolkit for arrow key navigation: pip install prompt_toolkit")
    print("="*60 + "\n")

    while True:
        try:
            # Simple input without advanced features
            user_input = input("You: ").strip()

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