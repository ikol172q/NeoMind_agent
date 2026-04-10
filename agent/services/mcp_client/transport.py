"""MCP Transport implementations.

Supports stdio and HTTP (streamable) transports for MCP protocol.
Uses JSON-RPC 2.0 for message framing over both transport types.

Created: 2026-04-02
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TransportType(Enum):
    """Supported MCP transport mechanisms."""

    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"


@dataclass
class TransportConfig:
    """Configuration for an MCP transport connection.

    For stdio transports, set ``command`` and optionally ``args``/``env``.
    For HTTP/SSE transports, set ``url`` and optionally ``headers``.
    """

    transport_type: TransportType

    # Stdio fields
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None

    # HTTP / SSE fields
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None

    timeout: float = 30.0


class BaseTransport(ABC):
    """Abstract base for MCP transports.

    All transports exchange JSON-RPC 2.0 messages as ``Dict[str, Any]``.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish the transport connection."""

    @abstractmethod
    async def send(self, message: Dict[str, Any]) -> None:
        """Send a JSON-RPC message over the transport."""

    @abstractmethod
    async def receive(self) -> Dict[str, Any]:
        """Block until the next JSON-RPC message arrives and return it."""

    @abstractmethod
    async def close(self) -> None:
        """Tear down the transport connection."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return ``True`` when the transport is ready to send/receive."""


class StdioTransport(BaseTransport):
    """Transport via subprocess stdin/stdout using JSON-RPC.

    Launches the MCP server as a child process and communicates by writing
    newline-delimited JSON to its *stdin* and reading from its *stdout*.
    """

    def __init__(self, config: TransportConfig) -> None:
        self._config = config
        self._process: Optional[asyncio.subprocess.Process] = None
        self._connected: bool = False
        self._read_lock: asyncio.Lock = asyncio.Lock()
        self._write_lock: asyncio.Lock = asyncio.Lock()

    # ── lifecycle ────────────────────────────────────────────────────

    async def connect(self) -> None:
        if self._connected:
            return

        if not self._config.command:
            raise ValueError("StdioTransport requires a command in TransportConfig")

        cmd_args: List[str] = [self._config.command]
        if self._config.args:
            cmd_args.extend(self._config.args)

        env = self._config.env  # None means inherit current env

        self._process = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._connected = True
        logger.info("StdioTransport connected: %s", " ".join(cmd_args))

    async def send(self, message: Dict[str, Any]) -> None:
        if not self._connected or self._process is None or self._process.stdin is None:
            raise ConnectionError("StdioTransport is not connected")

        payload = json.dumps(message, separators=(",", ":")) + "\n"
        async with self._write_lock:
            self._process.stdin.write(payload.encode())
            await self._process.stdin.drain()

    async def receive(self) -> Dict[str, Any]:
        if not self._connected or self._process is None or self._process.stdout is None:
            raise ConnectionError("StdioTransport is not connected")

        async with self._read_lock:
            try:
                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=self._config.timeout,
                )
            except asyncio.TimeoutError:
                raise TimeoutError("StdioTransport read timed out")

        if not line:
            self._connected = False
            raise ConnectionError("StdioTransport: subprocess closed stdout")

        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"StdioTransport received invalid JSON: {line!r}") from exc

    async def close(self) -> None:
        if self._process is not None:
            try:
                if self._process.stdin and not self._process.stdin.is_closing():
                    self._process.stdin.close()
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()
            except ProcessLookupError:
                pass
            finally:
                self._process = None
                self._connected = False
                logger.info("StdioTransport closed")

    @property
    def is_connected(self) -> bool:
        if self._process is not None and self._process.returncode is not None:
            self._connected = False
        return self._connected


class HttpTransport(BaseTransport):
    """Transport via HTTP POST using JSON-RPC.

    Each ``send`` + ``receive`` pair corresponds to a single HTTP
    request/response cycle.  Uses only :mod:`urllib.request` (stdlib)
    so no external dependencies are required.
    """

    def __init__(self, config: TransportConfig) -> None:
        self._config = config
        self._connected: bool = False
        self._pending_responses: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

    # ── lifecycle ────────────────────────────────────────────────────

    async def connect(self) -> None:
        if self._connected:
            return

        if not self._config.url:
            raise ValueError("HttpTransport requires a url in TransportConfig")

        # Validate connectivity with a quick HEAD-like request (optional)
        self._connected = True
        logger.info("HttpTransport connected: %s", self._config.url)

    async def send(self, message: Dict[str, Any]) -> None:
        if not self._connected:
            raise ConnectionError("HttpTransport is not connected")

        response = await self._post(message)
        await self._pending_responses.put(response)

    async def receive(self) -> Dict[str, Any]:
        if not self._connected:
            raise ConnectionError("HttpTransport is not connected")

        try:
            return await asyncio.wait_for(
                self._pending_responses.get(),
                timeout=self._config.timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError("HttpTransport receive timed out")

    async def close(self) -> None:
        self._connected = False
        # Drain any leftover items
        while not self._pending_responses.empty():
            try:
                self._pending_responses.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info("HttpTransport closed")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── internal ─────────────────────────────────────────────────────

    async def _post(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an HTTP POST in a thread to avoid blocking the loop."""

        url = self._config.url
        assert url is not None

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._config.headers:
            headers.update(self._config.headers)

        body = json.dumps(message, separators=(",", ":")).encode()

        req = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method="POST",
        )

        loop = asyncio.get_running_loop()
        try:
            response_body: bytes = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: urllib.request.urlopen(
                        req, timeout=self._config.timeout
                    ).read(),
                ),
                timeout=self._config.timeout + 5,
            )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode(errors="replace")
            raise ConnectionError(
                f"HTTP {exc.code}: {error_body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(f"URL error: {exc.reason}") from exc
        except asyncio.TimeoutError:
            raise TimeoutError("HttpTransport POST timed out")

        try:
            return json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"HttpTransport received invalid JSON: {response_body!r}"
            ) from exc


def create_transport(config: TransportConfig) -> BaseTransport:
    """Factory: build the right transport from a :class:`TransportConfig`."""

    if config.transport_type == TransportType.STDIO:
        return StdioTransport(config)
    if config.transport_type in (TransportType.HTTP, TransportType.SSE):
        return HttpTransport(config)
    raise ValueError(f"Unsupported transport type: {config.transport_type}")
