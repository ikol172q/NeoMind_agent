# agent/browser/daemon.py
"""
Browser Daemon — persistent headless Chromium with command interface.

Architecture (from gstack pattern):
    BrowserDaemon
        │
        ├── Playwright Chromium (headless, persistent context)
        │   ├── Cookies + localStorage persist across calls
        │   ├── Multiple tabs supported
        │   └── Console/network logs buffered
        │
        └── Command dispatch (goto, click, fill, snapshot, screenshot, etc.)

Usage:
    daemon = BrowserDaemon()
    await daemon.start()
    result = await daemon.execute("goto", ["https://example.com"])
    result = await daemon.execute("snapshot", ["-i"])
    result = await daemon.execute("click", ["@e3"])
    result = await daemon.execute("screenshot", ["/tmp/page.png"])
    await daemon.stop()

Or via the singleton:
    browser = await get_browser()
    result = await browser.execute("text", [])
"""

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

logger = logging.getLogger("neomind.browser")

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    # Stub types so class definitions don't break at import time
    Browser = Any
    BrowserContext = Any
    Page = Any


# ── Snapshot System ──────────────────────────────────────────────

class SnapshotRef:
    """Maps @e1, @e2, ... refs to Playwright locators."""

    def __init__(self):
        self._refs: Dict[str, Any] = {}  # "@e1" → Locator
        self._counter = 0

    def clear(self):
        self._refs.clear()
        self._counter = 0

    def add(self, locator) -> str:
        self._counter += 1
        ref = f"@e{self._counter}"
        self._refs[ref] = locator
        return ref

    def get(self, ref: str):
        return self._refs.get(ref)

    @property
    def count(self) -> int:
        return len(self._refs)


# ── Browser Daemon ───────────────────────────────────────────────

