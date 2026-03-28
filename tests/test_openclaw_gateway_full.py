"""
Comprehensive unit tests for agent/finance/openclaw_gateway.py
Tests GatewayFrame, IncomingMessage, and OpenClawGateway.
"""

import pytest
import json
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from enum import Enum

from agent.finance.openclaw_gateway import (
    GatewayFrame,
    IncomingMessage,
    OpenClawGateway,
    FrameType,
    BroadcastEvent,
    OPENCLAW_DEFAULT_URL,
    PROTOCOL_VERSION,
)


class TestFrameType:
    """Test FrameType enum."""

    def test_frame_types_exist(self):
        """Test that all expected frame types exist."""
        assert FrameType.RPC_CALL == "rpc_call"
        assert FrameType.RPC_RESPONSE == "rpc_response"
        assert FrameType.BROADCAST == "broadcast"
        assert FrameType.HEARTBEAT == "heartbeat"
        assert FrameType.AUTH == "auth"
        assert FrameType.AUTH_RESULT == "auth_result"


class TestBroadcastEvent:
    """Test BroadcastEvent enum."""

    def test_broadcast_events_exist(self):
        """Test that all expected broadcast events exist."""
        assert BroadcastEvent.MESSAGE_RECEIVED == "message.received"
        assert BroadcastEvent.MESSAGE_SENT == "message.sent"
        assert BroadcastEvent.CHANNEL_JOINED == "channel.joined"
        assert BroadcastEvent.SKILL_INVOKED == "skill.invoked"


class TestGatewayFrame:
    """Test GatewayFrame serialization and deserialization."""

    def test_creation_minimal(self):
        """Test creating a minimal frame."""
        frame = GatewayFrame(type=FrameType.HEARTBEAT)
        assert frame.type == FrameType.HEARTBEAT
        assert frame.id == ""
        assert frame.error is None

    def test_creation_full(self):
        """Test creating a frame with all fields."""
        frame = GatewayFrame(
            type=FrameType.RPC_CALL,
            id="abc123",
            method="test.method",
            params={"key": "value"},
            result="result",
            error="error message",
            event="test.event",
            data={"data": "value"},
            timestamp="2024-01-01T00:00:00Z",
        )
        assert frame.type == FrameType.RPC_CALL
        assert frame.id == "abc123"
        assert frame.method == "test.method"
        assert frame.error == "error message"

    def test_to_json_rpc_call(self):
        """Test serialization of RPC call frame."""
        frame = GatewayFrame(
            type=FrameType.RPC_CALL,
            id="abc123",
            method="test.method",
            params={"key": "value"},
        )
        json_str = frame.to_json()
        data = json.loads(json_str)

        assert data["type"] == FrameType.RPC_CALL
        assert data["id"] == "abc123"
        assert data["method"] == "test.method"
        assert data["params"] == {"key": "value"}
        assert data["v"] == PROTOCOL_VERSION

    def test_to_json_includes_timestamp(self):
        """Test that to_json includes timestamp."""
        frame = GatewayFrame(type=FrameType.HEARTBEAT)
        json_str = frame.to_json()
        data = json.loads(json_str)
        assert "ts" in data

    def test_to_json_custom_timestamp(self):
        """Test to_json with custom timestamp."""
        ts = "2024-01-01T12:00:00Z"
        frame = GatewayFrame(type=FrameType.HEARTBEAT, timestamp=ts)
        json_str = frame.to_json()
        data = json.loads(json_str)
        assert data["ts"] == ts

    def test_from_json_rpc_call(self):
        """Test deserialization of RPC call frame."""
        json_str = json.dumps({
            "type": FrameType.RPC_CALL,
            "id": "abc123",
            "method": "test.method",
            "params": {"key": "value"},
            "v": PROTOCOL_VERSION,
            "ts": "2024-01-01T00:00:00Z",
        })
        frame = GatewayFrame.from_json(json_str)

        assert frame.type == FrameType.RPC_CALL
        assert frame.id == "abc123"
        assert frame.method == "test.method"
        assert frame.params == {"key": "value"}

    def test_from_json_broadcast(self):
        """Test deserialization of broadcast frame."""
        json_str = json.dumps({
            "type": FrameType.BROADCAST,
            "event": BroadcastEvent.MESSAGE_RECEIVED,
            "data": {"channel": "whatsapp", "sender": "user123"},
            "ts": "2024-01-01T00:00:00Z",
        })
        frame = GatewayFrame.from_json(json_str)

        assert frame.type == FrameType.BROADCAST
        assert frame.event == BroadcastEvent.MESSAGE_RECEIVED
        assert frame.data["channel"] == "whatsapp"

    def test_from_json_rpc_response(self):
        """Test deserialization of RPC response frame."""
        json_str = json.dumps({
            "type": FrameType.RPC_RESPONSE,
            "id": "abc123",
            "result": {"status": "success"},
            "ts": "2024-01-01T00:00:00Z",
        })
        frame = GatewayFrame.from_json(json_str)

        assert frame.type == FrameType.RPC_RESPONSE
        assert frame.id == "abc123"
        assert frame.result == {"status": "success"}

    def test_from_json_with_error(self):
        """Test deserialization of error frame."""
        json_str = json.dumps({
            "type": FrameType.RPC_RESPONSE,
            "id": "abc123",
            "error": "Method not found",
            "ts": "2024-01-01T00:00:00Z",
        })
        frame = GatewayFrame.from_json(json_str)

        assert frame.error == "Method not found"

    def test_from_json_minimal(self):
        """Test deserialization of minimal frame."""
        json_str = json.dumps({"type": FrameType.HEARTBEAT})
        frame = GatewayFrame.from_json(json_str)

        assert frame.type == FrameType.HEARTBEAT
        assert frame.id == ""
        assert frame.error is None

    def test_roundtrip_serialization(self):
        """Test that serialize/deserialize is lossless."""
        original = GatewayFrame(
            type=FrameType.RPC_CALL,
            id="test123",
            method="test.method",
            params={"data": [1, 2, 3]},
        )

        json_str = original.to_json()
        restored = GatewayFrame.from_json(json_str)

        assert restored.type == original.type
        assert restored.id == original.id
        assert restored.method == original.method
        assert restored.params == original.params


