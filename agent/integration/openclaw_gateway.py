# agent/finance/openclaw_gateway.py
"""
OpenClaw Gateway Client — connects NeoMind Finance to OpenClaw's messaging backbone.

Implements OpenClaw Gateway Protocol v3:
- JSON-encoded WebSocket frames
- RPC-style request/response with correlation IDs
- Server broadcast handling (incoming messages from WhatsApp/Telegram/Slack/etc.)
- Device token authentication
- Reconnect with exponential backoff

This allows NeoMind's finance personality to:
1. RECEIVE queries from any OpenClaw-connected messaging platform
2. PUSH alerts, digests, and reports through those same channels
3. Maintain persistent connection with heartbeat keepalive
"""

import os
import json
import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable, Awaitable
from enum import Enum

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

logger = logging.getLogger("neomind.openclaw")


# ── Protocol Constants ───────────────────────────────────────────────

OPENCLAW_DEFAULT_URL = "ws://127.0.0.1:18789"
PROTOCOL_VERSION = 3


class FrameType(str, Enum):
    """OpenClaw Gateway frame types."""
    RPC_CALL = "rpc_call"           # Client → Server: invoke a method
    RPC_RESPONSE = "rpc_response"   # Server → Client: result of an RPC call
    BROADCAST = "broadcast"         # Server → Client: push event (incoming message, etc.)
    HEARTBEAT = "heartbeat"         # Bidirectional keepalive
    AUTH = "auth"                   # Client → Server: authentication
    AUTH_RESULT = "auth_result"     # Server → Client: auth outcome


class BroadcastEvent(str, Enum):
    """Known broadcast event types from OpenClaw gateway."""
    MESSAGE_RECEIVED = "message.received"    # Incoming message from a channel
    MESSAGE_SENT = "message.sent"            # Confirmation of outbound message
    CHANNEL_JOINED = "channel.joined"
    CHANNEL_LEFT = "channel.left"
    SKILL_INVOKED = "skill.invoked"          # Another skill calling ours
    HEARTBEAT_TICK = "heartbeat.tick"


# ── Data Classes ─────────────────────────────────────────────────────

@dataclass
class GatewayFrame:
    """A single WebSocket frame in OpenClaw protocol."""
    type: str                           # FrameType value
    id: str = ""                        # Correlation ID (for RPC)
    method: str = ""                    # RPC method name
    params: Dict[str, Any] = field(default_factory=dict)
    result: Any = None                  # RPC response result
    error: Optional[str] = None         # Error message
    event: str = ""                     # Broadcast event name
    data: Dict[str, Any] = field(default_factory=dict)  # Broadcast payload
    timestamp: str = ""

    def to_json(self) -> str:
        d = {"type": self.type, "v": PROTOCOL_VERSION}
        if self.id:
            d["id"] = self.id
        if self.method:
            d["method"] = self.method
        if self.params:
            d["params"] = self.params
        if self.result is not None:
            d["result"] = self.result
        if self.error:
            d["error"] = self.error
        if self.event:
            d["event"] = self.event
        if self.data:
            d["data"] = self.data
        d["ts"] = self.timestamp or datetime.now(timezone.utc).isoformat()
        return json.dumps(d)

    @classmethod
    def from_json(cls, raw: str) -> 'GatewayFrame':
        d = json.loads(raw)
        return cls(
            type=d.get("type", ""),
            id=d.get("id", ""),
            method=d.get("method", ""),
            params=d.get("params", {}),
            result=d.get("result"),
            error=d.get("error"),
            event=d.get("event", ""),
            data=d.get("data", {}),
            timestamp=d.get("ts", ""),
        )


@dataclass
class IncomingMessage:
    """A message received from a messaging platform via OpenClaw."""
    channel: str          # "whatsapp", "telegram", "slack", "discord", etc.
    sender: str           # User identifier
    sender_name: str      # Display name
    text: str             # Message content
    chat_id: str = ""     # Conversation/group ID
    reply_to: str = ""    # Message ID to reply to (for threading)
    timestamp: str = ""
    raw: Dict = field(default_factory=dict)


# ── Gateway Client ───────────────────────────────────────────────────