class BrowserDaemon:
    """Persistent headless Chromium with command dispatch.

    Lifecycle:
    - start() → launches Chromium, creates persistent context
    - execute(cmd, args) → dispatches commands
    - stop() → closes browser

    State persists between execute() calls:
    - Cookies, localStorage, sessions
    - Open tabs
    - Console/network log buffers
    """

    DATA_DIR = Path(os.getenv("HOME", "/data")) / ".neomind" / "browser"
    IDLE_TIMEOUT = 1800  # 30 min auto-shutdown

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._tabs: Dict[str, Page] = {}  # tab_id → Page
        self._active_tab: str = ""
        self._refs = SnapshotRef()
        self._console_logs: List[str] = []
        self._network_logs: List[Dict] = []
        self._running = False
        self._last_activity = 0

    @property
    def is_running(self) -> bool:
        return self._running and self._browser is not None

    async def start(self):
        """Launch Chromium with persistent context."""
        if not HAS_PLAYWRIGHT:
            raise ImportError(
                "playwright not installed. Run: pip install playwright && playwright install chromium"
            )

        if self._running:
            return

        logger.info("Starting browser daemon...")
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()

        # Persistent context = cookies/localStorage survive between sessions
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.DATA_DIR / "chromium-profile"),
            headless=True,
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-gpu",
            ],
        )

        # Get or create first page
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        tab_id = "tab-1"
        self._tabs[tab_id] = self._page
        self._active_tab = tab_id

        # Wire event listeners
        self._page.on("console", lambda msg: self._console_logs.append(
            f"[{msg.type}] {msg.text}"
        ))
        self._page.on("response", lambda resp: self._network_logs.append({
            "url": resp.url, "status": resp.status, "method": resp.request.method,
        }))

        self._running = True
        self._last_activity = asyncio.get_event_loop().time()
        logger.info("Browser daemon started")

    async def stop(self):
        """Shut down Chromium."""
        self._running = False
        if self._context:
            await self._context.close()
            self._context = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._browser = None
        self._page = None
        self._tabs.clear()
        self._refs.clear()
        logger.info("Browser daemon stopped")

    # ── Command Dispatch ─────────────────────────────────────────

    async def execute(self, command: str, args: List[str] = None) -> str:
        """Execute a browser command. Returns result as string."""
        if not self._running:
            await self.start()

        args = args or []
        self._last_activity = asyncio.get_event_loop().time()

        # Trim console/network buffers
        self._console_logs = self._console_logs[-500:]
        self._network_logs = self._network_logs[-500:]

        cmd = command.lower().strip()
        page = self._page

        try:
            # ── Navigation ───────────────────────────────────
            if cmd == "goto":
                url = args[0] if args else ""
                if not url.startswith("http"):
                    url = "https://" + url
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self._refs.clear()
                title = await page.title()
                return f"Navigated to: {url}\nTitle: {title}"

            elif cmd == "back":
                await page.go_back()
                return "Navigated back"

            elif cmd == "forward":
                await page.go_forward()
                return "Navigated forward"

            elif cmd == "reload":
                await page.reload()
                return "Page reloaded"

            # ── Reading ──────────────────────────────────────
            elif cmd == "text":
                text = await page.inner_text("body")
                return text[:10000]  # cap at 10K chars

            elif cmd == "html":
                selector = args[0] if args else "body"
                html = await page.inner_html(selector)
                return html[:10000]

            elif cmd == "title":
                return await page.title()

            elif cmd == "url":
                return page.url

            elif cmd == "links":
                links = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => ({text: e.textContent.trim().slice(0,80), href: e.href})).filter(l => l.text)"
                )
                lines = [f"[{l['text']}]({l['href']})" for l in links[:50]]
                return "\n".join(lines) or "No links found"

            elif cmd == "forms":
                forms = await page.eval_on_selector_all(
                    "input, select, textarea, button",
                    """els => els.map(e => ({
                        tag: e.tagName, type: e.type || '', name: e.name || '',
                        placeholder: e.placeholder || '', value: e.value || ''
                    }))"""
                )
                lines = [f"{f['tag']} type={f['type']} name={f['name']} placeholder={f['placeholder']}" for f in forms[:30]]
                return "\n".join(lines) or "No form elements found"

            # ── Snapshot (ARIA tree → @ref) ──────────────────
            elif cmd == "snapshot":
                interactive_only = "-i" in args
                return await self._take_snapshot(page, interactive_only)

            # ── Screenshot ───────────────────────────────────
            elif cmd == "screenshot":
                path = args[0] if args else "/tmp/neomind-screenshot.png"
                await page.screenshot(path=path, full_page=False)
                return f"Screenshot saved: {path}"

            elif cmd == "pdf":
                path = args[0] if args else "/tmp/neomind-page.pdf"
                await page.pdf(path=path)
                return f"PDF saved: {path}"

            # ── Interaction ──────────────────────────────────
            elif cmd == "click":
                ref = args[0] if args else ""
                locator = self._resolve_ref(ref)
                if locator:
                    await locator.click(timeout=5000)
                    return f"Clicked {ref}"
                else:
                    # Try as CSS selector
                    await page.click(ref, timeout=5000)
                    return f"Clicked {ref}"

            elif cmd == "fill":
                ref = args[0] if len(args) >= 2 else ""
                value = args[1] if len(args) >= 2 else ""
                locator = self._resolve_ref(ref)
                if locator:
                    await locator.fill(value, timeout=5000)
                    return f"Filled {ref} with '{value}'"
                else:
                    await page.fill(ref, value, timeout=5000)
                    return f"Filled {ref} with '{value}'"

            elif cmd == "select":
                ref = args[0] if len(args) >= 2 else ""
                value = args[1] if len(args) >= 2 else ""
                locator = self._resolve_ref(ref)
                if locator:
                    await locator.select_option(value, timeout=5000)
                else:
                    await page.select_option(ref, value, timeout=5000)
                return f"Selected '{value}' in {ref}"

            elif cmd == "type":
                text = " ".join(args)
                await page.keyboard.type(text)
                return f"Typed: {text}"

            elif cmd == "press":
                key = args[0] if args else "Enter"
                await page.keyboard.press(key)
                return f"Pressed: {key}"

            elif cmd == "scroll":
                direction = args[0] if args else "down"
                amount = int(args[1]) if len(args) > 1 else 300
                if direction == "down":
                    await page.mouse.wheel(0, amount)
                elif direction == "up":
                    await page.mouse.wheel(0, -amount)
                return f"Scrolled {direction} {amount}px"

            elif cmd == "hover":
                ref = args[0] if args else ""
                locator = self._resolve_ref(ref)
                if locator:
                    await locator.hover(timeout=5000)
                else:
                    await page.hover(ref, timeout=5000)
                return f"Hovered {ref}"

            elif cmd == "wait":
                seconds = float(args[0]) if args else 1.0
                await asyncio.sleep(min(seconds, 10))
                return f"Waited {seconds}s"

            # ── Inspection ───────────────────────────────────
            elif cmd == "console":
                logs = self._console_logs[-20:]
                return "\n".join(logs) or "No console logs"

            elif cmd == "network":
                pattern = args[0] if args else ""
                logs = self._network_logs[-30:]
                if pattern:
                    logs = [l for l in logs if pattern in l.get("url", "")]
                lines = [f"{l['method']} {l['status']} {l['url'][:100]}" for l in logs]
                return "\n".join(lines) or "No network requests"

            elif cmd == "cookies":
                cookies = await self._context.cookies()
                lines = [f"{c['name']}={c['value'][:30]}... ({c['domain']})" for c in cookies[:20]]
                return "\n".join(lines) or "No cookies"

            elif cmd == "js":
                expression = " ".join(args)
                result = await page.evaluate(expression)
                return json.dumps(result, ensure_ascii=False, default=str)[:5000]

            # ── Tab Management ───────────────────────────────
            elif cmd == "newtab":
                url = args[0] if args else "about:blank"
                new_page = await self._context.new_page()
                tab_id = f"tab-{len(self._tabs) + 1}"
                self._tabs[tab_id] = new_page
                self._active_tab = tab_id
                self._page = new_page
                if url != "about:blank":
                    await new_page.goto(url, wait_until="domcontentloaded")
                return f"Opened {tab_id}: {url}"

            elif cmd == "tabs":
                lines = []
                for tid, p in self._tabs.items():
                    active = " ← active" if tid == self._active_tab else ""
                    try:
                        title = await p.title()
                    except Exception:
                        title = "(closed)"
                    lines.append(f"{tid}: {title}{active}")
                return "\n".join(lines) or "No tabs"

            elif cmd == "tab":
                tab_id = args[0] if args else ""
                if tab_id in self._tabs:
                    self._page = self._tabs[tab_id]
                    self._active_tab = tab_id
                    self._refs.clear()
                    return f"Switched to {tab_id}"
                return f"Tab not found: {tab_id}"

            elif cmd == "closetab":
                tab_id = args[0] if args else self._active_tab
                if tab_id in self._tabs and len(self._tabs) > 1:
                    await self._tabs[tab_id].close()
                    del self._tabs[tab_id]
                    self._active_tab = list(self._tabs.keys())[-1]
                    self._page = self._tabs[self._active_tab]
                    return f"Closed {tab_id}, active: {self._active_tab}"
                return "Cannot close last tab"

            # ── Meta ─────────────────────────────────────────
            elif cmd == "status":
                tabs = len(self._tabs)
                url = self._page.url if self._page else "none"
                return (
                    f"Running: {self._running}\n"
                    f"Tabs: {tabs}\n"
                    f"Active: {self._active_tab}\n"
                    f"URL: {url}\n"
                    f"Refs: {self._refs.count}\n"
                    f"Console logs: {len(self._console_logs)}\n"
                    f"Network logs: {len(self._network_logs)}"
                )

            else:
                return f"Unknown command: {cmd}. Use: goto, text, snapshot, screenshot, click, fill, etc."

        except Exception as e:
            return f"Error: {e}"

    # ── Snapshot Implementation ───────────────────────────────────

    async def _take_snapshot(self, page: Page, interactive_only: bool = False) -> str:
        """Generate ARIA-like snapshot with @ref IDs.

        Scans the page for elements, assigns @e1, @e2, ... refs.
        These refs can be used with click, fill, etc.
        """
        self._refs.clear()

        if interactive_only:
            # Only interactive elements
            selector = "a, button, input, select, textarea, [role='button'], [role='link'], [onclick], [tabindex]"
        else:
            # All visible elements with text
            selector = "a, button, input, select, textarea, h1, h2, h3, h4, p, span, div, li, td, th, label, img[alt]"

        try:
            elements = await page.query_selector_all(selector)
        except Exception:
            return "Error: could not query page elements"

        lines = []
        for el in elements[:200]:  # cap at 200 elements
            try:
                visible = await el.is_visible()
                if not visible:
                    continue

                tag = await el.evaluate("e => e.tagName.toLowerCase()")
                text = (await el.inner_text())[:80] if tag not in ("input", "img") else ""
                attrs = await el.evaluate("""e => ({
                    type: e.type || '',
                    name: e.name || '',
                    placeholder: e.placeholder || '',
                    href: e.href || '',
                    alt: e.alt || '',
                    role: e.getAttribute('role') || '',
                    value: e.value || '',
                })""")

                # Create locator from the element
                # Use a combination of tag + attributes for stable locator
                locator = page.locator(f"{tag}").filter(has_text=text) if text else page.locator(f"{tag}[name='{attrs.get('name', '')}']")
                ref = self._refs.add(el)  # store the ElementHandle directly

                # Format line
                info_parts = [f"<{tag}>"]
                if attrs.get("type"):
                    info_parts.append(f"type={attrs['type']}")
                if attrs.get("name"):
                    info_parts.append(f"name={attrs['name']}")
                if attrs.get("placeholder"):
                    info_parts.append(f"placeholder=\"{attrs['placeholder']}\"")
                if attrs.get("role"):
                    info_parts.append(f"role={attrs['role']}")
                if text:
                    info_parts.append(f"\"{text.strip()[:60]}\"")
                if attrs.get("href"):
                    href = attrs["href"][:60]
                    info_parts.append(f"href={href}")
                if attrs.get("alt"):
                    info_parts.append(f"alt=\"{attrs['alt'][:40]}\"")

                lines.append(f"  {ref}  {' '.join(info_parts)}")

            except Exception:
                continue

        header = f"Page: {page.url}\nElements: {self._refs.count}\n"
        if interactive_only:
            header += "(interactive only)\n"
        header += "─" * 40

        return header + "\n" + "\n".join(lines) if lines else header + "\nNo elements found"

    def _resolve_ref(self, ref: str):
        """Resolve @e1 style ref to an ElementHandle."""
        if ref.startswith("@"):
            return self._refs.get(ref)
        return None


# ── Singleton ────────────────────────────────────────────────────

_daemon: Optional[BrowserDaemon] = None


async def get_browser() -> BrowserDaemon:
    """Get or create the browser daemon singleton."""
    global _daemon
    if _daemon is None or not _daemon.is_running:
        _daemon = BrowserDaemon()
        await _daemon.start()
    return _daemon
