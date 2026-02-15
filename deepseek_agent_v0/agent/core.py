# agent/core.py
import os
import json
import asyncio
from typing import Optional, Dict, List, Any
import requests
from bs4 import BeautifulSoup
import re
import html2text
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
from typing import Optional, Dict, List, Any, Set, Tuple
import requests
from urllib.parse import urlparse
import chardet
from .code_analyzer import CodeAnalyzer
import difflib  # Add this line to your imports

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

        # NEW: Code analyzer
        self.code_analyzer = None
        self.code_changes_pending = []  # Store proposed changes

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
        """Procedddddss search command and return results"""
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
        else:
            return f"❌ Unknown subcommand: {subcommand}\n{self._code_help()}"

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
  /code help                 - Show this help

💡 TIPS:
  • Use relative paths from current directory
  • Changes are grouped and require confirmation
  • Large codebases (>500 files) require specific file targeting
        """.strip()

    def _code_scan(self, path: str) -> str:
        """Initialize code analyzer with given path"""
        try:
            abs_path = os.path.abspath(path)
            if not os.path.exists(abs_path):
                return f"❌ Path does not exist: {abs_path}"

            self.code_analyzer = CodeAnalyzer(abs_path)

            # Count files to warn if too many
            total_files, total_dirs = self.code_analyzer.count_files()

            result = f"✅ Codebase scanned: {abs_path}\n"
            result += f"📊 Statistics:\n"
            result += f"  • Total files: {total_files}\n"
            result += f"  • Total directories: {total_dirs}\n"

            if total_files > self.code_analyzer.max_files_before_warning:
                result += f"\n⚠️  LARGE CODEBASE: {total_files} files detected\n"
                result += f"💡 Use '/code find <pattern>' to search for specific files\n"
                result += f"   or '/code read <specific_file>' to analyze individual files\n"

            # Show file type distribution for smaller codebases
            if total_files <= 1000:
                summary = self.code_analyzer.get_code_summary()
                if 'file_types' in summary:
                    result += f"\n📁 File Types:\n"
                    for ext, count in summary['file_types'].items():
                        result += f"  • {ext or 'no ext'}: {count} files\n"

            return result

        except Exception as e:
            return f"❌ Error scanning path: {str(e)}"
    
    def _code_summary(self) -> str:
        """Show codebase summary"""
        if not self.code_analyzer:
            return "❌ No codebase scanned. Use '/code scan <path>' first."
        
        summary = self.code_analyzer.get_code_summary()
        
        result = f"📊 CODEBASE SUMMARY\n"
        result += f"────────────────────────\n"
        result += f"Root: {summary['root_path']}\n"
        result += f"Total files: {summary['total_files']}\n"

        if 'warning' in summary:
            result += f"\n⚠️  {summary['warning']}\n"
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
            return "❌ No codebase scanned. Use '/code scan <path>' first."

        if not pattern:
            return "❌ Please specify a pattern. Examples:\n" \
                   "  /code find *.py\n" \
                   "  /code find *test*\n" \
                   "  /code find agent.py\n"
        
        # Smart search
        results = self.code_analyzer.smart_find_files(pattern, max_results=20)
        
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
            return "❌ No codebase scanned. Use '/code scan <path>' first."
        
        if not file_path:
            return "❌ Please specify a file path"
        
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
            return f"❌ Error reading file: {str(e)}"
    
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
            return "❌ No codebase scanned. Use '/code scan <path>' first."

        if not file_path:
            return "❌ Please specify a file path"
        
        try:
            abs_path = os.path.abspath(file_path)
            analysis = self.code_analyzer.analyze_file(abs_path)

            if not analysis['success']:
                return f"❌ {analysis['error']}"

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
            return f"❌ Error analyzing file: {str(e)}"

    def _code_search(self, search_text: str) -> str:
        """Search for text in code files"""
        if not self.code_analyzer:
            return "❌ No codebase scanned. Use '/code scan <path>' first."
        
        if not search_text:
            return "❌ Please specify search text"

        # Find code files
        code_files = self.code_analyzer.find_code_files(limit=200)  # Limit for performance

        if not code_files:
            return "❌ No code files found in the scanned codebase."

        results = []
        print(f"🔍 Searching in {len(code_files)} files...")
        
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
            return f"🔍 No matches found for '{search_text}' in {len(code_files)} files."
        
        result = f"🔍 SEARCH RESULTS for '{search_text}'\n"
        result += f"📁 Found in {len(results)} files (searched {len(code_files)} files)\n"
        result += "────────────────────────\n"

        for i, res in enumerate(results, 1):
            result += f"\n{i}. {res['relative']}\n"
            result += f"   Matches: {res['occurrences']}\n"
            if res['sample']:
                result += f"   Sample:\n{res['sample']}\n"
        
        return result

    def _code_show_changes(self) -> str:
        """Show pending code changes"""
        if not self.code_changes_pending:
            return "📭 No pending changes. Use the AI to suggest code fixes."
        
        result = f"📋 PENDING CODE CHANGES ({len(self.code_changes_pending)})\n"
        result += "────────────────────────\n"

        # Group changes by file
        changes_by_file = {}
        for change in self.code_changes_pending:
            file_path = change['file_path']
            if file_path not in changes_by_file:
                changes_by_file[file_path] = []
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
        result += "⚠️  WARNING: This will modify files on disk!\n"
        result += "="*60 + "\n\n"

        # Ask for confirmation
        result += "Are you sure you want to apply these changes? (yes/no): "

        # In the CLI, we would handle this interactively
        # For now, return instructions
        result += "\n\n💡 To apply, type 'yes' and then run '/code apply confirm'"
        result += "\n💡 Or use '/code apply force' to apply without interactive confirmation"
        
        return result

    def _code_apply_changes_confirm(self, force: bool = False) -> str:
        """Actually apply the changes (called after confirmation)"""
        if not self.code_changes_pending:
            return " No pending changes to apply."

        applied = []
        failed = []

        # Group changes by file
        changes_by_file = {}
        for change in self.code_changes_pending:
            file_path = change['file_path']
            if file_path not in changes_by_file:
                changes_by_file[file_path] = []
            changes_by_file[file_path].append(change)

        # Apply changes to each file
        for file_path, changes in changes_by_file.items():
            try:
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
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
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
            result += f"\n✅ Successfully applied changes to {len(applied)} files:\n"
            for file_path in applied:
                result += f"   📄 {file_path}\n"

        if failed:
            result += f"\n❌ Failed to apply changes to {len(failed)} files:\n"
            for error in failed:
                result += f"   ⚠️  {error}\n"

        if not applied and not failed:
            result += "\n📭 No changes were applied."
        
        return result

    def _code_clear_changes(self) -> str:
        """Clear all pending changes"""
        count = len(self.code_changes_pending)
        self.code_changes_pending = []
        return f"🧹 Cleared {count} pending changes."

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

    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []

    def toggle_thinking_mode(self):
        """Toggle thinking mode on/off"""
        self.thinking_enabled = not self.thinking_enabled
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

        # Auto-detect if this is a code-related query
        if not prompt.startswith(('/fix', '/analyze', '/code', '/read', '/search', '/models')):
            if self.is_code_related_query(prompt):
                print(f"🔍 Detected code-related query. Adding code context...")
                self.add_code_context_instructions()

        print(f"🔄 Processing command: {prompt[:50]}{'...' if len(prompt) > 50 else ''}")
        
        # Auto-detect file paths before handling commands
        file_content = self.auto_detect_and_read_file(prompt)
        if file_content:
            # Extract just the filename from path
            file_match = re.search(r'([^\\/]+\.\w+)$', prompt)
            if file_match:
                filename = file_match.group(1)
                print(f"🔍 Detected file reference: {filename}")
                print(f"📄 Auto-loaded file content into conversation")

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
        elif prompt.startswith("/read"):
            url = prompt[5:].strip()
            if url:
                content = self.handle_read_command(url)
                print(f"\n{content}\n")
            else:
                print("Usage: /read <url> [options]\nTry: /read --help")
            return None
        elif prompt.startswith("/code"):
            subcommand = prompt[5:].strip()
            response = self.handle_code_command(subcommand)

            # Handle special apply confirmations
            if subcommand.startswith("apply confirm") or subcommand == "apply force":
                force = "force" in subcommand
                response = self._code_apply_changes_confirm(force)

            print(f"\n{response}\n")
            return None
        elif prompt.startswith("/fix") or prompt.startswith("/analyze"):
            # NEW: Handle auto-fix/analyze commands
            print(f"🚀 Starting auto-fix/analyze process...")
            result = self.handle_auto_fix_command(prompt)
            if result is not None:
                print(f"\n{result}\n")
            # Don't return None here - let it continue to the API call
            # Just set a flag to skip adding the user message
            skip_user_add = True
        else:
            skip_user_add = False

        # Regular chat processing (skip if we already added in handle_auto_fix_command)
        if not skip_user_add:
            self.add_to_history("user", prompt)

        print(f"🤖 Preparing to contact DeepSeek API...")
        print(f"📊 Current conversation has {len(self.conversation_history)} messages")

        # Debug: Show last message
        if self.conversation_history:
            last_msg = self.conversation_history[-1]
            print(f"📝 Last message role: {last_msg['role']}")
            print(f"📝 Last message preview: {last_msg['content'][:100]}...")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {
            "model": self.model,
            "messages": self.conversation_history,
            "stream": True,
            "temperature": temperature or agent_config.temperature,
            "max_tokens": max_tokens or agent_config.max_tokens,
        }

        if self.thinking_enabled:
            payload["thinking"] = {"type": "enabled"}
            print(f"💭 Thinking mode: ENABLED")

        try:
            print(f"📡 Sending request to DeepSeek API...")
            print(f"⏱️  Timeout set to: 60 seconds")
            
            # Start timing
            start_time = time.time()

            # Add progress indicator in background
            import threading

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

            # Stop progress indicator
            self._request_complete = True
            elapsed_time = time.time() - start_time

            print(f"\r✅ Request sent in {elapsed_time:.1f}s. Status: {response.status_code}")

            if response.status_code != 200:
                print(f"❌ Error {response.status_code}: {response.text}")
                self.conversation_history.pop()
                return None

            print(f"📥 Starting to receive stream...")
            print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

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
                                print(f"\n✅ Stream complete")
                                break
                            try:
                                json_data = json.loads(data)
                                if "choices" in json_data and json_data["choices"]:
                                    delta = json_data["choices"][0].get("delta", {})
                                    reasoning_chunk = delta.get("reasoning_content")

                                    if reasoning_chunk is not None:
                                        if reasoning_chunk and not is_reasoning_active:
                                            print(f"\n💭 THINKING:")
                                            print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                                            is_reasoning_active = True
                                            is_final_response_active = False
                                            has_seen_reasoning = True

                                        if reasoning_chunk:
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
                print(f"🔧 AUTO-FIX MODE: Processing AI response...")
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
                    try:
                        # Try to read the file
                        if not self.code_analyzer:
                            self.code_analyzer = CodeAnalyzer()

                        success, message, content = self.code_analyzer.read_file_safe(match)
                        if success:
                            print(f"📄 Auto-reading detected file: {match}")
                            return content
                    except:
                        continue

        return None

    def handle_auto_file_analysis(self, file_path: str) -> str:
        """
        Automatically handle file analysis when mentioned
        """
        if not self.code_analyzer:
            self.code_analyzer = CodeAnalyzer()
        
        # Try to read the file
        success, message, content = self.code_analyzer.read_file_safe(file_path)
        
        if not success:
            return f"❌ Could not read file {file_path}: {message}"
        
        # Add to conversation history
        self.add_to_history("user", f"""I want to analyze this file:

File: {file_path}

```python
{content[:5000]}  # Limit to avoid token overflow
```

Please analyze this code and suggest any improvements, fixes, or optimizations.""")

        return f"✅ Successfully loaded {file_path} for analysis. Please continue with your request."
    
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

        print(f"🔧 {'Fixing' if cmd_type == '/fix' else 'Analyzing'}: {file_path}")
        print(f"📝 Description: {description}")

        # Initialize code analyzer if needed
        if not self.code_analyzer:
            self.code_analyzer = CodeAnalyzer()

        # Read the file
        success, message, content = self.code_analyzer.read_file_safe(file_path)
        if not success:
            print(f"❌ Cannot read file: {message}")
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

        print(f"🤖 AI is analyzing the file. It will propose changes automatically...")

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

            print(f"\n🔍 Validating change: {description}")
            
            # Skip if old_code is clearly invalid
            if "# truncated for large files" in old_code.lower() or "# sample code" in old_code.lower():
                print(f"❌ Skipping invalid change (contains truncation comment)")
                continue

            # Try to validate, but be more lenient
            is_valid, error_msg = self.validate_proposed_change(old_code, new_code, file_path)

            if not is_valid:
                print(f"⚠️  Change validation warning: {error_msg}")
                print(f"💡 Still adding to pending changes for manual review")
                # Still add it, but mark as needs review
                description = f"[Needs Review] {description}"
            
            # Add to pending changes
            self.propose_code_change(file_path, old_code, new_code, description, line)
            change_count += 1
            print(f"✅ Added change to pending changes")

        return change_count

    def _auto_apply_changes_with_confirmation(self):
        """
        Automatically apply changes after user confirmation
        """
        if not self.code_changes_pending:
            print("📭 No changes to apply.")
            return

        # Show what will be changed
        print("\n" + "="*60)
        print("📋 PROPOSED CHANGES:")
        print("="*60)
        
        for change in self.code_changes_pending:
            print(f"\n📄 File: {change['file_path']}")
            print(f"📝 {change['description']}")
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