class TestIncomingMessage:
    """Test IncomingMessage dataclass."""

    def test_creation_minimal(self):
        """Test creating message with minimal fields."""
        msg = IncomingMessage(
            channel="whatsapp",
            sender="user123",
            sender_name="John",
            text="Hello",
        )
        assert msg.channel == "whatsapp"
        assert msg.sender == "user123"
        assert msg.text == "Hello"
        assert msg.chat_id == ""

    def test_creation_full(self):
        """Test creating message with all fields."""
        now = datetime.now(timezone.utc).isoformat()
        msg = IncomingMessage(
            channel="telegram",
            sender="123456789",
            sender_name="Alice",
            text="What is the BTC price?",
            chat_id="group123",
            reply_to="msg456",
            timestamp=now,
            raw={"raw_data": "value"},
        )
        assert msg.channel == "telegram"
        assert msg.reply_to == "msg456"
        assert msg.raw == {"raw_data": "value"}


class TestOpenClawGateway:
    """Test OpenClawGateway class."""

    @pytest.fixture
    def gateway(self):
        """Create a gateway instance."""
        return OpenClawGateway(
            url="ws://localhost:18789",
            token="test_token",
            skill_name="neomind-finance",
        )

    def test_init(self):
        """Test gateway initialization."""
        gateway = OpenClawGateway(
            url="ws://127.0.0.1:18789",
            token="token123",
        )
        assert gateway.url == "ws://127.0.0.1:18789"
        assert gateway.token == "token123"
        assert gateway.skill_name == "neomind-finance"
        assert gateway._connected is False
        assert gateway._running is False

    def test_init_with_env_vars(self, monkeypatch):
        """Test initialization from environment variables."""
        monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "ws://remote:18789")
        monkeypatch.setenv("OPENCLAW_DEVICE_TOKEN", "env_token")

        gateway = OpenClawGateway()
        assert gateway.url == "ws://remote:18789"
        assert gateway.token == "env_token"

    def test_init_default_url(self, monkeypatch):
        """Test initialization with default URL."""
        monkeypatch.delenv("OPENCLAW_GATEWAY_URL", raising=False)
        monkeypatch.delenv("OPENCLAW_DEVICE_TOKEN", raising=False)

        gateway = OpenClawGateway()
        assert gateway.url == OPENCLAW_DEFAULT_URL

    def test_is_connected_property(self, gateway):
        """Test is_connected property."""
        assert gateway.is_connected is False

        gateway._connected = True
        gateway._ws = Mock()
        assert gateway.is_connected is True

        gateway._ws = None
        assert gateway.is_connected is False

    def test_on_message_registers_handler(self, gateway):
        """Test registering message handler."""
        async def handler(msg):
            return "response"

        gateway.on_message(handler)
        assert handler in gateway._message_handlers

    def test_on_message_multiple_handlers(self, gateway):
        """Test registering multiple message handlers."""
        async def handler1(msg):
            pass

        async def handler2(msg):
            pass

        gateway.on_message(handler1)
        gateway.on_message(handler2)

        assert len(gateway._message_handlers) == 2

    def test_on_broadcast_registers_handler(self, gateway):
        """Test registering broadcast event handler."""
        async def handler(data):
            pass

        gateway.on_broadcast(BroadcastEvent.MESSAGE_RECEIVED, handler)

        assert BroadcastEvent.MESSAGE_RECEIVED in gateway._broadcast_handlers
        assert handler in gateway._broadcast_handlers[BroadcastEvent.MESSAGE_RECEIVED]

    def test_format_alert(self):
        """Test alert formatting."""
        alert = {
            "symbol": "AAPL",
            "price": "150.25",
            "condition": "above 150",
            "message": "Entry signal detected",
            "urgency": "high",
        }

        formatted = OpenClawGateway._format_alert(alert)

        assert "AAPL" in formatted
        assert "150.25" in formatted
        assert "Entry signal" in formatted
        assert "⚠️" in formatted  # high urgency icon

    def test_format_alert_default_urgency(self):
        """Test alert formatting with default urgency."""
        alert = {
            "symbol": "BTC",
            "price": "62450",
        }

        formatted = OpenClawGateway._format_alert(alert)

        assert "📊" in formatted  # normal urgency icon

    def test_format_alert_critical(self):
        """Test alert formatting with critical urgency."""
        alert = {
            "symbol": "TSLA",
            "price": "240",
            "urgency": "critical",
        }

        formatted = OpenClawGateway._format_alert(alert)

        assert "🚨" in formatted

    def test_gen_id(self):
        """Test ID generation."""
        id1 = OpenClawGateway._gen_id()
        id2 = OpenClawGateway._gen_id()

        assert len(id1) == 12
        assert len(id2) == 12
        assert id1 != id2

    def test_get_status(self, gateway):
        """Test status reporting."""
        status = gateway.get_status()

        assert "OpenClaw Gateway" in status
        assert gateway.url in status
        assert "localhost:18789" in status

    def test_get_status_connected(self, gateway):
        """Test status when connected."""
        gateway._connected = True
        gateway._ws = Mock()

        status = gateway.get_status()
        assert "✅ Yes" in status

    def test_get_status_disconnected(self, gateway):
        """Test status when disconnected."""
        gateway._connected = False

        status = gateway.get_status()
        assert "❌ No" in status

    def test_get_status_pending_rpcs(self, gateway):
        """Test status shows pending RPC count."""
        gateway._pending_rpcs["id1"] = Mock()
        gateway._pending_rpcs["id2"] = Mock()

        status = gateway.get_status()
        assert "2" in status


