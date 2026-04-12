"""
LSP Tool for NeoMind Agent.

Provides Language Server Protocol integration for code intelligence:
go-to-definition, find-references, hover, document symbols.

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class LSPAction(Enum):
    """LSP request methods."""
    GO_TO_DEFINITION = "textDocument/definition"
    FIND_REFERENCES = "textDocument/references"
    HOVER = "textDocument/hover"
    DOCUMENT_SYMBOL = "textDocument/documentSymbol"
    WORKSPACE_SYMBOL = "workspace/symbol"
    COMPLETION = "textDocument/completion"


@dataclass
class LSPLocation:
    """A location in a source file."""
    file_path: str
    line: int
    character: int
    end_line: Optional[int] = None
    end_character: Optional[int] = None


@dataclass
class LSPSymbol:
    """A symbol found in the workspace or document."""
    name: str
    kind: str  # function, class, variable, etc.
    location: LSPLocation
    container: Optional[str] = None  # parent class/module


@dataclass
class LSPHoverInfo:
    """Hover information for a symbol."""
    content: str
    language: Optional[str] = None
    range: Optional[LSPLocation] = None


@dataclass
class LSPResult:
    """Result from an LSP operation."""
    success: bool
    action: LSPAction
    locations: List[LSPLocation] = field(default_factory=list)
    symbols: List[LSPSymbol] = field(default_factory=list)
    hover: Optional[LSPHoverInfo] = None
    completions: List[Dict[str, str]] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: float = 0.0


# LSP symbol kind codes to human-readable names
_SYMBOL_KIND_MAP: Dict[int, str] = {
    1: "file", 2: "module", 3: "namespace", 4: "package",
    5: "class", 6: "method", 7: "property", 8: "field",
    9: "constructor", 10: "enum", 11: "interface", 12: "function",
    13: "variable", 14: "constant", 15: "string", 16: "number",
    17: "boolean", 18: "array", 19: "object", 20: "key",
    21: "null", 22: "enum_member", 23: "struct", 24: "event",
    25: "operator", 26: "type_parameter",
}


class LSPTool:
    """
    LSP client for code intelligence features.

    Manages language server processes and communicates via
    stdin/stdout using the LSP Content-Length header protocol.

    Features:
    - Go-to-definition
    - Find references
    - Hover information
    - Document / workspace symbols
    - Code completion
    """

    # Map file extensions to known language servers
    LANGUAGE_SERVERS: Dict[str, Dict[str, Any]] = {
        ".py": {"cmd": ["pylsp"], "name": "pylsp"},
        ".ts": {"cmd": ["typescript-language-server", "--stdio"], "name": "tsserver"},
        ".js": {"cmd": ["typescript-language-server", "--stdio"], "name": "tsserver"},
        ".go": {"cmd": ["gopls"], "name": "gopls"},
        ".rs": {"cmd": ["rust-analyzer"], "name": "rust-analyzer"},
        ".java": {"cmd": ["jdtls"], "name": "jdtls"},
    }

    def __init__(self, workspace_root: Optional[str] = None):
        """
        Initialize LSP tool.

        Args:
            workspace_root: Root directory for the workspace.
                            Defaults to current working directory.
        """
        self.workspace_root = workspace_root or os.getcwd()
        self._servers: Dict[str, asyncio.subprocess.Process] = {}
        self._request_id: int = 0
        self._initialized: Dict[str, bool] = {}
        self._pending_responses: Dict[str, Dict[int, asyncio.Future]] = {}
        self._reader_tasks: Dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def go_to_definition(
        self, file_path: str, line: int, character: int
    ) -> LSPResult:
        """
        Go to the definition of the symbol at the given position.

        Args:
            file_path: Absolute path to the source file
            line: Zero-based line number
            character: Zero-based character offset

        Returns:
            LSPResult with locations of the definition(s)
        """
        start = time.monotonic()
        action = LSPAction.GO_TO_DEFINITION

        try:
            language = await self._ensure_server(file_path)
            await self._notify_did_open(language, file_path)

            params = self._text_document_position_params(file_path, line, character)
            response = await self._send_request(language, action.value, params)

            locations = self._parse_locations(response.get("result"))
            duration = (time.monotonic() - start) * 1000

            return LSPResult(
                success=True, action=action,
                locations=locations, duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return LSPResult(
                success=False, action=action,
                error=str(e), duration_ms=duration,
            )

    async def find_references(
        self, file_path: str, line: int, character: int
    ) -> LSPResult:
        """
        Find all references to the symbol at the given position.

        Args:
            file_path: Absolute path to the source file
            line: Zero-based line number
            character: Zero-based character offset

        Returns:
            LSPResult with locations of all references
        """
        start = time.monotonic()
        action = LSPAction.FIND_REFERENCES

        try:
            language = await self._ensure_server(file_path)
            await self._notify_did_open(language, file_path)

            params = self._text_document_position_params(file_path, line, character)
            params["context"] = {"includeDeclaration": True}
            response = await self._send_request(language, action.value, params)

            locations = self._parse_locations(response.get("result"))
            duration = (time.monotonic() - start) * 1000

            return LSPResult(
                success=True, action=action,
                locations=locations, duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return LSPResult(
                success=False, action=action,
                error=str(e), duration_ms=duration,
            )

    async def hover(
        self, file_path: str, line: int, character: int
    ) -> LSPResult:
        """
        Get hover information for the symbol at the given position.

        Args:
            file_path: Absolute path to the source file
            line: Zero-based line number
            character: Zero-based character offset

        Returns:
            LSPResult with hover information
        """
        start = time.monotonic()
        action = LSPAction.HOVER

        try:
            language = await self._ensure_server(file_path)
            await self._notify_did_open(language, file_path)

            params = self._text_document_position_params(file_path, line, character)
            response = await self._send_request(language, action.value, params)

            hover_info = self._parse_hover(response.get("result"))
            duration = (time.monotonic() - start) * 1000

            return LSPResult(
                success=True, action=action,
                hover=hover_info, duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return LSPResult(
                success=False, action=action,
                error=str(e), duration_ms=duration,
            )

    async def document_symbols(self, file_path: str) -> LSPResult:
        """
        Get all symbols in a document.

        Args:
            file_path: Absolute path to the source file

        Returns:
            LSPResult with document symbols
        """
        start = time.monotonic()
        action = LSPAction.DOCUMENT_SYMBOL

        try:
            language = await self._ensure_server(file_path)
            await self._notify_did_open(language, file_path)

            params = {
                "textDocument": {"uri": self._file_uri(file_path)},
            }
            response = await self._send_request(language, action.value, params)

            symbols = self._parse_symbols(response.get("result"))
            duration = (time.monotonic() - start) * 1000

            return LSPResult(
                success=True, action=action,
                symbols=symbols, duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return LSPResult(
                success=False, action=action,
                error=str(e), duration_ms=duration,
            )

    async def workspace_symbols(self, query: str) -> LSPResult:
        """
        Search for symbols across the workspace.

        Args:
            query: Symbol name or partial match

        Returns:
            LSPResult with matching symbols
        """
        start = time.monotonic()
        action = LSPAction.WORKSPACE_SYMBOL

        try:
            # Use the first available server for workspace queries
            if not self._initialized:
                raise RuntimeError("No language server is running. Open a file first.")
            language = next(iter(self._initialized))

            params = {"query": query}
            response = await self._send_request(language, action.value, params)

            symbols = self._parse_symbols(response.get("result"))
            duration = (time.monotonic() - start) * 1000

            return LSPResult(
                success=True, action=action,
                symbols=symbols, duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return LSPResult(
                success=False, action=action,
                error=str(e), duration_ms=duration,
            )

    async def completion(
        self, file_path: str, line: int, character: int
    ) -> LSPResult:
        """
        Get code completions at the given position.

        Args:
            file_path: Absolute path to the source file
            line: Zero-based line number
            character: Zero-based character offset

        Returns:
            LSPResult with completion items
        """
        start = time.monotonic()
        action = LSPAction.COMPLETION

        try:
            language = await self._ensure_server(file_path)
            await self._notify_did_open(language, file_path)

            params = self._text_document_position_params(file_path, line, character)
            response = await self._send_request(language, action.value, params)

            completions = self._parse_completions(response.get("result"))
            duration = (time.monotonic() - start) * 1000

            return LSPResult(
                success=True, action=action,
                completions=completions, duration_ms=duration,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return LSPResult(
                success=False, action=action,
                error=str(e), duration_ms=duration,
            )

    async def close_all(self) -> None:
        """Shut down all running language servers gracefully."""
        for language in list(self._servers.keys()):
            await self._shutdown_server(language)
        self._servers.clear()
        self._initialized.clear()
        self._pending_responses.clear()
        for task in self._reader_tasks.values():
            task.cancel()
        self._reader_tasks.clear()

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    async def _ensure_server(self, file_path: str) -> str:
        """
        Ensure a language server is running for the given file type.

        Returns the language key (extension) used to look up the server.
        """
        ext = Path(file_path).suffix.lower()
        server_info = self.LANGUAGE_SERVERS.get(ext)
        if not server_info:
            raise ValueError(f"No language server configured for '{ext}' files")

        language = server_info["name"]
        if language not in self._initialized:
            await self._start_server(language, server_info["cmd"])
            await self._initialize(language)
        return language

    async def _start_server(self, language: str, cmd: List[str]) -> None:
        """Start a language server subprocess."""
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._servers[language] = process
        self._pending_responses[language] = {}
        # Start a background reader for this server's stdout
        self._reader_tasks[language] = asyncio.create_task(
            self._reader_loop(language)
        )

    async def _initialize(self, language: str) -> None:
        """Perform the LSP initialize / initialized handshake."""
        params = {
            "processId": os.getpid(),
            "rootUri": self._file_uri(self.workspace_root),
            "rootPath": self.workspace_root,
            "capabilities": {
                "textDocument": {
                    "definition": {"dynamicRegistration": False},
                    "references": {"dynamicRegistration": False},
                    "hover": {
                        "dynamicRegistration": False,
                        "contentFormat": ["markdown", "plaintext"],
                    },
                    "documentSymbol": {
                        "dynamicRegistration": False,
                        "hierarchicalDocumentSymbolSupport": True,
                    },
                    "completion": {
                        "dynamicRegistration": False,
                        "completionItem": {"snippetSupport": False},
                    },
                },
                "workspace": {
                    "symbol": {"dynamicRegistration": False},
                },
            },
            "workspaceFolders": [
                {
                    "uri": self._file_uri(self.workspace_root),
                    "name": os.path.basename(self.workspace_root),
                }
            ],
        }

        await self._send_request(language, "initialize", params)
        await self._send_notification(language, "initialized", {})
        self._initialized[language] = True

    async def _shutdown_server(self, language: str) -> None:
        """Send shutdown + exit to a language server."""
        process = self._servers.get(language)
        if process is None or process.returncode is not None:
            return

        try:
            await self._send_request(language, "shutdown", None)
            await self._send_notification(language, "exit", None)
        except Exception:
            pass

        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            process.kill()

    # ------------------------------------------------------------------
    # LSP protocol I/O
    # ------------------------------------------------------------------

    async def _send_request(
        self, language: str, method: str, params: Optional[Dict]
    ) -> Dict:
        """
        Send a JSON-RPC request and wait for the matching response.

        Args:
            language: Server key
            method: LSP method name
            params: Request parameters

        Returns:
            The full JSON-RPC response dict
        """
        self._request_id += 1
        req_id = self._request_id

        message: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_responses[language][req_id] = future

        await self._write_message(language, message)

        try:
            response = await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending_responses[language].pop(req_id, None)
            raise RuntimeError(f"Timeout waiting for response to {method} (id={req_id})")

        if "error" in response:
            err = response["error"]
            raise RuntimeError(
                f"LSP error [{err.get('code')}]: {err.get('message')}"
            )

        return response

    async def _send_notification(
        self, language: str, method: str, params: Optional[Dict]
    ) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        message: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            message["params"] = params

        await self._write_message(language, message)

    async def _write_message(self, language: str, message: Dict) -> None:
        """Encode and write a JSON-RPC message with Content-Length header."""
        process = self._servers.get(language)
        if process is None or process.stdin is None:
            raise RuntimeError(f"Language server '{language}' is not running")

        body = json.dumps(message).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        process.stdin.write(header + body)
        await process.stdin.drain()

    async def _reader_loop(self, language: str) -> None:
        """
        Background task that continuously reads JSON-RPC messages from
        the server's stdout and resolves pending futures.
        """
        process = self._servers.get(language)
        if process is None or process.stdout is None:
            return

        try:
            while True:
                message = await self._read_message(process.stdout)
                if message is None:
                    break  # EOF

                msg_id = message.get("id")
                if msg_id is not None and msg_id in self._pending_responses.get(language, {}):
                    future = self._pending_responses[language].pop(msg_id)
                    if not future.done():
                        future.set_result(message)
                # Notifications and server-initiated requests are silently
                # ignored for now (e.g. window/logMessage, diagnostics).
        except asyncio.CancelledError:
            return
        except Exception:
            # Server crashed or pipe broken
            return

    async def _read_message(
        self, reader: asyncio.StreamReader
    ) -> Optional[Dict]:
        """Read a single LSP JSON-RPC message from *reader*."""
        # Read headers until we see the blank line separator
        content_length = 0
        while True:
            line = await reader.readline()
            if not line:
                return None  # EOF

            line_str = line.decode("ascii", errors="replace").strip()
            if not line_str:
                break  # End of headers

            if line_str.lower().startswith("content-length:"):
                content_length = int(line_str.split(":", 1)[1].strip())

        if content_length == 0:
            return None

        body = await reader.readexactly(content_length)
        return json.loads(body.decode("utf-8"))

    # ------------------------------------------------------------------
    # Notification helpers
    # ------------------------------------------------------------------

    async def _notify_did_open(self, language: str, file_path: str) -> None:
        """Send textDocument/didOpen so the server knows about the file."""
        try:
            text = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""

        ext = Path(file_path).suffix.lower()
        lang_id_map = {
            ".py": "python", ".ts": "typescript", ".js": "javascript",
            ".go": "go", ".rs": "rust", ".java": "java",
        }
        lang_id = lang_id_map.get(ext, "plaintext")

        params = {
            "textDocument": {
                "uri": self._file_uri(file_path),
                "languageId": lang_id,
                "version": 1,
                "text": text,
            }
        }
        await self._send_notification(language, "textDocument/didOpen", params)

    # ------------------------------------------------------------------
    # Response parsing helpers
    # ------------------------------------------------------------------

    def _parse_locations(self, result: Any) -> List[LSPLocation]:
        """Parse definition / references response into LSPLocations."""
        if result is None:
            return []

        items = result if isinstance(result, list) else [result]
        locations: List[LSPLocation] = []

        for item in items:
            # Handle both Location and LocationLink
            if "targetUri" in item:
                uri = item["targetUri"]
                rng = item.get("targetSelectionRange") or item.get("targetRange", {})
            else:
                uri = item.get("uri", "")
                rng = item.get("range", {})

            start = rng.get("start", {})
            end = rng.get("end", {})

            locations.append(LSPLocation(
                file_path=self._uri_to_path(uri),
                line=start.get("line", 0),
                character=start.get("character", 0),
                end_line=end.get("line"),
                end_character=end.get("character"),
            ))

        return locations

    def _parse_symbols(self, result: Any) -> List[LSPSymbol]:
        """Parse document/workspace symbol responses."""
        if result is None:
            return []

        symbols: List[LSPSymbol] = []
        items = result if isinstance(result, list) else [result]

        for item in items:
            # DocumentSymbol (hierarchical) has selectionRange
            # SymbolInformation (flat) has location
            if "selectionRange" in item:
                rng = item["selectionRange"]
                uri = ""  # DocumentSymbol doesn't carry a URI
                file_path = ""
            else:
                loc = item.get("location", {})
                uri = loc.get("uri", "")
                rng = loc.get("range", {})
                file_path = self._uri_to_path(uri)

            start = rng.get("start", {})
            end = rng.get("end", {})
            kind_num = item.get("kind", 0)

            symbols.append(LSPSymbol(
                name=item.get("name", ""),
                kind=_SYMBOL_KIND_MAP.get(kind_num, "unknown"),
                location=LSPLocation(
                    file_path=file_path,
                    line=start.get("line", 0),
                    character=start.get("character", 0),
                    end_line=end.get("line"),
                    end_character=end.get("character"),
                ),
                container=item.get("containerName"),
            ))

            # Recurse into children for hierarchical document symbols
            for child in item.get("children", []):
                child_symbols = self._parse_symbols([child])
                for cs in child_symbols:
                    if cs.container is None:
                        cs.container = item.get("name")
                symbols.extend(child_symbols)

        return symbols

    def _parse_hover(self, result: Any) -> Optional[LSPHoverInfo]:
        """Parse hover response."""
        if result is None:
            return None

        contents = result.get("contents", "")
        language: Optional[str] = None

        # contents can be a string, MarkupContent, or MarkedString[]
        if isinstance(contents, str):
            content = contents
        elif isinstance(contents, dict):
            content = contents.get("value", "")
            language = contents.get("language") or contents.get("kind")
        elif isinstance(contents, list):
            parts = []
            for c in contents:
                if isinstance(c, str):
                    parts.append(c)
                elif isinstance(c, dict):
                    language = language or c.get("language")
                    parts.append(c.get("value", ""))
            content = "\n---\n".join(parts)
        else:
            content = str(contents)

        hover_range = None
        if "range" in result:
            rng = result["range"]
            start = rng.get("start", {})
            end = rng.get("end", {})
            hover_range = LSPLocation(
                file_path="",
                line=start.get("line", 0),
                character=start.get("character", 0),
                end_line=end.get("line"),
                end_character=end.get("character"),
            )

        return LSPHoverInfo(content=content, language=language, range=hover_range)

    def _parse_completions(self, result: Any) -> List[Dict[str, str]]:
        """Parse completion response into simple dicts."""
        if result is None:
            return []

        # result can be CompletionList or CompletionItem[]
        items = result if isinstance(result, list) else result.get("items", [])

        completions: List[Dict[str, str]] = []
        for item in items:
            completions.append({
                "label": item.get("label", ""),
                "kind": str(item.get("kind", "")),
                "detail": item.get("detail", ""),
                "insert_text": item.get("insertText", item.get("label", "")),
            })

        return completions

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _file_uri(path: str) -> str:
        """Convert a filesystem path to a file:// URI."""
        abs_path = os.path.abspath(path)
        # On Windows, paths start with a drive letter; Unix paths start with /
        if not abs_path.startswith("/"):
            abs_path = "/" + abs_path
        return "file://" + abs_path

    @staticmethod
    def _uri_to_path(uri: str) -> str:
        """Convert a file:// URI back to a filesystem path."""
        if uri.startswith("file://"):
            path = uri[len("file://"):]
            # On Windows, strip the leading / before the drive letter
            if len(path) > 2 and path[0] == "/" and path[2] == ":":
                path = path[1:]
            return path
        return uri

    @staticmethod
    def _text_document_position_params(
        file_path: str, line: int, character: int
    ) -> Dict[str, Any]:
        """Build TextDocumentPositionParams."""
        return {
            "textDocument": {
                "uri": LSPTool._file_uri(file_path),
            },
            "position": {
                "line": line,
                "character": character,
            },
        }


