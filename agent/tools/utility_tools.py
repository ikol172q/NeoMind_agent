"""
Utility Tools for NeoMind Agent.

Implements commonly needed utility tools:
- WebFetchTool: Fetch web page content
- WebSearchTool: Search the web
- NotebookEditTool: Edit Jupyter notebooks
- TodoWriteTool: Write/manage todo lists
- AskUserQuestionTool: Structured user prompts
- SleepTool: Async sleep/delay
- BriefTool: Toggle brief/verbose output mode

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WebFetchResult:
    """Result from fetching a web URL."""
    success: bool
    url: str
    content: str = ""
    status_code: int = 0
    content_type: str = ""
    error: Optional[str] = None


@dataclass
class SearchHit:
    """A single search result entry."""
    title: str
    url: str
    snippet: str


@dataclass
class WebSearchResult:
    """Result from a web search."""
    success: bool
    query: str
    results: List[SearchHit] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class NotebookCell:
    """Represents a single Jupyter notebook cell."""
    index: int
    cell_type: str
    source: str
    outputs: List[Any] = field(default_factory=list)


@dataclass
class NotebookResult:
    """Result from a notebook operation."""
    success: bool
    message: str
    cells: List[NotebookCell] = field(default_factory=list)
    error: Optional[str] = None


class TodoPriority(Enum):
    """Priority levels for todo items."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class TodoItem:
    """A single todo entry."""
    id: str
    text: str
    priority: str = "medium"
    completed: bool = False
    created_at: str = ""
    completed_at: Optional[str] = None


@dataclass
class TodoResult:
    """Result from a todo operation."""
    success: bool
    message: str
    todos: List[TodoItem] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class AskResult:
    """Result from asking the user a question."""
    question: str
    options: Optional[List[str]] = None
    default: Optional[str] = None
    formatted: str = ""


@dataclass
class SleepResult:
    """Result from a sleep operation."""
    success: bool
    slept_seconds: float
    reason: str = ""


@dataclass
class BriefResult:
    """Result from toggling brief mode."""
    brief: bool
    message: str


# ---------------------------------------------------------------------------
# HTML text extractor (stdlib only)
# ---------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """Simple HTML-to-text extractor using the stdlib HTMLParser."""

    _SKIP_TAGS = frozenset({"script", "style", "noscript", "head"})

    def __init__(self) -> None:
        super().__init__()
        self._pieces: List[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._pieces.append(text)

    def get_text(self) -> str:
        return "\n".join(self._pieces)


def _strip_html(html: str) -> str:
    """Strip HTML tags and return plain text."""
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


# ---------------------------------------------------------------------------
# WebFetchTool
# ---------------------------------------------------------------------------

class WebFetchTool:
    """Fetch and extract content from web URLs."""

    _DEFAULT_UA = (
        "Mozilla/5.0 (compatible; NeoMindAgent/1.0; "
        "+https://github.com/neomind-agent)"
    )

    async def fetch(
        self,
        url: str,
        extract_text: bool = True,
        timeout: float = 30,
    ) -> WebFetchResult:
        """
        Fetch content from a URL.

        Args:
            url: The URL to fetch.
            extract_text: If True, strip HTML tags and return plain text.
            timeout: Request timeout in seconds.

        Returns:
            WebFetchResult with content, status_code and content_type.
        """
        if not url or not url.strip():
            return WebFetchResult(
                success=False,
                url=url or "",
                error="URL cannot be empty",
            )

        def _do_fetch() -> WebFetchResult:
            req = Request(url, headers={"User-Agent": self._DEFAULT_UA})
            try:
                with urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                    content_type = resp.headers.get("Content-Type", "")
                    charset = "utf-8"
                    # Attempt to extract charset from content-type header
                    ct_lower = content_type.lower()
                    if "charset=" in ct_lower:
                        charset = ct_lower.split("charset=")[-1].split(";")[0].strip()

                    try:
                        body = raw.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        body = raw.decode("utf-8", errors="replace")

                    if extract_text and "html" in ct_lower:
                        body = _strip_html(body)

                    return WebFetchResult(
                        success=True,
                        url=url,
                        content=body,
                        status_code=resp.status,
                        content_type=content_type,
                    )
            except HTTPError as exc:
                return WebFetchResult(
                    success=False,
                    url=url,
                    status_code=exc.code,
                    error=f"HTTP {exc.code}: {exc.reason}",
                )
            except URLError as exc:
                return WebFetchResult(
                    success=False,
                    url=url,
                    error=f"URL error: {exc.reason}",
                )
            except Exception as exc:  # noqa: BLE001
                return WebFetchResult(
                    success=False,
                    url=url,
                    error=str(exc),
                )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_fetch)


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------

