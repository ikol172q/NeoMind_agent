# agent.py - Core agent logic
import os
import json
import time
import asyncio
import aiohttp
import re
from typing import Optional, Dict, List, Any, Tuple
from functools import lru_cache
from lxml import html as lxml_html
import requests
from bs4 import BeautifulSoup


class OptimizedDuckDuckGoSearch:
    """Async + lxml optimized search"""
    
    def __init__(self):
        self.cache = {}
        self.min_interval = 0.5  # Faster but be nice to DDG

    @lru_cache(maxsize=100)
    def should_search(self, query: str) -> bool:
        """Cache decision for whether to search"""
        triggers = {"today", "news", "weather", "latest", "current", "now", "recent"}
        return any(trigger in query.lower() for trigger in triggers)

    async def _fetch_html(self, query: str) -> str:
        """Async fetch with connection pooling"""
        params = {
            'q': query,
            'kl': 'us-en',
            'kp': '1',  # Safe search on
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://html.duckduckgo.com/html/",
                data=params,
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=10
            ) as response:
                return await response.text()

    def _parse_fast(self, html: str) -> List[str]:
        """Lxml parsing - 10x faster than BeautifulSoup"""
        try:
            tree = lxml_html.fromstring(html.encode('utf-8'))

            # XPath for snippets (fastest method)
            snippets = tree.xpath('//a[contains(@class, "snippet")]//text()')

            # Alternative XPath if first one fails
            if not snippets:
                snippets = tree.xpath('//div[contains(@class, "result")]//text()')

            # Clean and filter
            results = []
            seen = set()
            for text in snippets:
                if text and isinstance(text, str):
                    cleaned = re.sub(r'\s+', ' ', text).strip()
                    if (len(cleaned) > 30 and 
                        cleaned not in seen and
                        len(cleaned) < 1000):
                        seen.add(cleaned)
                        results.append(cleaned[:400])

            return results[:5]  # Return top 5

        except Exception:
            return []

    async def search(self, query: str) -> Tuple[bool, str]:
        """Main async search method"""
        start = time.time()

        try:
            # Rate limiting
            current = time.time()
            if hasattr(self, 'last_search'):
                elapsed = current - self.last_search
                if elapsed < self.min_interval:
                    await asyncio.sleep(self.min_interval - elapsed)

            html = await self._fetch_html(query)
            results = self._parse_fast(html)

            self.last_search = time.time()

            if results:
                elapsed = time.time() - start
                formatted = "\n".join([f"{i+1}. {r}" for i, r in enumerate(results)])
                return True, f"✅ [{elapsed:.2f}s] Found {len(results)} results:\n\n{formatted}"
            else:
                return False, "No results found"

        except asyncio.TimeoutError:
            return False, "Search timeout"
        except Exception as e:
            return False, f"Error: {str(e)}"


class DuckDuckGoSearch:
    """Lightweight DuckDuckGo search with caching"""

    def __init__(self):
        self.cache: Dict[str, Dict] = {}
        self.last_search = 0
        self.min_interval = 1.0  # seconds between requests
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def search(self, query: str, max_results: int = 3) -> Tuple[bool, str]:
        """Search DuckDuckGo and return (success, result_string)"""
        # Rate limiting
        current = time.time()
        if current - self.last_search < self.min_interval:
            time.sleep(self.min_interval - (current - self.last_search))

        try:
            # Try HTML search (more robust)
            url = "https://html.duckduckgo.com/html/"
            data = {'q': query, 'kl': 'us-en'}

            response = requests.post(url, data=data, 
                                   headers=self.headers, timeout=8)
            response.raise_for_status()

            # Parse with BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')

            results = []
            # Extract search snippets
            for snippet in soup.find_all('a', class_='result__snippet', 
                                       limit=max_results):
                text = snippet.get_text(strip=True)
                if text and len(text) > 30:
                    results.append(text[:500])

            if results:
                formatted = "\n".join([f"• {r}" for r in results])
                self.last_search = time.time()
                return True, f"🔍 **Search Results for '{query}':**\n\n{formatted}"
            else:
                return False, "No results found."

        except Exception as e:
            return False, f"Search failed: {str(e)}"


class DeepSeekStreamingChat:
    def __init__(self, api_key: Optional[str] = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = model
        self.base_url = "https://api.deepseek.com/chat/completions"
        self.conversation_history = []
        self.thinking_enabled = False  # Add thinking mode flag
        self.searcher = DuckDuckGoSearch()  # ADD THIS LINE
        self.enable_auto_search = False  # ADD THIS LINE - optional auto-search
        self.searcher = OptimizedDuckDuckGoSearch()
        self.search_loop = None

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
         # NEW: Check for search command
        if prompt.startswith("/search"):
            search_query = prompt[7:].strip()  # Remove "/search"
            search_result = self.handle_search(search_query)
            print(f"\n{search_result}\n")
            return None

        # NEW: Optional auto-search (disabled by default)
        # If you want AI to auto-search for certain queries, uncomment:
        # auto_search_triggers = ["today", "weather", "news", "latest", "current"]
        # if any(trigger in prompt.lower() for trigger in auto_search_triggers):
        #     print(f"\n🔍 [Auto-searching for: {prompt[:50]}...]")
        #     success, search_result = self.searcher.search(prompt)
        #     if success:
        #         # Add search results to the prompt
        #         prompt = f"Search Context:\n{search_result}\n\nUser Question: {prompt}"

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
    
    async def stream_response_async(self, prompt: str, **kwargs):
        """Async version - handles search commands asynchronously"""
        if prompt.startswith("/search"):
            query = prompt[7:].strip()
            print(f"\n🔍 Searching for: {query}")
            success, result = await self.searcher.search(query)
            print(f"\n{result}\n")
            return None

        # For non-search prompts, fall back to sync version
        # Or implement async chat if you want
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