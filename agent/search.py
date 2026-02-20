# agent/search.py
import time
import asyncio
import aiohttp
import re
from typing import List, Tuple, Dict
from functools import lru_cache
from lxml import html as lxml_html
import requests
from bs4 import BeautifulSoup


class OptimizedDuckDuckGoSearch:
    """Async + lxml optimized search"""
    
    def __init__(self, triggers=None):
        self.cache = {}
        self.min_interval = 0.5
        self.last_search = 0
        # Default triggers for auto-search detection
        self.triggers = triggers or {"today", "news", "weather", "latest", "current", "now", "recent",
                                     "2026", "2025", "2024", "yesterday", "tomorrow", "update", "breaking",
                                     "stock", "price", "score", "results", "announcement", "release"}
        # Time-sensitive patterns
        self.time_patterns = [
            r"what.*happened.*today",
            r"current.*events",
            r"latest.*news",
            r"recent.*developments",
            r"stock.*price.*of",
            r"score.*of.*game",
            r"weather.*in.*",
            r"forecast.*for.*",
            r"breaking.*news",
        ]

    @lru_cache(maxsize=100)
    def should_search(self, query: str) -> bool:
        """Cache decision for whether to search"""
        query_lower = query.lower()
        # Check trigger keywords
        if any(trigger in query_lower for trigger in self.triggers):
            return True
        # Check time-sensitive patterns
        import re
        if any(re.search(pattern, query_lower) for pattern in self.time_patterns):
            return True
        return False

    async def _fetch_html(self, query: str) -> str:
        """Async fetch with connection pooling"""
        params = {
            'q': query,
            'kl': 'us-en',
            'kp': '1',
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
            snippets = tree.xpath('//a[contains(@class, "snippet")]//text()')

            if not snippets:
                snippets = tree.xpath('//div[contains(@class, "result")]//text()')

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

            return results[:5]
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
                return True, f" [{elapsed:.2f}s] Found {len(results)} results:\n\n{formatted}"
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
        self.min_interval = 1.0
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def search(self, query: str, max_results: int = 3) -> Tuple[bool, str]:
        """Search DuckDuckGo and return (success, result_string)"""
        current = time.time()
        if current - self.last_search < self.min_interval:
            time.sleep(self.min_interval - (current - self.last_search))

        try:
            url = "https://html.duckduckgo.com/html/"
            data = {'q': query, 'kl': 'us-en'}

            response = requests.post(url, data=data, 
                                   headers=self.headers, timeout=8)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            results = []

            for snippet in soup.find_all('a', class_='result__snippet', 
                                       limit=max_results):
                text = snippet.get_text(strip=True)
                if text and len(text) > 30:
                    results.append(text[:500])

            if results:
                formatted = "\n".join([f" {r}" for r in results])
                self.last_search = time.time()
                return True, f" **Search Results for '{query}':**\n\n{formatted}"
            else:
                return False, "No results found."

        except Exception as e:
            return False, f"Search failed: {str(e)}"