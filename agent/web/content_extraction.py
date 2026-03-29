"""Web Content Extraction — strategy-based web page content extraction.

Extracted from core.py (Tier 2C of architecture redesign).
Contains the pure extraction strategies and utility functions used by
/read, /links, /crawl, and /webmap commands.

Created: 2026-03-28 (Tier 2C)
"""

from __future__ import annotations

import html
import re
from typing import Optional
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    requests = None

try:
    import chardet
except ImportError:
    chardet = None

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    BeautifulSoup = None

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    import html2text as _html2text_mod
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False
    _html2text_mod = None


# ── Text Cleaning ────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Clean text by fixing encoding issues, removing HTML entities, normalizing."""
    if not text:
        return ""

    # 1. Unescape HTML entities
    text = html.unescape(text)

    # 2. Fix common encoding issues (mojibake patterns)
    replacements = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã³': 'ó', 'Ãº': 'ú', 'Ã±': 'ñ',
        'Ã': 'Á', 'Ã¤': 'ä', 'Ã«': 'ë', 'Ã¶': 'ö', 'Ã¼': 'ü',
        'â\x80\x99': "'", 'â\x80\x9c': '"', 'â\x80\x9d': '"',
        'â\x80\x94': '—', 'â\x80\x93': '–', 'â\x80\xa2': '•',
        'â\x80\xa6': '…',
        'Â': ' ',
    }
    for wrong, correct in replacements.items():
        text = text.replace(wrong, correct)

    # 3. Remove control characters
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)

    # 4. Normalize line endings and whitespace
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\r', '\n', text)
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    # 5. Clean specific patterns
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    text = re.sub(r'javascript:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'data:[^ ]+;base64,[^ ]+', '', text)

    # 6. Remove non-BMP characters
    text = re.sub(r'[^\u0000-\uFFFF]', '', text)

    return text.strip()


def score_content(content: str) -> int:
    """Score content quality (0-100) with language checking."""
    if not content:
        return 0

    content = clean_text(content)
    score = 0

    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', content))
    english_words = len(re.findall(r'\b[a-zA-Z]{2,}\b', content))

    # Penalize gibberish
    weird_sequences = len(re.findall(r'[Ã©äåçèéêëìíîïðñòóôõöøùúûüýþÿ]', content))
    if weird_sequences > len(content) * 0.1:
        return 0

    if chinese_chars > 10 and english_words > 10:
        score += 30
    elif chinese_chars > 20:
        score += 25
    elif english_words > 20:
        score += 25
    else:
        return 10

    length = len(content)
    if length > 1000:
        score += 40
    elif length > 500:
        score += 20
    elif length > 100:
        score += 10

    sentences = re.findall(r'[.!?。！？]+', content)
    if len(sentences) > 5:
        score += 30

    return min(score, 100)


def format_result(url: str, content: str, score: int) -> str:
    """Format the final result with language info."""
    if len(content) > 20000:
        content = content[:20000] + f"\n\n[Content truncated. Original: {len(content)} chars]"

    content = clean_text(content)

    # Get page title
    title = "Unknown Title"
    if requests and HAS_BS4:
        try:
            response = requests.get(url, timeout=5)
            soup = BeautifulSoup(response.content, 'html.parser')
            if soup.title and soup.title.string:
                title = clean_text(soup.title.string.strip())
        except Exception:
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

    quality = "🟢 High" if score > 70 else "🟡 Medium" if score > 40 else "🔴 Low"

    return f"""📄 PAGE: {title}
🔗 URL: {url}
🌐 Language: {language}
📊 Quality: {quality} ({score}/100)
📏 Length: {len(content)} characters
{"-" * 60}

{content}

{"-" * 60}
✅ End of content from: {url}"""


# ── Extraction Strategies ────────────────────────────────────────────

def try_trafilatura(url: str, max_length: int) -> Optional[str]:
    """Try using trafilatura for article extraction."""
    if not HAS_TRAFILATURA:
        return None
    try:
        downloaded = trafilatura.fetch_url(url)
        text = trafilatura.extract(
            downloaded,
            include_links=True,
            include_images=False,
            include_tables=True,
            no_fallback=False,
            include_formatting=True,
            output_format='txt',
        )
        if text:
            text = clean_text(text)
        return text
    except Exception:
        return None


def try_beautifulsoup(url: str, max_length: int) -> Optional[str]:
    """Try BeautifulSoup extraction with proper encoding handling."""
    if not HAS_BS4 or not requests:
        return None
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Accept-Charset': 'utf-8, iso-8859-1, utf-16, *;q=0.7',
        }

        if 'github.com' in url:
            headers['Accept'] = 'application/vnd.github.v3+json'
        elif 'bilibili.com' in url:
            headers['Referer'] = 'https://www.bilibili.com'
            headers['Accept-Charset'] = 'utf-8, gb2312, gbk, *;q=0.7'

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        # Detect encoding
        encoding = None

        if response.encoding:
            encoding = response.encoding.lower()

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

        if not encoding and chardet:
            detected = chardet.detect(response.content)
            encoding = detected.get('encoding', 'utf-8').lower()

        encoding_map = {
            'gb2312': 'gbk', 'gbk': 'gbk', 'gb18030': 'gb18030',
            'big5': 'big5', 'shift_jis': 'shift_jis', 'euc-jp': 'euc-jp',
            'utf-8': 'utf-8', 'utf8': 'utf-8', 'ascii': 'utf-8',
        }
        encoding = encoding_map.get(encoding or 'utf-8', 'utf-8')

        try:
            content = response.content.decode(encoding, errors='replace')
        except (UnicodeDecodeError, LookupError):
            content = response.content.decode('utf-8', errors='replace')

        soup = BeautifulSoup(content, 'html.parser')

        for tag in ['script', 'style', 'nav', 'footer', 'header',
                     'aside', 'form', 'iframe', 'noscript', 'svg']:
            for element in soup.find_all(tag):
                element.decompose()

        main_selectors = [
            'main', 'article', '[role="main"]', '.main-content',
            '.content', '.post-content', '.article-content',
            '#content', '.markdown-body',
            '.video-info', '.video-desc',
        ]

        main_content = None
        for selector in main_selectors:
            main_content = soup.select_one(selector)
            if main_content:
                break

        if main_content:
            text = main_content.get_text(separator='\n', strip=True)
        else:
            body = soup.find('body')
            text = body.get_text(separator='\n', strip=True) if body else ""

        text = clean_text(text)

        # Extract links
        search_root = main_content or soup.find('body') or soup
        raw_links = search_root.find_all('a', href=True)
        parsed_base = urlparse(url)

        seen_hrefs = set()
        link_lines = []
        link_num = 0

        for a_tag in raw_links:
            href = a_tag['href'].strip()
            link_text = a_tag.get_text(strip=True)[:80]
            if not link_text or not href or href.startswith(('#', 'javascript:')):
                continue
            if href.startswith('/'):
                href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
            elif not href.startswith(('http://', 'https://')):
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            link_num += 1
            link_lines.append(f"[{link_num}] {link_text} → {href}")

        if link_lines:
            text = text.strip() + "\n\n--- Links Found ---\n" + "\n".join(link_lines[:50])

        return text.strip()
    except Exception as e:
        print(f"Debug: BeautifulSoup error for {url}: {str(e)}")
        return None