class WebSearchTool:
    """Search the web using available search APIs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        engine: str = "duckduckgo",
    ) -> None:
        """
        Initialize the search tool.

        Args:
            api_key: Optional API key (reserved for future engines).
            engine: Search engine to use. Currently only ``duckduckgo``
                    is supported (no API key required).
        """
        self.api_key = api_key
        self.engine = engine

    async def search(
        self,
        query: str,
        num_results: int = 5,
    ) -> WebSearchResult:
        """
        Search the web.

        Resolution order (matches the agent-wide search policy):
          1. UniversalSearchEngine (Tavily-primary; LLM-optimized,
             higher quality than DDG). Used when the package +
             TAVILY_API_KEY are available — happens silently if so.
          2. DuckDuckGo HTML lite endpoint — original CLI fallback,
             no API key required, kept so the tool still works in
             environments without Tavily set up.

        Args:
            query: Search query string.
            num_results: Maximum number of results to return.

        Returns:
            WebSearchResult with a list of SearchHit items.
        """
        if not query or not query.strip():
            return WebSearchResult(
                success=False,
                query=query or "",
                error="Query cannot be empty",
            )

        # Try Tavily-primary engine first (silently degrades if not set up)
        try:
            engine_result = await self._search_via_universal_engine(
                query, num_results)
            if engine_result is not None:
                return engine_result
        except Exception as exc:
            # Don't let engine init failures break CLI search — fall back
            import logging as _lg
            _lg.getLogger(__name__).debug(
                "WebSearchTool universal engine path failed: %s — "
                "falling back to %s", exc, self.engine)

        if self.engine == "duckduckgo":
            return await self._search_duckduckgo(query, num_results)

        return WebSearchResult(
            success=False,
            query=query,
            error=f"Unsupported search engine: {self.engine}",
        )

    async def _search_via_universal_engine(
        self, query: str, num_results: int,
    ) -> Optional[WebSearchResult]:
        """Use UniversalSearchEngine (Tavily-primary). Returns None if
        the engine has no available sources (e.g. missing tavily-python
        + missing duckduckgo_search/feedparser). Returns a populated
        WebSearchResult otherwise. Raises on init / network failure
        so the caller can fall back."""
        from agent.search.engine import UniversalSearchEngine
        # Singleton-per-process is fine; engine init is cheap when
        # source classes' .available checks fail fast.
        global _UNIVERSAL_ENGINE_SINGLETON
        try:
            engine = _UNIVERSAL_ENGINE_SINGLETON
        except NameError:
            engine = None
        if engine is None:
            engine = UniversalSearchEngine(domain="general")
            globals()["_UNIVERSAL_ENGINE_SINGLETON"] = engine
        # If neither tier has any source available, return None to
        # let caller fall back to its own DDG implementation.
        if not (engine.tier1_sources or engine.tier2_sources or engine.tier3_sources):
            return None
        result = await engine.search_advanced(
            query=query,
            max_results=num_results,
            extract_content=False,
            expand_queries=False,
        )
        if not result or not result.items:
            return None
        hits: List[SearchHit] = []
        for it in result.items[:num_results]:
            hits.append(SearchHit(
                title=it.title or "",
                url=it.url or "",
                snippet=(it.snippet or "")[:300],
            ))
        return WebSearchResult(success=True, query=query, results=hits)

    async def _search_duckduckgo(
        self,
        query: str,
        num_results: int,
    ) -> WebSearchResult:
        """Search via the DuckDuckGo HTML lite endpoint."""

        def _do_search() -> WebSearchResult:
            url = "https://lite.duckduckgo.com/lite/"
            data = urlencode({"q": query}).encode("utf-8")
            req = Request(
                url,
                data=data,
                method="POST",
                headers={
                    "User-Agent": WebFetchTool._DEFAULT_UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            try:
                with urlopen(req, timeout=15) as resp:
                    html = resp.read().decode("utf-8", errors="replace")

                results = self._parse_ddg_lite(html, num_results)

                return WebSearchResult(
                    success=True,
                    query=query,
                    results=results,
                )
            except Exception as exc:  # noqa: BLE001
                return WebSearchResult(
                    success=False,
                    query=query,
                    error=str(exc),
                )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_search)

    @staticmethod
    def _parse_ddg_lite(html: str, max_results: int) -> List[SearchHit]:
        """
        Parse the DuckDuckGo lite HTML response.

        The lite page has a table-based layout.  Result links live inside
        ``<a>`` tags with ``class="result-link"``, and snippets appear in
        ``<td>`` elements with ``class="result-snippet"``.
        """
        hits: List[SearchHit] = []

        # Extract result links: <a rel="nofollow" href="..." class="result-link">Title</a>
        link_pattern = re.compile(
            r'<a[^>]+class="result-link"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE,
        )
        # Also try generic table row result links
        link_pattern_alt = re.compile(
            r'<a[^>]+rel="nofollow"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE,
        )

        snippet_pattern = re.compile(
            r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>',
            re.DOTALL | re.IGNORECASE,
        )

        links = link_pattern.findall(html)
        if not links:
            links = link_pattern_alt.findall(html)

        snippets = snippet_pattern.findall(html)

        for i, (href, title_html) in enumerate(links):
            if i >= max_results:
                break
            # Skip DuckDuckGo internal links
            if "duckduckgo.com" in href:
                continue
            title = _strip_html(title_html).strip() or href
            snippet = ""
            if i < len(snippets):
                snippet = _strip_html(snippets[i]).strip()
            hits.append(SearchHit(title=title, url=href, snippet=snippet))
            if len(hits) >= max_results:
                break

        return hits


# ---------------------------------------------------------------------------
# NotebookEditTool
# ---------------------------------------------------------------------------

class NotebookEditTool:
    """Read and edit Jupyter notebook cells."""

    @staticmethod
    def _read_nb(path: str) -> Dict[str, Any]:
        """Load a notebook file and return its JSON dict."""
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _write_nb(path: str, nb: Dict[str, Any]) -> None:
        """Write a notebook dict back to disk."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(nb, fh, indent=1, ensure_ascii=False)
            fh.write("\n")

    @staticmethod
    def _cell_source(cell: Dict[str, Any]) -> str:
        """Get cell source as a single string."""
        src = cell.get("source", "")
        if isinstance(src, list):
            return "".join(src)
        return str(src)

    @staticmethod
    def _cell_outputs(cell: Dict[str, Any]) -> List[Any]:
        """Extract cell outputs (code cells only)."""
        return cell.get("outputs", [])

    def _to_notebook_cells(self, cells: List[Dict[str, Any]]) -> List[NotebookCell]:
        """Convert raw cell dicts to NotebookCell dataclasses."""
        result: List[NotebookCell] = []
        for idx, cell in enumerate(cells):
            result.append(
                NotebookCell(
                    index=idx,
                    cell_type=cell.get("cell_type", "code"),
                    source=self._cell_source(cell),
                    outputs=self._cell_outputs(cell),
                )
            )
        return result

    def read_notebook(self, path: str) -> NotebookResult:
        """
        Read a Jupyter notebook and return its cells.

        Args:
            path: Path to the ``.ipynb`` file.

        Returns:
            NotebookResult with all cells.
        """
        try:
            nb = self._read_nb(path)
            cells = nb.get("cells", [])
            return NotebookResult(
                success=True,
                message=f"Read {len(cells)} cell(s) from {path}",
                cells=self._to_notebook_cells(cells),
            )
        except FileNotFoundError:
            return NotebookResult(
                success=False,
                message=f"Notebook not found: {path}",
                error="not_found",
            )
        except json.JSONDecodeError as exc:
            return NotebookResult(
                success=False,
                message=f"Invalid notebook JSON: {exc}",
                error="invalid_json",
            )

    def edit_cell(
        self,
        path: str,
        cell_index: int,
        new_source: str,
    ) -> NotebookResult:
        """
        Edit a specific cell's source.

        Args:
            path: Path to the ``.ipynb`` file.
            cell_index: Zero-based index of the cell to edit.
            new_source: New source content for the cell.

        Returns:
            NotebookResult reflecting the updated notebook.
        """
        try:
            nb = self._read_nb(path)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            return NotebookResult(
                success=False,
                message=str(exc),
                error="read_error",
            )

        cells = nb.get("cells", [])
        if cell_index < 0 or cell_index >= len(cells):
            return NotebookResult(
                success=False,
                message=f"Cell index {cell_index} out of range (0..{len(cells) - 1})",
                error="index_error",
            )

        # Notebook format stores source as a list of lines
        cells[cell_index]["source"] = new_source.splitlines(keepends=True)
        self._write_nb(path, nb)

        return NotebookResult(
            success=True,
            message=f"Cell {cell_index} updated",
            cells=self._to_notebook_cells(cells),
        )

    def add_cell(
        self,
        path: str,
        cell_type: str = "code",
        source: str = "",
        position: int = -1,
    ) -> NotebookResult:
        """
        Add a new cell to the notebook.

        Args:
            path: Path to the ``.ipynb`` file.
            cell_type: ``"code"`` or ``"markdown"``.
            source: Cell source content.
            position: Insert position (-1 means append).

        Returns:
            NotebookResult reflecting the updated notebook.
        """
        try:
            nb = self._read_nb(path)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            return NotebookResult(
                success=False,
                message=str(exc),
                error="read_error",
            )

        new_cell: Dict[str, Any] = {
            "cell_type": cell_type,
            "metadata": {},
            "source": source.splitlines(keepends=True),
        }
        if cell_type == "code":
            new_cell["execution_count"] = None
            new_cell["outputs"] = []

        cells = nb.get("cells", [])
        if position < 0 or position >= len(cells):
            cells.append(new_cell)
            pos_label = len(cells) - 1
        else:
            cells.insert(position, new_cell)
            pos_label = position

        nb["cells"] = cells
        self._write_nb(path, nb)

        return NotebookResult(
            success=True,
            message=f"Added {cell_type} cell at position {pos_label}",
            cells=self._to_notebook_cells(cells),
        )

    def delete_cell(self, path: str, cell_index: int) -> NotebookResult:
        """
        Delete a cell from the notebook.

        Args:
            path: Path to the ``.ipynb`` file.
            cell_index: Zero-based index of the cell to delete.

        Returns:
            NotebookResult reflecting the updated notebook.
        """
        try:
            nb = self._read_nb(path)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            return NotebookResult(
                success=False,
                message=str(exc),
                error="read_error",
            )

        cells = nb.get("cells", [])
        if cell_index < 0 or cell_index >= len(cells):
            return NotebookResult(
                success=False,
                message=f"Cell index {cell_index} out of range (0..{len(cells) - 1})",
                error="index_error",
            )

        deleted = cells.pop(cell_index)
        self._write_nb(path, nb)

        return NotebookResult(
            success=True,
            message=f"Deleted {deleted.get('cell_type', 'unknown')} cell at index {cell_index}",
            cells=self._to_notebook_cells(cells),
        )


