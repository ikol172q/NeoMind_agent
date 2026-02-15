# agent/core.py
import os
import json
import asyncio
from typing import Optional, Dict, List, Any
import requests
from bs4 import BeautifulSoup
import re
import html2text

# Add to imports
import html
from urllib.parse import urlparse
import chardet  # For auto-detecting encoding

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
{"─" * 60}

{content}

{"─" * 60}
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
            'Â': '',  # Remove extra spaces from UTF-8 BOM issues
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
    /read --debug <url>            - Show debugging info (doesn't add to AI memory)
    /read --strategy <n> <url>     - Use specific strategy (0-4)
    /read --no-ai <url>            - Read without adding to AI memory

    Strategies:
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
                        return f"❌ Invalid strategy number. Must be 0-4."
                else:
                    return "❌ Missing strategy number. Use: /read --strategy <0-4> <url>"
            elif parts[i] == '--no-ai':
                no_ai = True
                parts.pop(i)
            else:
                i += 1

        # The remaining parts should form the URL
        if not parts:
            return "❌ Please provide a URL"
        
        url = ' '.join(parts)

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
                return f"❌ All strategies failed for {url}"
        
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
                    return f"❌ Strategy {strategy} failed to extract content"
            else:
                return f"❌ Invalid strategy number. Use 0-{len(strategies)-1}"

        else:
            # Normal reading with best strategy (default behavior)
            content = self.read_webpage(url)

            # Add to conversation history unless --no-ai flag is set
            if not no_ai:
                self._add_webpage_to_memory(url, content)
            
            return content

    def _add_webpage_to_memory(self, url: str, content: str) -> None:
        """
        Add webpage content to conversation history for AI awareness
        """
        # Extract just the main text content (remove formatting headers)
        # Find where the actual content starts (after the "─" * 60 line)
        lines = content.split('\n')
        content_start = 0

        for i, line in enumerate(lines):
            if '─' * 60 in line or '=' * 60 in line:
                content_start = i + 1
                break

        main_content = '\n'.join(lines[content_start:])
        
        # Remove trailing separator if present
        if '─' * 60 in main_content or '=' * 60 in main_content:
            main_content = main_content[:main_content.rfind('─' * 60)]

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
                content = self.handle_read_command(url)  # Calls the single merged method
                print(f"\n{content}\n")
            else:
                print("Usage: /read <url> [options]\nTry: /read --help")
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