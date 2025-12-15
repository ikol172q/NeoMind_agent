# agent/core.py
import os
import json
import asyncio
from typing import Optional, Dict, List, Any
import requests

from .search import OptimizedDuckDuckGoSearch
from agent_config import agent_config


class DeepSeekStreamingChat:
    """Main DeepSeek agent with streaming and search capabilities"""

    def __init__(self, api_key: Optional[str] = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        # CHANGED: Use agent_config instead of hardcoded values
        self.model = model if model != "deepseek-chat" else agent_config.model
        self.base_url = "https://api.deepseek.com/chat/completions"
        self.conversation_history = []
        self.thinking_enabled = agent_config.thinking_enabled  # CHANGED
        self.searcher = OptimizedDuckDuckGoSearch()
        self.enable_auto_search = False
        self.search_loop = None

        # NEW: Add system prompt if provided
        if agent_config.system_prompt:
            self.add_to_history("system", agent_config.system_prompt)

        if not self.api_key:
            raise ValueError("API key is required. Set DEEPSEEK_API_KEY environment variable or pass it as argument.")

    def handle_search(self, query: str) -> str:
        """Process search command and return results"""
        if not query or query.strip() == "":
            return "Usage: /search <your query>"

        success, result = self.searcher.search(query.strip())
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

    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []

    def toggle_thinking_mode(self):
        """Toggle thinking mode on/off"""
        self.thinking_enabled = not self.thinking_enabled
        return self.thinking_enabled

    def stream_response(self, prompt: str, temperature: float = 0.7, max_tokens: int = 2048 * 4):
        """Stream response with separate thinking and final response streams"""
        if prompt.startswith("/search"):
            search_query = prompt[7:].strip()
            search_result = self.handle_search(search_query)
            print(f"\n{search_result}\n")
            return None

        self.add_to_history("user", prompt)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {
            "model": self.model,
            "messages": self.conversation_history,
            "stream": True,
            "temperature": temperature or agent_config.temperature,  # CHANGED
            "max_tokens": max_tokens or agent_config.max_tokens,    # CHANGED
        }

        if self.thinking_enabled:
            payload["thinking"] = {"type": "enabled"}

        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=30
            )

            if response.status_code != 200:
                print(f"\nError {response.status_code}: {response.text}")
                self.conversation_history.pop()
                return None

            full_response = ""
            reasoning_content = ""
            is_reasoning_active = False
            is_final_response_active = False
            has_seen_reasoning = False

            try:
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
                                    reasoning_chunk = delta.get("reasoning_content")

                                    if reasoning_chunk is not None:
                                        if reasoning_chunk and not is_reasoning_active:
                                            print("\n\033[90m" + "─" * 40 + "🤔 THINKING" + "─" * 40 + "\033[0m")
                                            is_reasoning_active = True
                                            is_final_response_active = False
                                            has_seen_reasoning = True

                                        if reasoning_chunk:
                                            print(f"\033[90m{reasoning_chunk}\033[0m", end="", flush=True)
                                            reasoning_content += reasoning_chunk

                                    content = delta.get("content", "")
                                    if content:
                                        if not is_final_response_active:
                                            if has_seen_reasoning and is_reasoning_active:
                                                print("\n\033[90m" + "-" * 40 + "💬 RESPONSE" + "-" * 40 + "\033[0m\n")
                                            elif not self.thinking_enabled:
                                                print("\nAssistant: ", end="", flush=True)
                                            is_final_response_active = True
                                            is_reasoning_active = False
                                        
                                        print(content, end="", flush=True)
                                        full_response += content
                            except json.JSONDecodeError:
                                continue
            except KeyboardInterrupt:
                print("\n\n[Streaming interrupted by user]")
                response.close()

                save_partial = input("\nSave partial response? (y/n): ").strip().lower()
                if save_partial == 'y' and full_response:
                    self.add_to_history("assistant", full_response + "\n[Response interrupted by user]")
                    return full_response + "\n[Response interrupted by user]"
                else:
                    self.conversation_history.pop()
                    return None

            if full_response:
                self.add_to_history("assistant", full_response)

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

    async def stream_response_async(self, prompt: str, **kwargs):
        """Async version - handles search commands asynchronously"""
        if prompt.startswith("/search"):
            query = prompt[7:].strip()
            print(f"\n Searching for: {query}")
            success, result = await self.searcher.search(query)
            print(f"\n{result}\n")
            return None

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