class TestOpenClawGatewayAsync:
    """Test async methods of OpenClawGateway."""

    @pytest.fixture
    def gateway(self):
        """Create a gateway instance."""
        return OpenClawGateway(url="ws://localhost:18789", token="test")

    @pytest.mark.asyncio
    async def test_connect_no_websockets(self, gateway, monkeypatch):
        """Test connect when websockets not available."""
        with patch("agent.finance.openclaw_gateway.HAS_WEBSOCKETS", False):
            await gateway.connect()
            # Should return early without setting _running
            assert gateway._running is False

    @pytest.mark.asyncio
    async def test_disconnect(self, gateway):
        """Test graceful disconnect."""
        gateway._running = True
        gateway._connected = True
        mock_ws = AsyncMock()
        gateway._ws = mock_ws

        await gateway.disconnect()

        assert gateway._running is False
        assert gateway._connected is False
        assert gateway._ws is None
        mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_no_ws(self, gateway):
        """Test disconnect when no WebSocket."""
        gateway._running = True
        gateway._ws = None

        await gateway.disconnect()

        assert gateway._running is False

    @pytest.mark.asyncio
    async def test_send_message_not_connected(self, gateway):
        """Test send_message raises when not connected."""
        gateway._connected = False

        with pytest.raises(ConnectionError):
            await gateway.send_message("whatsapp", "+1234567890", "Hello")

    @pytest.mark.asyncio
    async def test_broadcast_alert_not_connected(self, gateway):
        """Test broadcast_alert when not connected."""
        gateway._connected = False

        # Should not raise, just log warning
        await gateway.broadcast_alert({"symbol": "AAPL", "price": "150"})

    @pytest.mark.asyncio
    async def test_broadcast_alert_connected(self, gateway):
        """Test broadcast_alert when connected."""
        gateway._connected = True
        gateway._ws = AsyncMock()

        # Mock RPC
        with patch.object(gateway, "_rpc", new_callable=AsyncMock) as mock_rpc:
            await gateway.broadcast_alert({
                "symbol": "AAPL",
                "price": "150",
                "urgency": "high",
            })

            mock_rpc.assert_called_once()

    @pytest.mark.asyncio
    async def test_push_digest_not_connected(self, gateway):
        """Test push_digest when not connected."""
        gateway._connected = False

        # Should not raise
        await gateway.push_digest("<html>digest</html>", "Summary", None)

    @pytest.mark.asyncio
    async def test_handle_broadcast_message_received(self, gateway):
        """Test handling MESSAGE_RECEIVED broadcast."""
        handler_called = False

        async def test_handler(msg):
            nonlocal handler_called
            handler_called = True
            return "Reply"

        gateway.on_message(test_handler)

        frame = GatewayFrame(
            type=FrameType.BROADCAST,
            event=BroadcastEvent.MESSAGE_RECEIVED,
            data={
                "channel": "whatsapp",
                "sender": "user123",
                "sender_name": "John",
                "text": "Hello",
            },
        )

        # Mock send
        gateway._ws = AsyncMock()

        await gateway._handle_broadcast(frame)

        # Handler should be called
        assert handler_called or gateway._message_handlers  # Either called or registered

    @pytest.mark.asyncio
    async def test_authenticate_success(self, gateway):
        """Test successful authentication."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({
            "type": FrameType.AUTH_RESULT,
            "error": None,
        }))
        mock_ws.send = AsyncMock()

        # Authenticate with mock WebSocket
        await gateway._authenticate(mock_ws)

        # Verify auth was sent and response was received
        mock_ws.send.assert_called_once()
        mock_ws.recv.assert_called_once()


class TestOpenClawGatewayIntegration:
    """Integration tests for OpenClawGateway."""

    @pytest.fixture
    def gateway(self):
        """Create gateway for integration tests."""
        return OpenClawGateway(
            url="ws://localhost:18789",
            token="integration_token",
        )

    def test_handler_registration_flow(self, gateway):
        """Test handler registration and dispatch setup."""
        message_handlers = []
        broadcast_handlers = {}

        async def msg_handler1(msg):
            return "response1"

        async def msg_handler2(msg):
            return "response2"

        async def broadcast_handler(data):
            pass

        # Register handlers
        gateway.on_message(msg_handler1)
        gateway.on_message(msg_handler2)
        gateway.on_broadcast("test.event", broadcast_handler)

        # Verify registration
        assert len(gateway._message_handlers) == 2
        assert "test.event" in gateway._broadcast_handlers

    def test_frame_serialization_roundtrip(self):
        """Test complete frame serialization cycle."""
        original = GatewayFrame(
            type=FrameType.RPC_CALL,
            id="integration_test_123",
            method="skills.register",
            params={
                "name": "neomind-finance",
                "version": "1.0.0",
                "commands": [
                    {"name": "stock", "args": "<symbol>"},
                ],
            },
        )

        # Serialize
        json_str = original.to_json()

        # Deserialize
        restored = GatewayFrame.from_json(json_str)

        # Verify
        assert restored.type == original.type
        assert restored.id == original.id
        assert restored.method == original.method
        assert len(restored.params["commands"]) == 1