# ---------------------------------------------------------------------------
# TodoWriteTool
# ---------------------------------------------------------------------------

class TodoWriteTool:
    """
    Manage a todo list persisted to ``.neomind/todos.json``.

    The todo file is stored relative to the given workspace directory
    (defaults to the current working directory).
    """

    def __init__(self, workspace: Optional[str] = None) -> None:
        self._workspace = workspace or os.getcwd()
        self._dir = os.path.join(self._workspace, ".neomind")
        self._path = os.path.join(self._dir, "todos.json")
        self._todos: Dict[str, TodoItem] = {}
        self._load()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        """Load todos from disk."""
        if not os.path.isfile(self._path):
            self._todos = {}
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._todos = {
                item["id"]: TodoItem(**item) for item in data
            }
        except (json.JSONDecodeError, KeyError, TypeError):
            self._todos = {}

    def _save(self) -> None:
        """Persist todos to disk."""
        os.makedirs(self._dir, exist_ok=True)
        items = [
            {
                "id": t.id,
                "text": t.text,
                "priority": t.priority,
                "completed": t.completed,
                "created_at": t.created_at,
                "completed_at": t.completed_at,
            }
            for t in self._todos.values()
        ]
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(items, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    # -- public API ----------------------------------------------------------

    def add(self, text: str, priority: str = "medium") -> TodoResult:
        """
        Add a new todo item.

        Args:
            text: Todo description.
            priority: ``"low"``, ``"medium"``, or ``"high"``.

        Returns:
            TodoResult with the created item.
        """
        if not text or not text.strip():
            return TodoResult(
                success=False,
                message="Todo text cannot be empty",
                error="invalid_text",
            )

        if priority not in {p.value for p in TodoPriority}:
            priority = TodoPriority.MEDIUM.value

        todo_id = str(uuid.uuid4())[:8]
        item = TodoItem(
            id=todo_id,
            text=text.strip(),
            priority=priority,
            completed=False,
            created_at=datetime.now().isoformat(),
        )
        self._todos[todo_id] = item
        self._save()

        return TodoResult(
            success=True,
            message=f"Todo {todo_id} added",
            todos=[item],
        )

    def complete(self, todo_id: str) -> TodoResult:
        """
        Mark a todo as completed.

        Args:
            todo_id: The todo item ID.

        Returns:
            TodoResult with the updated item.
        """
        item = self._todos.get(todo_id)
        if not item:
            return TodoResult(
                success=False,
                message=f"Todo {todo_id} not found",
                error="not_found",
            )
        if item.completed:
            return TodoResult(
                success=False,
                message=f"Todo {todo_id} is already completed",
                error="already_completed",
            )

        item.completed = True
        item.completed_at = datetime.now().isoformat()
        self._save()

        return TodoResult(
            success=True,
            message=f"Todo {todo_id} completed",
            todos=[item],
        )

    def remove(self, todo_id: str) -> TodoResult:
        """
        Remove a todo item.

        Args:
            todo_id: The todo item ID.

        Returns:
            TodoResult confirming removal.
        """
        item = self._todos.pop(todo_id, None)
        if not item:
            return TodoResult(
                success=False,
                message=f"Todo {todo_id} not found",
                error="not_found",
            )

        self._save()
        return TodoResult(
            success=True,
            message=f"Todo {todo_id} removed",
            todos=[item],
        )

    def list_todos(self, show_completed: bool = False) -> TodoResult:
        """
        List todo items.

        Args:
            show_completed: If False, only show incomplete items.

        Returns:
            TodoResult with matching items.
        """
        items = list(self._todos.values())
        if not show_completed:
            items = [t for t in items if not t.completed]

        # Sort: high > medium > low, then by creation time
        priority_order = {"high": 0, "medium": 1, "low": 2}
        items.sort(key=lambda t: (priority_order.get(t.priority, 1), t.created_at))

        return TodoResult(
            success=True,
            message=f"Found {len(items)} todo(s)",
            todos=items,
        )


# ---------------------------------------------------------------------------
# AskUserQuestionTool
# ---------------------------------------------------------------------------

class AskUserQuestionTool:
    """
    Generate structured questions for the user.

    The tool formats the question for display; the actual answer is
    expected in the next conversational turn.
    """

    def ask(
        self,
        question: str,
        options: Optional[List[str]] = None,
        default: Optional[str] = None,
    ) -> AskResult:
        """
        Create a structured user prompt.

        Args:
            question: The question text.
            options: Optional list of allowed answers.
            default: Optional default answer.

        Returns:
            AskResult with a ``formatted`` string ready for display.
        """
        lines: List[str] = [question]

        if options:
            lines.append("")
            for idx, opt in enumerate(options, start=1):
                marker = " (default)" if opt == default else ""
                lines.append(f"  {idx}. {opt}{marker}")

        if default and not options:
            lines.append(f"  [default: {default}]")

        formatted = "\n".join(lines)

        return AskResult(
            question=question,
            options=options,
            default=default,
            formatted=formatted,
        )


# ---------------------------------------------------------------------------
# SleepTool
# ---------------------------------------------------------------------------

_MAX_SLEEP_SECONDS: float = 300.0


class SleepTool:
    """Async sleep / delay utility."""

    async def sleep(
        self,
        seconds: float,
        reason: str = "",
    ) -> SleepResult:
        """
        Sleep for the specified duration.

        The actual sleep time is capped at 300 seconds.

        Args:
            seconds: Duration to sleep (will be clamped to [0, 300]).
            reason: Optional human-readable reason for the delay.

        Returns:
            SleepResult indicating how long we actually slept.
        """
        clamped = max(0.0, min(seconds, _MAX_SLEEP_SECONDS))
        await asyncio.sleep(clamped)
        return SleepResult(
            success=True,
            slept_seconds=clamped,
            reason=reason,
        )


# ---------------------------------------------------------------------------
# BriefTool
# ---------------------------------------------------------------------------

class BriefTool:
    """Toggle brief / verbose output mode."""

    def __init__(self) -> None:
        self._brief: bool = False

    def toggle(self) -> BriefResult:
        """Toggle between brief and verbose mode."""
        self._brief = not self._brief
        mode = "brief" if self._brief else "verbose"
        return BriefResult(brief=self._brief, message=f"Output mode set to {mode}")

    def set_brief(self, enabled: bool) -> BriefResult:
        """
        Explicitly set the output mode.

        Args:
            enabled: True for brief mode, False for verbose.
        """
        self._brief = enabled
        mode = "brief" if self._brief else "verbose"
        return BriefResult(brief=self._brief, message=f"Output mode set to {mode}")

    @property
    def is_brief(self) -> bool:
        """Return whether brief mode is currently active."""
        return self._brief


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    # Result types
    "WebFetchResult",
    "SearchHit",
    "WebSearchResult",
    "NotebookCell",
    "NotebookResult",
    "TodoPriority",
    "TodoItem",
    "TodoResult",
    "AskResult",
    "SleepResult",
    "BriefResult",
    # Tool classes
    "WebFetchTool",
    "WebSearchTool",
    "NotebookEditTool",
    "TodoWriteTool",
    "AskUserQuestionTool",
    "SleepTool",
    "BriefTool",
]


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def _main() -> None:
        print("=== Utility Tools Smoke Test ===\n")

        # BriefTool
        brief = BriefTool()
        print(f"Brief mode: {brief.is_brief}")
        r = brief.toggle()
        print(f"After toggle: {r.message}")

        # AskUserQuestionTool
        ask = AskUserQuestionTool()
        q = ask.ask("Pick a colour:", options=["red", "blue", "green"], default="blue")
        print(f"\n{q.formatted}")

        # SleepTool
        sleep_tool = SleepTool()
        sr = await sleep_tool.sleep(0.1, reason="test")
        print(f"\nSlept {sr.slept_seconds}s ({sr.reason})")

        # WebFetchTool (just validates empty-url path)
        wf = WebFetchTool()
        fr = await wf.fetch("")
        print(f"\nEmpty-url fetch: success={fr.success}, error={fr.error}")

        # WebSearchTool (just validates empty-query path)
        ws = WebSearchTool()
        sr2 = await ws.search("")
        print(f"Empty-query search: success={sr2.success}, error={sr2.error}")

        print("\nUtility tools smoke test passed!")

    asyncio.run(_main())
