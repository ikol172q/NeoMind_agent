"""Web command handlers — links, crawl, webmap, logs.

Extracted from core.py (Tier 2G). Each function takes the core agent reference
and command string, returning formatted output.

Created: 2026-03-28 (Tier 2G)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

if TYPE_CHECKING:
    pass

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    BeautifulSoup = None


def handle_links_command(core, url_or_command: str) -> str:
    """Handle /links command — extract and list all links from a webpage."""
    if not url_or_command or url_or_command.strip() == "":
        # Re-show cached links if available
        if core._last_links:
            from agent.web.content_extraction import format_links_output
            return format_links_output(core._last_links)
        return (
            "🔗 /links <url>  — Extract all links from a webpage\n"
            "After running /links, use /read N to follow link #N."
        )

    url = url_or_command.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    print(f"🔗 Extracting links from: {url}")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Remove nav/footer noise
        for tag in ['nav', 'footer', 'aside']:
            for el in soup.find_all(tag):
                el.decompose()

        parsed_base = urlparse(url)
        base_domain = parsed_base.netloc

        internal_links = {}  # num → (text, href)
        external_links = {}
        seen = set()
        num = 0

        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            text = a_tag.get_text(strip=True)[:80]
            if not text or not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue

            # Resolve relative
            if href.startswith('/'):
                href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
            elif not href.startswith(('http://', 'https://')):
                continue

            if href in seen:
                continue
            seen.add(href)
            num += 1

            parsed_href = urlparse(href)
            if parsed_href.netloc == base_domain or parsed_href.netloc.endswith('.' + base_domain):
                internal_links[num] = (text, href)
            else:
                external_links[num] = (text, href)

        # Store for /read N follow-up
        core._last_links = {}
        all_links = {**internal_links, **external_links}
        for n, (text, href) in all_links.items():
            core._last_links[n] = href

        # Format output
        lines = [f"🔗 Links from: {url}", f"   Total: {len(all_links)}", ""]

        if internal_links:
            lines.append(f"── Internal ({len(internal_links)}) ──")
            for n, (text, href) in internal_links.items():
                path = urlparse(href).path or '/'
                lines.append(f"  [{n}] {text} → {path}")
            lines.append("")

        if external_links:
            lines.append(f"── External ({len(external_links)}) ──")
            for n, (text, href) in external_links.items():
                lines.append(f"  [{n}] {text} → {href}")
            lines.append("")

        lines.append("💡 Use /read N to follow a link (e.g., /read 3)")

        return "\n".join(lines)

    except Exception as e:
        return core.formatter.error(f"Failed to extract links from {url}: {e}")


def handle_crawl_command(core, command: str) -> str:
    """Handle /crawl command — crawl a website following same-domain links."""
    if not command or command.strip() == "":
        return (
            "🕷️ /crawl <url> [--depth N] [--max N]\n"
            "  Crawl a website from the given URL.\n"
            "  --depth N  Max link depth (default: 1)\n"
            "  --max N    Max pages to crawl (default: 10, hard cap: 50)\n\n"
            "Example: /crawl https://docs.example.com --depth 2 --max 15"
        )

    parts = command.strip().split()
    url = None
    max_depth = 1
    max_pages = 10

    # Parse args
    i = 0
    while i < len(parts):
        if parts[i] == '--depth' and i + 1 < len(parts):
            try:
                max_depth = int(parts[i + 1])
                i += 2
                continue
            except ValueError:
                return core.formatter.error("--depth requires an integer")
        elif parts[i] == '--max' and i + 1 < len(parts):
            try:
                max_pages = min(int(parts[i + 1]), 50)  # Hard cap at 50
                i += 2
                continue
            except ValueError:
                return core.formatter.error("--max requires an integer")
        elif url is None:
            url = parts[i]
        i += 1

    if not url:
        return core.formatter.error("Please provide a URL to crawl.")

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    print(f"🕷️ Starting crawl: {url} (depth={max_depth}, max={max_pages})")

    try:
        from agent.web.extractor import WebExtractor
        from agent.web.crawler import BFSCrawler
        from agent.web.cache import URLCache

        # Create extractor with browser fallback
        cache = URLCache(ttl_seconds=1800)
        extractor = WebExtractor(
            browser_sync_fn=core._browser_sync,
            cache=cache,
        )
        crawler = BFSCrawler(extractor, cache=cache, delay=1.0)

        report = crawler.crawl(
            url,
            max_depth=max_depth,
            max_pages=max_pages,
        )

        # Store crawl results for follow-up /read
        core._crawl_results = {
            page.url: page.content for page in report.ok_pages
        }

        # Add summary to AI memory (not full content — too large)
        if report.ok_pages:
            summary_content = report.all_content(max_chars_per_page=2000)
            # Cap total at 12000 chars for memory
            if len(summary_content) > 12000:
                summary_content = summary_content[:12000] + "\n\n[Crawl content truncated]"

            core.add_to_history("user", f"""I've crawled the following website:

Start URL: {url}
Pages crawled: {len(report.ok_pages)}
Total words: {report.total_words:,}

{summary_content}