__all__ = [
    'LSPTool',
    'LSPAction',
    'LSPLocation',
    'LSPSymbol',
    'LSPHoverInfo',
    'LSPResult',
]


if __name__ == "__main__":
    import asyncio

    async def main():
        print("=== LSP Tool Test ===\n")

        tool = LSPTool(workspace_root="/tmp")

        # Verify dataclass creation
        loc = LSPLocation(file_path="/tmp/test.py", line=10, character=5)
        print(f"Location: {loc.file_path}:{loc.line}:{loc.character}")

        sym = LSPSymbol(name="my_func", kind="function", location=loc, container="MyClass")
        print(f"Symbol: {sym.name} ({sym.kind}) in {sym.container}")

        hover = LSPHoverInfo(content="def my_func() -> None", language="python")
        print(f"Hover: {hover.content}")

        result = LSPResult(
            success=True,
            action=LSPAction.GO_TO_DEFINITION,
            locations=[loc],
        )
        print(f"Result: success={result.success}, action={result.action.value}")
        print(f"  locations={len(result.locations)}")

        # URI round-trip
        uri = LSPTool._file_uri("/tmp/test.py")
        back = LSPTool._uri_to_path(uri)
        assert back == "/tmp/test.py", f"URI round-trip failed: {back}"
        print(f"URI round-trip OK: {uri} -> {back}")

        print("\nLSP Tool dataclass test passed!")

    asyncio.run(main())
