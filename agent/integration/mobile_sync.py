# agent/finance/mobile_sync.py
"""
Mobile Sync Gateway — OpenClaw-powered sync for cross-device access.

Transport Layer: OpenClaw Gateway (WebSocket protocol v3)
- Connects to running OpenClaw instance for messaging (WhatsApp, Telegram, Slack, etc.)
- Falls back to standalone WebSocket server if OpenClaw not available

Architecture:
- Single source of truth: NeoMind's encrypted SQLite
- Bidirectional memory bridge: SQLite ↔ OpenClaw Markdown
- Push: price alerts, digest summaries, urgent news via OpenClaw channels
- Pull: query from any messaging platform
- Lane-aware FIFO queue prevents alert spam

Security:
- Device pairing with 6-digit code (standalone mode)
- OpenClaw token auth (gateway mode)
- Sensitive fields never exported to Markdown
"""

import os
import json
import hashlib
import secrets
import time
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

logger = logging.getLogger("neomind.sync")


# ── Data Classes ─────────────────────────────────────────────────────

@dataclass
class PairedDevice:
    """A paired mobile device."""
    device_id: str
    name: str = ""
    token: str = ""
    paired_at: str = ""
    last_seen: str = ""
    is_active: bool = True


@dataclass
class SyncMessage:
    """A message to/from a mobile device."""
    type: str          # "alert", "digest", "quote", "query", "response"
    payload: Dict = field(default_factory=dict)
    timestamp: str = ""
    device_id: str = ""


class LaneAwareFIFO:
    """
    Lane-aware FIFO queue (from OpenClaw patterns).
    Prevents alert spam by limiting concurrency per lane.
    """

    def __init__(self, concurrency: Optional[Dict[str, int]] = None):
        self.concurrency = concurrency or {"alerts": 1, "digest": 1, "chat": 4}
        self.queues: Dict[str, List[SyncMessage]] = {lane: [] for lane in self.concurrency}
        self.active: Dict[str, int] = {lane: 0 for lane in self.concurrency}

    def enqueue(self, lane: str, message: SyncMessage) -> bool:
        if lane not in self.queues:
            self.queues[lane] = []
            self.concurrency[lane] = 1
            self.active[lane] = 0
        self.queues[lane].append(message)
        return True

    def dequeue(self, lane: str) -> Optional[SyncMessage]:
        if lane not in self.queues:
            return None
        if self.active.get(lane, 0) >= self.concurrency.get(lane, 1):
            return None
        if not self.queues[lane]:
            return None
        self.active[lane] = self.active.get(lane, 0) + 1
        return self.queues[lane].pop(0)

    def complete(self, lane: str):
        self.active[lane] = max(0, self.active.get(lane, 0) - 1)


# ── Main Gateway ─────────────────────────────────────────────────────

