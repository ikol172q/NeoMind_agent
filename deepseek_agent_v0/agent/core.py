# agent/core.py
import os
import json
import asyncio
from typing import Optional, Dict, List, Any
import requests
from bs4 import BeautifulSoup
import re
import html2text

from .search import OptimizedDuckDuckGoSearch
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

from .search import OptimizedDuckDuckGoSearch
from agent_config import agent_config

class DeepSeekStreamingChat:
    """Main DeepSeek agent with streaming, search, and model listing capabilities"""

    def __init__(self, api_key: Optional[str] = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        # CHANGED: Use agent_config instead of hardcoded values
        self.model = model if model != "deepseek-chat" else agent_config.model
        # https://api-docs.deepseek.com/quick_start/pricing
        self.base_url = "https://api.deepseek.com/chat/completions"
        self.models_url = "https://api.deepseek.com/models"  # NEW: For listing models
        self.conversation_history = []
        self.thinking_enabled = agent_config.thinking_enabled  # CHANGED
        self.searcher = OptimizedDuckDuckGoSearch()
        self.enable_auto_search = False
        self.search_loop = None
        self.available_models_cache = None  # NEW: Cache for available models
        self.available_models_cache_timestamp = 0  # NEW: Cache timestamp

        # NEW: Add system prompt if provided
        if agent_config.system_prompt:
            self.add_to_history("system", agent_config.system_prompt)

        if not self.api_key:
            raise ValueError("API key is required. Set DEEPSEEK_API_KEY environment variable or pass it as argument.")
        # Initialize HTML-to-text converter
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = True
        self.html_converter.body_width = 0  # No width limit

        # Initialize optional renderer
        self.session = None
        if HAS_REQUESTS_HTML:
            try:
                self.session = HTMLSession()
            except:
                self.session = None

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
            print("\n🔧 OTHER MODELS:")
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
            print(f"✓ Model switched from '{old_model}' to '{model_id}'")
            return True
        else:
            print(f"✗ Model '{model_id}' not found. Available models:")
            self.print_models()
            return False

    # Updated stream_response to handle /models command
    def handle_search(self, query: str) -> str:
        """Process search command and return results"""
        if not query or query.strip() == "":
            return "Usage: /search <your query>"

        success, result = self.searcher.search(query.strip())
        return result

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
                if len(parts) >= 3:
                    model_id = parts[2]
                    success = self.set_model(model_id)
                    return "Model switched successfully." if success else "Failed to switch model."
                else:
                    print("Usage: /models switch <model_id>")
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
  /models switch <model>   - Switch to a different model
  /models current          - Show current model
  /models help             - Show this help
                """.strip())
                return None
            else:
                print(f"Unknown subcommand: {subcommand}")
                print("Try: /models help")
                return None

        return None

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
        strategies = [
            self._try_trafilatura,
            self._try_beautifulsoup,
            self._try_html2text,
            self._try_requests_html,
            self._try_fallback,
        ]
        
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
            return f"❌ Failed to extract content from {url}. All strategies failed."

    def _try_trafilatura(self, url: str, max_length: int) -> Optional[str]:
        """Try using trafilatura (best for articles)"""
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
            )
            return text
        except:
            return None

    def _try_beautifulsoup(self, url: str, max_length: int) -> Optional[str]:
        """Try BeautifulSoup extraction with smart cleaning"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }

            # Special headers for specific sites
            if 'github.com' in url:
                headers['Accept'] = 'application/vnd.github.v3+json'
            elif 'bilibili.com' in url:
                headers['Referer'] = 'https://www.bilibili.com'

            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

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

            # Clean text
            text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
            text = re.sub(r'[ \t]{2,}', ' ', text)

            return text.strip()
        except:
            return None

    def _try_html2text(self, url: str, max_length: int) -> Optional[str]:
        """Try html2text conversion"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            # Convert HTML to markdown-like text
            text = self.html_converter.handle(response.text)
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
        """Score content quality (0-100)"""
        if not content:
            return 0

        score = 0

        # Length score (more content is better)
        length = len(content)
        if length > 1000:
            score += 40
        elif length > 500:
            score += 20
        elif length > 100:
            score += 10

        # Sentence structure score
        sentences = re.findall(r'[.!?]+', content)
        if len(sentences) > 5:
            score += 30

        # Paragraph structure score
        paragraphs = content.count('\n\n')
        if paragraphs > 3:
            score += 20

        # Word diversity score
        words = content.split()
        unique_words = len(set(words))
        if len(words) > 0 and unique_words / len(words) > 0.5:
            score += 10

        return min(score, 100)

    def _format_result(self, url: str, content: str, score: int) -> str:
        """Format the final result"""
        if len(content) > 20000:
            content = content[:20000] + f"\n\n[Content truncated. Original: {len(content)} chars]"

        # Get page title if possible
        title = "Unknown Title"
        try:
            response = requests.get(url, timeout=5)
            soup = BeautifulSoup(response.content, 'html.parser')
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
        except:
            pass

        # Quality indicator
        quality = "🟢 High" if score > 70 else "🟡 Medium" if score > 40 else "🔴 Low"
        
        result = f"""📄 PAGE: {title}
🔗 URL: {url}
📊 Quality: {quality} ({score}/100)
📏 Length: {len(content)} characters
{"─" * 60}

{content}

{"─" * 60}
✅ End of content from: {url}"""

        return result

    def handle_read_command(self, url_or_command: str) -> str:
        """
        Handle /read command for webpage reading with enhanced capabilities
        """
        if not url_or_command or url_or_command.strip() == "":
            help_text = """
📚 /read Command Usage:
  /read <url>                     - Read webpage content
  /read --debug <url>            - Show debugging info
  /read --strategy <n> <url>     - Use specific strategy (0-4)
  
Strategies:
  0: trafilatura (best for articles)
  1: beautifulsoup (smart extraction)
  2: html2text (markdown conversion)
  3: requests-html (JavaScript sites)
  4: fallback (basic extraction)
            """.strip()
            return help_text

        parts = url_or_command.split()

        # Handle flags
        debug = False
        strategy = None
        url = url_or_command

        if '--debug' in parts:
            debug = True
            parts.remove('--debug')
            url = ' '.join(parts[1:]) if len(parts) > 1 else ''
        elif '--strategy' in parts:
            try:
                idx = parts.index('--strategy')
                if idx + 1 < len(parts):
                    strategy = int(parts[idx + 1])
                    # Remove both --strategy and the number
                    parts.pop(idx)
                    parts.pop(idx)
                    url = ' '.join(parts)
            except:
                pass
        else:
            url = ' '.join(parts)

        if not url:
            return "❌ Please provide a URL"
        
        print(f"🌐 Processing: {url}")
        
        if debug:
            # Run all strategies and show results
            results = []
            strategies = [
                ("trafilatura", self._try_trafilatura),
                ("beautifulsoup", self._try_beautifulsoup),
                ("html2text", self._try_html2text),
                ("requests-html", self._try_requests_html),
                ("fallback", self._try_fallback),
            ]

            for name, strategy_func in strategies:
                try:
                    content = strategy_func(url, 5000)
                    if content:
                        score = self._score_content(content)
                        results.append(f"{name}: {score}/100, {len(content)} chars")
                        if len(results) == 1:  # First successful
                            final_content = content
                            final_score = score
                except Exception as e:
                    results.append(f"{name}: ERROR - {str(e)}")

            debug_info = "\n".join(results)
            final_result = self._format_result(url, final_content, final_score)
            return f"🔍 Debug Results:\n{debug_info}\n\n{final_result}"
        
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
                    return self._format_result(url, content, score)
                else:
                    return f"❌ Strategy {strategy} failed to extract content"
            else:
                return f"❌ Invalid strategy number. Use 0-{len(strategies)-1}"

        else:
            # Normal reading with best strategy
            return self.read_webpage(url)

    def handle_read_command(self, url_or_command: str) -> str:
        """
        Handle /read command for webpage reading
        """
        if not url_or_command or url_or_command.strip() == "":
            return "Usage: /read <url>\nExample: /read https://example.com"

        url = url_or_command.strip()
        print(f"\n🌐 Reading webpage: {url}")
        return self.read_webpage(url)
    
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
        # Handle commands first
        if prompt.startswith("/search"):
            search_query = prompt[7:].strip()
            search_result = self.handle_search(search_query)
            print(f"\n{search_result}\n")
            return None
        elif prompt.startswith("/models"):
            response = self.handle_models_command(prompt)
            if response:
                print(f"\n{response}\n")
            return None
        elif prompt.startswith("/read"):  # NEW: Handle /read command
            url = prompt[5:].strip()
            if url:
                content = self.handle_read_command(url)
                print(f"\n{content}\n")
            else:
                print("Usage: /read <url>\nExample: /read https://example.com")
            return None

        # Regular chat processing
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
                                            print("\n\033[90m" + "" * 40 + " THINKING" + "" * 40 + "\033[0m")
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
                                                print("\n\033[90m" + "-" * 40 + " RESPONSE" + "-" * 40 + "\033[0m\n")
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
        """Async version - handles search and model commands asynchronously"""
        if prompt.startswith("/search"):
            query = prompt[7:].strip()
            print(f"\n🔍 Searching for: {query}")
            success, result = await self.searcher.search(query)
            print(f"\n{result}\n")
            return None
        elif prompt.startswith("/models"):
            # Run model commands in thread pool
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.handle_models_command(prompt))
            return None
        elif prompt.startswith("/read"):  # NEW: Handle /read command asynchronously
            url = prompt[5:].strip()
            if url:
                # Run webpage reading in thread pool (IO-bound)
                loop = asyncio.get_event_loop()
                content = await loop.run_in_executor(None, self.handle_read_command, url)
                print(f"\n{content}\n")
            else:
                print("Usage: /read <url>\nExample: /read https://example.com")
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