class OpenClawGateway:
    """
    Async WebSocket client that connects to an OpenClaw gateway.

    Usage:
        gw = OpenClawGateway(token="your_device_token")

        # Register message handler
        gw.on_message(my_handler)

        # Connect and run
        await gw.connect()

        # Send a message through a channel
        await gw.send_message("whatsapp", "+1234567890", "BTC is at $62,450!")

        # Push a finance alert to all channels
        await gw.broadcast_alert({...})
    """

    HEARTBEAT_INTERVAL = 30  # seconds
    RECONNECT_BASE_DELAY = 1  # seconds
    RECONNECT_MAX_DELAY = 60  # seconds
    RECONNECT_MAX_ATTEMPTS = 0  # 0 = infinite

    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
        skill_name: str = "neomind-finance",
    ):
        self.url = url or os.getenv("OPENCLAW_GATEWAY_URL", OPENCLAW_DEFAULT_URL)
        self.token = token or os.getenv("OPENCLAW_DEVICE_TOKEN", "")
        self.skill_name = skill_name
        self._ws = None
        self._running = False
        self._connected = False
        self._pending_rpcs: Dict[str, asyncio.Future] = {}
        self._message_handlers: List[Callable[[IncomingMessage], Awaitable[Optional[str]]]] = []
        self._broadcast_handlers: Dict[str, List[Callable]] = {}
        self._reconnect_attempt = 0

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    # ── Handler Registration ─────────────────────────────────────────

    def on_message(self, handler: Callable[[IncomingMessage], Awaitable[Optional[str]]]):
        """Register a handler for incoming messages.

        Handler receives IncomingMessage, returns Optional[str] reply text.
        If handler returns a string, it's sent as a reply to the same channel.
        """
        self._message_handlers.append(handler)

    def on_broadcast(self, event: str, handler: Callable):
        """Register a handler for a specific broadcast event type."""
        self._broadcast_handlers.setdefault(event, []).append(handler)

    # ── Connection Lifecycle ─────────────────────────────────────────

    async def connect(self):
        """Connect to the OpenClaw gateway with auto-reconnect."""
        if not HAS_WEBSOCKETS:
            logger.error("websockets not installed. Run: pip install websockets")
            return

        self._running = True
        while self._running:
            try:
                await self._connect_once()
            except Exception as e:
                if not self._running:
                    break
                logger.warning(f"Gateway connection lost: {e}")
                self._connected = False

                # Exponential backoff
                delay = min(
                    self.RECONNECT_BASE_DELAY * (2 ** self._reconnect_attempt),
                    self.RECONNECT_MAX_DELAY,
                )
                self._reconnect_attempt += 1

                if self.RECONNECT_MAX_ATTEMPTS and self._reconnect_attempt > self.RECONNECT_MAX_ATTEMPTS:
                    logger.error(f"Max reconnect attempts ({self.RECONNECT_MAX_ATTEMPTS}) exceeded")
                    break

                logger.info(f"Reconnecting in {delay}s (attempt {self._reconnect_attempt})...")
                await asyncio.sleep(delay)

    async def _connect_once(self):
        """Single connection attempt."""
        logger.info(f"Connecting to OpenClaw gateway at {self.url}")

        async with websockets.connect(self.url) as ws:
            self._ws = ws
            self._reconnect_attempt = 0

            # Authenticate
            if self.token:
                await self._authenticate(ws)

            # Register as skill provider
            await self._register_skill(ws)

            self._connected = True
            logger.info("Connected to OpenClaw gateway")

            # Run concurrent tasks: receive loop + heartbeat
            await asyncio.gather(
                self._receive_loop(ws),
                self._heartbeat_loop(ws),
            )

    async def _authenticate(self, ws):
        """Send auth frame with device token."""
        frame = GatewayFrame(
            type=FrameType.AUTH,
            id=self._gen_id(),
            params={
                "token": self.token,
                "client": "neomind-finance",
                "protocol_version": PROTOCOL_VERSION,
            },
        )
        await ws.send(frame.to_json())

        # Wait for auth result
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            response = GatewayFrame.from_json(raw)
            if response.error:
                raise ConnectionError(f"Auth failed: {response.error}")
            logger.info("Authenticated with OpenClaw gateway")
        except asyncio.TimeoutError:
            raise ConnectionError("Auth timeout — is OpenClaw gateway running?")

    async def _register_skill(self, ws):
        """Register NeoMind finance as a skill provider."""
        result = await self._rpc(ws, "skills.register", {
            "name": self.skill_name,
            "version": "1.0.0",
            "description": "Personal Finance & Investment Intelligence",
            "commands": [
                {"name": "stock", "description": "Stock price and analysis", "args": "<symbol>"},
                {"name": "crypto", "description": "Crypto price and trends", "args": "<symbol>"},
                {"name": "news", "description": "Multi-source financial news", "args": "[query]"},
                {"name": "digest", "description": "Daily market digest", "args": ""},
                {"name": "compute", "description": "Financial math", "args": "<expression>"},
                {"name": "portfolio", "description": "Portfolio overview", "args": ""},
                {"name": "predict", "description": "Log prediction", "args": "<symbol> <direction> <confidence>"},
                {"name": "alert", "description": "Set price alert", "args": "<symbol> <condition> <price>"},
                {"name": "chart", "description": "Generate financial chart", "args": "<type> <data>"},
                {"name": "risk", "description": "Risk assessment", "args": "[symbol]"},
                {"name": "compare", "description": "Compare assets", "args": "<sym1> <sym2>"},
                {"name": "watchlist", "description": "Manage watchlist", "args": "[add|remove] [symbol]"},
                {"name": "sources", "description": "Source trust scores", "args": ""},
                {"name": "calendar", "description": "Financial events", "args": ""},
                {"name": "memory", "description": "Query memory", "args": "<query>"},
                {"name": "sync", "description": "Sync status", "args": ""},
            ],
            "capabilities": ["finance", "news", "crypto", "analysis", "alerts"],
        })
        logger.info(f"Registered skill: {self.skill_name}")

    async def disconnect(self):
        """Gracefully disconnect."""
        self._running = False
        self._connected = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    # ── Message Receive Loop ─────────────────────────────────────────

    async def _receive_loop(self, ws):
        """Main receive loop — dispatches frames to appropriate handlers."""
        async for raw in ws:
            try:
                frame = GatewayFrame.from_json(raw)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Invalid frame: {e}")
                continue

            if frame.type == FrameType.RPC_RESPONSE:
                # Resolve pending RPC future
                future = self._pending_rpcs.pop(frame.id, None)
                if future and not future.done():
                    if frame.error:
                        future.set_exception(RuntimeError(frame.error))
                    else:
                        future.set_result(frame.result)

            elif frame.type == FrameType.BROADCAST:
                await self._handle_broadcast(frame)

            elif frame.type == FrameType.HEARTBEAT:
                # Respond to server heartbeat
                pong = GatewayFrame(type=FrameType.HEARTBEAT, id=frame.id)
                await ws.send(pong.to_json())

    async def _handle_broadcast(self, frame: GatewayFrame):
        """Handle broadcast events from the gateway."""
        event = frame.event

        # Incoming message from a messaging platform
        if event == BroadcastEvent.MESSAGE_RECEIVED:
            msg = IncomingMessage(
                channel=frame.data.get("channel", "unknown"),
                sender=frame.data.get("sender", ""),
                sender_name=frame.data.get("sender_name", ""),
                text=frame.data.get("text", ""),
                chat_id=frame.data.get("chat_id", ""),
                reply_to=frame.data.get("message_id", ""),
                timestamp=frame.timestamp,
                raw=frame.data,
            )

            # Dispatch to registered message handlers
            for handler in self._message_handlers:
                try:
                    reply = await handler(msg)
                    if reply:
                        await self.send_message(
                            channel=msg.channel,
                            recipient=msg.chat_id or msg.sender,
                            text=reply,
                            reply_to=msg.reply_to,
                        )
                except Exception as e:
                    logger.error(f"Message handler error: {e}")

        # Skill invocation from another skill or user
        elif event == BroadcastEvent.SKILL_INVOKED:
            # Will be handled by skill adapter
            pass

        # Dispatch to generic broadcast handlers
        handlers = self._broadcast_handlers.get(event, [])
        for handler in handlers:
            try:
                await handler(frame.data)
            except Exception as e:
                logger.error(f"Broadcast handler error for {event}: {e}")

    # ── Heartbeat ────────────────────────────────────────────────────

    async def _heartbeat_loop(self, ws):
        """Send periodic heartbeats to keep connection alive."""
        while self._running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            try:
                frame = GatewayFrame(
                    type=FrameType.HEARTBEAT,
                    id=self._gen_id(),
                )
                await ws.send(frame.to_json())
            except Exception:
                break  # Connection lost — reconnect loop will handle it

    # ── RPC Methods ──────────────────────────────────────────────────

    async def _rpc(self, ws, method: str, params: Dict = None, timeout: float = 30) -> Any:
        """Send an RPC call and wait for the response."""
        rpc_id = self._gen_id()
        future = asyncio.get_event_loop().create_future()
        self._pending_rpcs[rpc_id] = future

        frame = GatewayFrame(
            type=FrameType.RPC_CALL,
            id=rpc_id,
            method=method,
            params=params or {},
        )
        await ws.send(frame.to_json())

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_rpcs.pop(rpc_id, None)
            raise TimeoutError(f"RPC {method} timed out after {timeout}s")

    async def send_message(
        self,
        channel: str,
        recipient: str,
        text: str,
        reply_to: str = "",
        format: str = "markdown",
    ):
        """Send a message through an OpenClaw messaging channel.

        Args:
            channel: "whatsapp", "telegram", "slack", "discord", etc.
            recipient: Chat ID, phone number, or channel name
            text: Message text
            reply_to: Optional message ID to reply to
            format: "text", "markdown", or "html"
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OpenClaw gateway")

        await self._rpc(self._ws, "messages.send", {
            "channel": channel,
            "recipient": recipient,
            "text": text,
            "reply_to": reply_to,
            "format": format,
            "skill": self.skill_name,
        })

    async def broadcast_alert(self, alert: Dict, channels: Optional[List[str]] = None):
        """Push a finance alert to all connected channels.

        Args:
            alert: {symbol, price, condition, message, urgency}
            channels: Specific channels to target. None = all connected.
        """
        if not self.is_connected:
            logger.warning("Cannot broadcast alert — not connected to gateway")
            return

        text = self._format_alert(alert)

        await self._rpc(self._ws, "messages.broadcast", {
            "text": text,
            "channels": channels,  # None = all
            "skill": self.skill_name,
            "priority": alert.get("urgency", "normal"),
        })

    async def push_digest(self, digest_html: str, summary: str, channels: Optional[List[str]] = None):
        """Push a daily digest through OpenClaw channels.

        Sends a short summary text to mobile channels,
        with an optional HTML attachment for rich display.
        """
        if not self.is_connected:
            return

        await self._rpc(self._ws, "messages.broadcast", {
            "text": summary,
            "attachments": [
                {
                    "type": "html",
                    "content": digest_html,
                    "filename": f"digest_{datetime.now().strftime('%Y%m%d')}.html",
                }
            ],
            "channels": channels,
            "skill": self.skill_name,
        })

    # ── Formatting Helpers ───────────────────────────────────────────

    @staticmethod
    def _format_alert(alert: Dict) -> str:
        """Format a finance alert for messaging platforms."""
        symbol = alert.get("symbol", "?")
        price = alert.get("price", "?")
        condition = alert.get("condition", "")
        message = alert.get("message", "")

        urgency = alert.get("urgency", "normal")
        icon = {"critical": "🚨", "high": "⚠️", "normal": "📊", "low": "ℹ️"}.get(urgency, "📊")

        parts = [f"{icon} **{symbol}** — ${price}"]
        if condition:
            parts.append(f"Trigger: {condition}")
        if message:
            parts.append(message)
        return "\n".join(parts)

    @staticmethod
    def _gen_id() -> str:
        return uuid.uuid4().hex[:12]

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> str:
        lines = ["OpenClaw Gateway", "=" * 50]
        lines.append(f"  URL: {self.url}")
        lines.append(f"  Connected: {'✅ Yes' if self.is_connected else '❌ No'}")
        lines.append(f"  Skill: {self.skill_name}")
        lines.append(f"  Auth: {'✅ Token set' if self.token else '⚠️ No token (set OPENCLAW_DEVICE_TOKEN)'}")
        lines.append(f"  Reconnect attempts: {self._reconnect_attempt}")
        lines.append(f"  Pending RPCs: {len(self._pending_rpcs)}")
        lines.append(f"  Message handlers: {len(self._message_handlers)}")
        return "\n".join(lines)