Please remember this content. I may ask questions about it.""")

            print("💡 Crawl content added to AI memory.")

        return report.summary()

    except ImportError as e:
        return core.formatter.error(
            f"Crawl module not available: {e}\n"
            "Make sure agent/web/ package exists."
        )
    except Exception as e:
        return core.formatter.error(f"Crawl failed: {e}")


def handle_webmap_command(core, command: str) -> str:
    """Handle /webmap command — generate sitemap or discover site structure."""
    if not command or command.strip() == "":
        return (
            "🗺️  /webmap <url> [--depth N]\n"
            "  Generate a site map from sitemap.xml or by crawling.\n"
            "  --depth N  Max crawl depth if no sitemap found (default: 1)\n\n"
            "Example: /webmap https://docs.example.com"
        )

    parts = command.strip().split()
    url = None
    max_depth = 1

    # Parse args
    i = 0
    while i < len(parts):
        if parts[i] == '--depth' and i + 1 < len(parts):
            try:
                max_depth = int(parts[i + 1])
                i += 2
                continue
            except ValueError:
                return core.formatter.error("--depth requires an integer")
        elif url is None:
            url = parts[i]
        i += 1

    if not url:
        return core.formatter.error("Please provide a URL.")

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    print(f"🗺️  Generating webmap for: {url}")

    try:
        from urllib.parse import urljoin
        import xml.etree.ElementTree as ET
        import requests as _requests

        # ── Step 1: Try to fetch sitemap.xml ──────────────────────
        sitemap_url = urljoin(url, '/sitemap.xml')
        print(f"  Checking for sitemap at: {sitemap_url}")

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            response = _requests.get(sitemap_url, headers=headers, timeout=10)
            response.raise_for_status()

            # Parse sitemap
            root = ET.fromstring(response.content)
            sitemap_urls = []

            # Handle standard sitemap namespace
            namespace = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            for url_elem in root.findall('.//sm:loc', namespace):
                if url_elem.text:
                    sitemap_urls.append(url_elem.text)

            if not sitemap_urls:
                # Try without namespace
                for url_elem in root.findall('.//loc'):
                    if url_elem.text:
                        sitemap_urls.append(url_elem.text)

            if sitemap_urls:
                print(f"  Found sitemap.xml with {len(sitemap_urls)} URLs")
                core._last_webmap = sitemap_urls
                from agent.web.content_extraction import format_webmap
                return format_webmap(url, sitemap_urls, source='sitemap.xml')

        except Exception as e:
            print(f"  Sitemap not found: {e}")

        # ── Step 2: Fall back to BFS crawl ────────────────────────
        print(f"  Falling back to crawl-based discovery (depth={max_depth})")

        from agent.web.extractor import WebExtractor
        from agent.web.crawler import BFSCrawler
        from agent.web.cache import URLCache

        cache = URLCache(ttl_seconds=1800)
        extractor = WebExtractor(
            browser_sync_fn=core._browser_sync,
            cache=cache,
        )
        crawler = BFSCrawler(extractor, cache=cache, delay=0.5)

        report = crawler.crawl(
            url,
            max_depth=max_depth,
            max_pages=20,  # Keep it reasonable for webmap
        )

        # Extract URLs from crawled pages
        crawled_urls = [page.url for page in report.ok_pages]
        core._last_webmap = crawled_urls

        from agent.web.content_extraction import format_webmap
        return format_webmap(url, crawled_urls, source='crawl')

    except ImportError as e:
        return core.formatter.error(
            f"Webmap module not available: {e}\n"
            "Make sure requests and xml modules are available."
        )
    except Exception as e:
        return core.formatter.error(f"Webmap generation failed: {e}")


def handle_logs_command(core, command: str) -> Optional[str]:
    """Handle /logs command — search and view activity logs."""
    if not core._unified_logger:
        return core.formatter.warning("Unified logger not initialized")

    parts = command.strip().split(maxsplit=1) if command.strip() else []
    subcommand = parts[0] if parts else ""
    args = parts[1] if len(parts) > 1 else ""

    try:
        from agent.services.log_commands import (
            format_log_stats, format_log_weekly_stats,
            format_log_search_results, format_log_recent,
        )

        if not subcommand or subcommand == "":
            # Default: show today's stats
            stats = core._unified_logger.get_daily_stats()
            return format_log_stats(stats, "today")

        elif subcommand == "search":
            if not args:
                return core.formatter.warning("/logs search requires a keyword")
            results = core._unified_logger.search(args, limit=10)
            return format_log_search_results(results, args)

        elif subcommand == "stats":
            # Weekly stats
            stats = core._unified_logger.get_weekly_stats()
            return format_log_weekly_stats(stats)

        elif subcommand == "recent":
            # Most recent entries
            limit = 10
            if args:
                try:
                    limit = int(args)
                except ValueError:
                    return core.formatter.error(f"Invalid limit: {args}")
            results = core._unified_logger.query(limit=limit)
            return format_log_recent(results, limit)

        elif subcommand == "cleanup":
            # Clean up old logs
            keep_days = 90
            if args:
                try:
                    keep_days = int(args)
                except ValueError:
                    return core.formatter.error(f"Invalid days: {args}")
            deleted = core._unified_logger.cleanup_old_logs(keep_days)
            return core.formatter.success(
                f"Cleaned up logs: deleted {deleted} files (kept logs from last {keep_days} days)"
            )

        else:
            return core.formatter.error(
                f"Unknown /logs subcommand: {subcommand}\n"
                "Usage: /logs [search <kw>|stats|recent [N]|cleanup [days]]"
            )

    except Exception as e:
        return core.formatter.error(f"Logs command failed: {e}")