class MobileSyncGateway:
    """
    Unified sync gateway with OpenClaw integration.

    Mode 1 — OpenClaw Gateway (preferred):
      Connects to a running OpenClaw instance. Messages flow through
      WhatsApp/Telegram/Slack/Discord. Memory bridges bidirectionally.

    Mode 2 — Standalone WebSocket (fallback):
      Runs its own WebSocket server on local network. Mobile apps connect directly.

    The mode is auto-detected: if OPENCLAW_DEVICE_TOKEN is set or OpenClaw
    is running on the default port, we use gateway mode.
    """

    DEFAULT_PORT = 18790
    PAIRING_CODE_LENGTH = 6
    TOKEN_LENGTH = 64

    def __init__(self, memory_store=None, port: Optional[int] = None):
        self.memory = memory_store
        self.port = port or int(os.getenv("NEOMIND_SYNC_PORT", str(self.DEFAULT_PORT)))
        self.paired_devices: Dict[str, PairedDevice] = {}
        self.event_queue = LaneAwareFIFO()
        self._running = False
        self._config_path = Path("~/.neomind/finance/sync_config.json").expanduser()
        self._load_config()

        # OpenClaw integration (lazy-initialized)
        self._openclaw_gateway = None
        self._openclaw_skill = None
        self._memory_bridge = None
        self._mode = "standalone"  # "openclaw" or "standalone"

    # ── OpenClaw Integration ─────────────────────────────────────────

    def init_openclaw(self, components: Dict[str, Any] = None) -> bool:
        """Initialize OpenClaw integration if available.

        Args:
            components: Dict from get_finance_components() for skill routing.

        Returns True if OpenClaw mode activated, False if falling back to standalone.
        """
        token = os.getenv("OPENCLAW_DEVICE_TOKEN", "")
        gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "")

        # OpenClaw mode activates if EITHER token or gateway_url is set.
        # Token can be empty — OpenClaw may run without auth (common in local Docker).
        if not token and not gateway_url:
            logger.info("No OpenClaw config — using standalone mode")
            self._mode = "standalone"
            return False

        try:
            from .openclaw_gateway import OpenClawGateway
            self._openclaw_gateway = OpenClawGateway(
                url=gateway_url or None,
                token=token or None,
            )

            # Set up skill adapter if components provided
            if components:
                from .openclaw_skill import OpenClawFinanceSkill
                self._openclaw_skill = OpenClawFinanceSkill(
                    components=components,
                    gateway=self._openclaw_gateway,
                )

            # Set up memory bridge
            from agent.services.memory_bridge import MemoryBridge
            self._memory_bridge = MemoryBridge(memory_store=self.memory)

            self._mode = "openclaw"
            logger.info("OpenClaw mode activated")
            return True

        except ImportError as e:
            logger.warning(f"OpenClaw modules not available: {e}")
            self._mode = "standalone"
            return False

    @property
    def openclaw_gateway(self):
        return self._openclaw_gateway

    @property
    def memory_bridge(self):
        return self._memory_bridge

    # ── Device Management (shared between modes) ─────────────────────

    def _load_config(self):
        try:
            if self._config_path.exists():
                data = json.loads(self._config_path.read_text())
                for dev_data in data.get("devices", []):
                    dev = PairedDevice(**dev_data)
                    self.paired_devices[dev.device_id] = dev
        except Exception:
            pass

    def _save_config(self):
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "devices": [
                    {
                        "device_id": d.device_id,
                        "name": d.name,
                        "token": d.token,
                        "paired_at": d.paired_at,
                        "last_seen": d.last_seen,
                        "is_active": d.is_active,
                    }
                    for d in self.paired_devices.values()
                ],
                "port": self.port,
                "mode": self._mode,
            }
            self._config_path.write_text(json.dumps(data, indent=2))
            os.chmod(self._config_path, 0o600)
        except Exception:
            pass

    def generate_pairing_code(self) -> str:
        return ''.join([str(secrets.randbelow(10)) for _ in range(self.PAIRING_CODE_LENGTH)])

    def pair_device(self, code: str, device_name: str = "") -> Optional[PairedDevice]:
        if not code or len(code) != self.PAIRING_CODE_LENGTH:
            return None

        device_id = hashlib.sha256(f"{code}{time.time()}".encode()).hexdigest()[:16]
        token = secrets.token_urlsafe(self.TOKEN_LENGTH)

        device = PairedDevice(
            device_id=device_id,
            name=device_name or f"Device-{device_id[:6]}",
            token=token,
            paired_at=datetime.now(timezone.utc).isoformat(),
            last_seen=datetime.now(timezone.utc).isoformat(),
        )

        self.paired_devices[device_id] = device
        self._save_config()
        return device

    def revoke_device(self, device_id: str) -> bool:
        if device_id in self.paired_devices:
            self.paired_devices[device_id].is_active = False
            self._save_config()
            return True
        return False

    def authenticate(self, token: str) -> Optional[PairedDevice]:
        for device in self.paired_devices.values():
            if device.token == token and device.is_active:
                device.last_seen = datetime.now(timezone.utc).isoformat()
                return device
        return None

    # ── Push Methods (route through OpenClaw or local queue) ─────────

    def push_alert(self, alert: Dict):
        """Push a price alert through the active transport."""
        msg = SyncMessage(
            type="alert",
            payload=alert,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.event_queue.enqueue("alerts", msg)

        # Also push through OpenClaw if connected
        if self._openclaw_gateway and self._openclaw_gateway.is_connected:
            asyncio.ensure_future(
                self._openclaw_gateway.broadcast_alert(alert)
            )

    def push_digest(self, digest: Dict):
        """Push a digest summary through the active transport."""
        msg = SyncMessage(
            type="digest",
            payload=digest,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.event_queue.enqueue("digest", msg)

    def sync_memory(self) -> Dict[str, int]:
        """Trigger bidirectional memory sync with OpenClaw.

        Returns {"exported": N, "imported": M, "conflicts": K}.
        """
        if self._memory_bridge:
            return self._memory_bridge.sync()
        return {"exported": 0, "imported": 0, "conflicts": 0}

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self):
        """Start the sync gateway in the appropriate mode."""
        self._running = True

        if self._mode == "openclaw" and self._openclaw_gateway:
            logger.info("Starting in OpenClaw gateway mode")
            print(f"📱 Sync: OpenClaw mode → {self._openclaw_gateway.url}")

            # Run gateway connection + periodic memory sync
            await asyncio.gather(
                self._openclaw_gateway.connect(),
                self._periodic_memory_sync(),
            )

        else:
            # Standalone mode
            if not HAS_WEBSOCKETS:
                print("⚠️  websockets not installed. Mobile sync unavailable.")
                print("   Install with: pip install websockets")
                print("   Or set OPENCLAW_DEVICE_TOKEN to use OpenClaw mode.")
                return

            logger.info(f"Starting in standalone mode on port {self.port}")
            print(f"📱 Sync: Standalone mode → ws://0.0.0.0:{self.port}")
            print("   Tip: Set OPENCLAW_DEVICE_TOKEN to enable OpenClaw integration")

            # Start standalone WebSocket server
            async with websockets.serve(self._standalone_handler, "0.0.0.0", self.port):
                await asyncio.Future()  # run forever

    async def _periodic_memory_sync(self):
        """Periodically sync memory with OpenClaw."""
        while self._running:
            try:
                if self._memory_bridge:
                    result = self._memory_bridge.sync()
                    if result["exported"] or result["imported"]:
                        logger.info(
                            f"Memory sync: exported={result['exported']}, "
                            f"imported={result['imported']}"
                        )
            except Exception as e:
                logger.warning(f"Memory sync error: {e}")

            await asyncio.sleep(300)  # sync every 5 minutes

    async def _standalone_handler(self, websocket, path):
        """Handle WebSocket connections in standalone mode."""
        # Authenticate
        try:
            auth_msg = await asyncio.wait_for(websocket.recv(), timeout=10)
            auth_data = json.loads(auth_msg)
            device = self.authenticate(auth_data.get("token", ""))
            if not device:
                await websocket.send(json.dumps({"error": "auth_failed"}))
                return
            await websocket.send(json.dumps({"status": "authenticated", "device": device.name}))
        except Exception:
            return

        # Message loop
        try:
            async for raw_msg in websocket:
                try:
                    data = json.loads(raw_msg)
                    msg_type = data.get("type", "")

                    if msg_type == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))

                    elif msg_type == "query":
                        # Route to skill handler if available
                        if self._openclaw_skill:
                            from .openclaw_gateway import IncomingMessage
                            incoming = IncomingMessage(
                                channel="standalone",
                                sender=device.device_id,
                                sender_name=device.name,
                                text=data.get("text", ""),
                            )
                            reply = await self._openclaw_skill.handle_incoming(incoming)
                            await websocket.send(json.dumps({
                                "type": "response",
                                "text": reply or "No response.",
                            }))

                    elif msg_type == "get_queue":
                        # Send pending messages
                        pending = []
                        for lane in self.event_queue.queues:
                            msg = self.event_queue.dequeue(lane)
                            while msg:
                                pending.append({
                                    "type": msg.type,
                                    "payload": msg.payload,
                                    "timestamp": msg.timestamp,
                                })
                                self.event_queue.complete(lane)
                                msg = self.event_queue.dequeue(lane)

                        await websocket.send(json.dumps({
                            "type": "queue",
                            "messages": pending,
                        }))

                except json.JSONDecodeError:
                    pass
        except websockets.ConnectionClosed:
            pass

    async def stop(self):
        """Stop the sync gateway."""
        self._running = False
        if self._openclaw_gateway:
            await self._openclaw_gateway.disconnect()

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> str:
        lines = ["Mobile Sync Gateway", "=" * 50]
        lines.append(f"  Mode: {self._mode}")

        if self._mode == "openclaw":
            if self._openclaw_gateway:
                lines.append(f"  OpenClaw URL: {self._openclaw_gateway.url}")
                lines.append(f"  Connected: {'✅' if self._openclaw_gateway.is_connected else '❌'}")
            if self._memory_bridge:
                lines.append(f"  Memory Bridge: ✅ Active")
        else:
            lines.append(f"  Port: {self.port}")
            lines.append(f"  WebSocket: {'✅' if HAS_WEBSOCKETS else '❌ Not installed'}")

        lines.append(f"  Status: {'🟢 Running' if self._running else '🔴 Stopped'}")

        active = [d for d in self.paired_devices.values() if d.is_active]
        lines.append(f"\n  Paired Devices: {len(active)}")
        for device in active:
            lines.append(f"    📱 {device.name} (last seen: {device.last_seen[:19]})")

        if not active and self._mode == "standalone":
            lines.append("    No devices paired. Use /sync pair to add a device.")
        elif not active and self._mode == "openclaw":
            lines.append("    Messages routed through OpenClaw channels.")

        # Queue status
        total_queued = sum(len(q) for q in self.event_queue.queues.values())
        if total_queued > 0:
            lines.append(f"\n  Queued messages: {total_queued}")

        return "\n".join(lines)