def try_html2text(url: str, max_length: int, html_converter=None) -> Optional[str]:
    """Try html2text conversion with encoding handling."""
    if not HAS_HTML2TEXT or not requests:
        return None

    if html_converter is None:
        try:
            html_converter = _html2text_mod.HTML2Text()
            html_converter.ignore_links = False
            html_converter.ignore_images = True
        except Exception:
            return None

    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        try:
            if chardet:
                detected = chardet.detect(response.content)
                encoding = detected.get('encoding', 'utf-8').lower()
                content = response.content.decode(encoding, errors='replace')
            else:
                content = response.content.decode('utf-8', errors='replace')
        except Exception:
            content = response.content.decode('utf-8', errors='replace')

        html_converter.unicode_snob = True
        html_converter.escape_snob = False
        html_converter.links_each_paragraph = False
        html_converter.body_width = 0

        text = html_converter.handle(content)
        text = clean_text(text)
        return text.strip()
    except Exception:
        return None


def try_requests_html(url: str, max_length: int, session=None) -> Optional[str]:
    """Try JavaScript rendering for dynamic sites."""
    if not session:
        return None
    try:
        r = session.get(url, timeout=20)
        render_timeout = 30 if 'bilibili.com' in url else 15
        r.html.render(timeout=render_timeout, sleep=2)
        text = r.html.text
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        return text.strip()
    except Exception:
        return None


def try_fallback(url: str, max_length: int) -> Optional[str]:
    """Last resort fallback — strip HTML tags."""
    if not requests:
        return None
    try:
        response = requests.get(url, timeout=10)
        text = re.sub(r'<[^>]+>', ' ', response.text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    except Exception:
        return None


# ── Formatting Helpers ───────────────────────────────────────────────

def format_webmap(base_url: str, urls: list, source: str = 'crawl') -> str:
    """Format discovered URLs as a tree structure."""
    if not urls:
        return "🗺️  No URLs discovered."

    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc
    base_path = parsed_base.path.rstrip('/')

    url_tree = {}
    for url_str in urls:
        parsed = urlparse(url_str)
        if parsed.netloc != base_domain:
            continue
        path = parsed.path.rstrip('/')
        if path.startswith(base_path):
            rel_path = path[len(base_path):].lstrip('/') or '/'
        else:
            rel_path = path.lstrip('/') or '/'
        url_tree[rel_path] = url_str

    sorted_paths = sorted(url_tree.keys(), key=lambda p: (p.count('/'), p))

    lines = [
        f"🗺️  Site map for {base_domain} (source: {source})",
        f"  Found {len(url_tree)} URLs",
        "",
    ]

    for path in sorted_paths:
        depth = path.count('/') if path != '/' else 0
        indent = "  " * (depth + 1)
        display_path = path if len(path) <= 60 else path[:57] + "..."
        lines.append(f"{indent}{display_path}")

    lines.append("")
    lines.append(f"💡 URLs stored in /webmap results. Use /read <url> to view any page.")

    return "\n".join(lines)


def format_links_output(links: dict) -> str:
    """Re-display cached link list."""
    lines = [f"🔗 Cached links ({len(links)} total):", ""]
    for n, href in sorted(links.items()):
        lines.append(f"  [{n}] {href}")
    lines.append("")
    lines.append("💡 Use /read N to follow a link")
    return "\n".join(lines)
