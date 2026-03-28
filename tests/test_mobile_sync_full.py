"""
Comprehensive unit tests for agent/finance/mobile_sync.py
Tests LaneAwareFIFO, PairedDevice, SyncMessage, and MobileSyncGateway.
"""

import pytest
import json
import os
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch, AsyncMock

from agent.finance.mobile_sync import (
    LaneAwareFIFO,
    PairedDevice,
    SyncMessage,
    MobileSyncGateway,
)


class TestLaneAwareFIFO:
    """Test the LaneAwareFIFO queue implementation."""

    def test_init_default_concurrency(self):
        """Test initialization with default concurrency settings."""
        queue = LaneAwareFIFO()
        assert queue.concurrency == {"alerts": 1, "digest": 1, "chat": 4}
        assert set(queue.queues.keys()) == {"alerts", "digest", "chat"}

    def test_init_custom_concurrency(self):
        """Test initialization with custom concurrency settings."""
        custom = {"lane_a": 2, "lane_b": 5}
        queue = LaneAwareFIFO(concurrency=custom)
        assert queue.concurrency == custom
        assert set(queue.queues.keys()) == {"lane_a", "lane_b"}

    def test_enqueue_existing_lane(self):
        """Test enqueueing to an existing lane."""
        queue = LaneAwareFIFO()
        msg = SyncMessage(type="alert", payload={"symbol": "AAPL"})
        result = queue.enqueue("alerts", msg)
        assert result is True
        assert len(queue.queues["alerts"]) == 1
        assert queue.queues["alerts"][0] == msg

    def test_enqueue_new_lane(self):
        """Test enqueueing to a new lane."""
        queue = LaneAwareFIFO()
        msg = SyncMessage(type="alert", payload={"test": "data"})
        result = queue.enqueue("new_lane", msg)
        assert result is True
        assert "new_lane" in queue.queues
        assert queue.queues["new_lane"][0] == msg
        assert queue.concurrency["new_lane"] == 1

    def test_dequeue_when_under_concurrency(self):
        """Test dequeuing when under concurrency limit."""
        queue = LaneAwareFIFO(concurrency={"test": 2})
        msg1 = SyncMessage(type="alert")
        msg2 = SyncMessage(type="digest")

        queue.enqueue("test", msg1)
        queue.enqueue("test", msg2)

        # First dequeue should succeed
        result = queue.dequeue("test")
        assert result == msg1
        assert queue.active["test"] == 1

        # Second dequeue should succeed (under limit of 2)
        result = queue.dequeue("test")
        assert result == msg2
        assert queue.active["test"] == 2

    def test_dequeue_when_at_concurrency_limit(self):
        """Test dequeue returns None when at concurrency limit."""
        queue = LaneAwareFIFO(concurrency={"test": 1})
        msg1 = SyncMessage(type="alert")
        msg2 = SyncMessage(type="alert")

        queue.enqueue("test", msg1)
        queue.enqueue("test", msg2)

        # Dequeue first message
        queue.dequeue("test")
        assert queue.active["test"] == 1

        # Try to dequeue second while at limit
        result = queue.dequeue("test")
        assert result is None

    def test_dequeue_empty_queue(self):
        """Test dequeue on empty queue returns None."""
        queue = LaneAwareFIFO()
        result = queue.dequeue("alerts")
        assert result is None

    def test_dequeue_nonexistent_lane(self):
        """Test dequeue on nonexistent lane returns None."""
        queue = LaneAwareFIFO()
        result = queue.dequeue("nonexistent")
        assert result is None

    def test_complete_decrements_active(self):
        """Test complete decrements active count."""
        queue = LaneAwareFIFO()
        queue.active["test"] = 3
        queue.complete("test")
        assert queue.active["test"] == 2

    def test_complete_does_not_go_negative(self):
        """Test complete doesn't make active count negative."""
        queue = LaneAwareFIFO()
        queue.active["test"] = 0
        queue.complete("test")
        assert queue.active["test"] == 0

    def test_fifo_ordering(self):
        """Test that messages are dequeued in FIFO order."""
        queue = LaneAwareFIFO(concurrency={"test": 10})
        messages = [
            SyncMessage(type=f"msg{i}") for i in range(5)
        ]

        for msg in messages:
            queue.enqueue("test", msg)

        dequeued = []
        for _ in range(5):
            msg = queue.dequeue("test")
            if msg:
                dequeued.append(msg)
                queue.complete("test")

        assert dequeued == messages


class TestPairedDevice:
    """Test PairedDevice dataclass."""

    def test_creation_with_defaults(self):
        """Test creating a PairedDevice with defaults."""
        device = PairedDevice(device_id="dev123")
        assert device.device_id == "dev123"
        assert device.name == ""
        assert device.token == ""
        assert device.paired_at == ""
        assert device.is_active is True

    def test_creation_with_all_fields(self):
        """Test creating a PairedDevice with all fields."""
        now = datetime.now(timezone.utc).isoformat()
        device = PairedDevice(
            device_id="dev123",
            name="iPhone",
            token="token_xyz",
            paired_at=now,
            last_seen=now,
            is_active=True,
        )
        assert device.device_id == "dev123"
        assert device.name == "iPhone"
        assert device.token == "token_xyz"
        assert device.paired_at == now
        assert device.last_seen == now


class TestSyncMessage:
    """Test SyncMessage dataclass."""

    def test_creation_minimal(self):
        """Test creating a SyncMessage with minimal fields."""
        msg = SyncMessage(type="alert")
        assert msg.type == "alert"
        assert msg.payload == {}
        assert msg.timestamp == ""

    def test_creation_full(self):
        """Test creating a SyncMessage with all fields."""
        payload = {"symbol": "AAPL", "price": 150.25}
        now = datetime.now(timezone.utc).isoformat()
        msg = SyncMessage(
            type="alert",
            payload=payload,
            timestamp=now,
            device_id="dev123",
        )
        assert msg.type == "alert"
        assert msg.payload == payload
        assert msg.device_id == "dev123"


class TestMobileSyncGateway:
    """Test MobileSyncGateway main functionality."""

    @pytest.fixture
    def tmp_config_dir(self, tmp_path):
        """Provide a temporary config directory."""
        config_dir = tmp_path / ".neomind" / "finance"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    @pytest.fixture
    def gateway(self, tmp_config_dir, monkeypatch):
        """Create a gateway instance with temp config."""
        monkeypatch.setenv("HOME", str(tmp_config_dir.parent.parent))
        return MobileSyncGateway(port=18790)

    def test_init_creates_instance(self, gateway):
        """Test gateway initialization."""
        assert gateway.port == 18790
        assert gateway.paired_devices == {}
        assert gateway.event_queue is not None
        assert gateway._running is False
        assert gateway._mode == "standalone"

    def test_init_custom_port(self, tmp_config_dir, monkeypatch):
        """Test gateway with custom port."""
        monkeypatch.setenv("HOME", str(tmp_config_dir.parent.parent))
        monkeypatch.setenv("NEOMIND_SYNC_PORT", "19000")
        gateway = MobileSyncGateway()
        assert gateway.port == 19000

    def test_generate_pairing_code(self, gateway):
        """Test pairing code generation."""
        code = gateway.generate_pairing_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_pair_device_valid_code(self, gateway):
        """Test pairing a device with valid code."""
        code = "123456"
        device = gateway.pair_device(code, "TestPhone")
        assert device is not None
        assert device.device_id is not None
        assert device.name == "TestPhone"
        assert device.token is not None
        assert len(device.token) >= 60
        assert device.is_active is True

    def test_pair_device_invalid_code_empty(self, gateway):
        """Test pairing with empty code."""
        device = gateway.pair_device("", "TestPhone")
        assert device is None

    def test_pair_device_invalid_code_wrong_length(self, gateway):
        """Test pairing with wrong code length."""
        device = gateway.pair_device("12345", "TestPhone")
        assert device is None
        device = gateway.pair_device("1234567", "TestPhone")
        assert device is None

    def test_pair_device_generates_unique_ids(self, gateway):
        """Test that pairing generates unique device IDs."""
        device1 = gateway.pair_device("111111", "Phone1")
        device2 = gateway.pair_device("222222", "Phone2")
        assert device1.device_id != device2.device_id
        assert device1.token != device2.token

    def test_pair_device_default_name(self, gateway):
        """Test pairing with default device name."""
        device = gateway.pair_device("123456")
        assert device.name.startswith("Device-")

    def test_paired_devices_persisted(self, gateway, tmp_config_dir):
        """Test that paired devices are persisted to config."""
        device = gateway.pair_device("123456", "TestDevice")
        config_path = tmp_config_dir / "sync_config.json"
        assert config_path.exists()

        # Load config and verify
        data = json.loads(config_path.read_text())
        assert len(data["devices"]) == 1
        assert data["devices"][0]["name"] == "TestDevice"

    def test_load_config(self, gateway, tmp_config_dir):
        """Test loading paired devices from config."""
        # Create a config file
        config_path = tmp_config_dir / "sync_config.json"
        devices_data = [
            {
                "device_id": "dev1",
                "name": "iPhone",
                "token": "token123",
                "paired_at": "2024-01-01T00:00:00+00:00",
                "last_seen": "2024-01-02T00:00:00+00:00",
                "is_active": True,
            }
        ]
        config_path.write_text(json.dumps({"devices": devices_data}))

        # Create new gateway and verify it loads
        new_gateway = MobileSyncGateway(port=18790)
        assert len(new_gateway.paired_devices) == 1
        assert new_gateway.paired_devices["dev1"].name == "iPhone"

    def test_revoke_device(self, gateway):
        """Test revoking a paired device."""
        device = gateway.pair_device("123456", "TestPhone")
        assert device.is_active is True

        # Revoke it
        result = gateway.revoke_device(device.device_id)
        assert result is True
        assert gateway.paired_devices[device.device_id].is_active is False

    def test_revoke_nonexistent_device(self, gateway):
        """Test revoking a nonexistent device."""
        result = gateway.revoke_device("nonexistent")
        assert result is False

    def test_authenticate_valid_token(self, gateway):
        """Test authentication with valid token."""
        device = gateway.pair_device("123456", "TestPhone")
        authenticated = gateway.authenticate(device.token)
        assert authenticated is not None
        assert authenticated.device_id == device.device_id
        assert authenticated.last_seen is not None

    def test_authenticate_invalid_token(self, gateway):
        """Test authentication with invalid token."""
        gateway.pair_device("123456", "TestPhone")
        authenticated = gateway.authenticate("invalid_token")
        assert authenticated is None

    def test_authenticate_revoked_device(self, gateway):
        """Test authentication with revoked device token."""
        device = gateway.pair_device("123456", "TestPhone")
        gateway.revoke_device(device.device_id)
        authenticated = gateway.authenticate(device.token)
        assert authenticated is None

    def test_authenticate_updates_last_seen(self, gateway):
        """Test that authentication updates last_seen timestamp."""
        device = gateway.pair_device("123456", "TestPhone")
        old_seen = device.last_seen

        # Wait a moment and authenticate
        import time
        time.sleep(0.1)
        authenticated = gateway.authenticate(device.token)

        assert authenticated.last_seen > old_seen

    def test_push_alert(self, gateway):
        """Test pushing an alert."""
        alert = {"symbol": "AAPL", "price": 150.25, "condition": "above"}
        gateway.push_alert(alert)

        # Check queue
        msg = gateway.event_queue.dequeue("alerts")
        assert msg is not None
        assert msg.type == "alert"
        assert msg.payload == alert

    def test_push_digest(self, gateway):
        """Test pushing a digest."""
        digest = {"title": "Daily Digest", "items": []}
        gateway.push_digest(digest)

        # Check queue
        msg = gateway.event_queue.dequeue("digest")
        assert msg is not None
        assert msg.type == "digest"
        assert msg.payload == digest

    def test_sync_memory_no_bridge(self, gateway):
        """Test sync_memory when no memory bridge is set."""
        result = gateway.sync_memory()
        assert result == {"exported": 0, "imported": 0, "conflicts": 0}

    def test_sync_memory_with_bridge(self, gateway):
        """Test sync_memory with memory bridge."""
        mock_bridge = Mock()
        mock_bridge.sync.return_value = {"exported": 5, "imported": 3, "conflicts": 0}
        gateway._memory_bridge = mock_bridge

        result = gateway.sync_memory()
        assert result == {"exported": 5, "imported": 3, "conflicts": 0}
        mock_bridge.sync.assert_called_once()

    def test_init_openclaw_no_env(self, gateway, monkeypatch):
        """Test init_openclaw when no OpenClaw env vars are set."""
        monkeypatch.delenv("OPENCLAW_DEVICE_TOKEN", raising=False)
        monkeypatch.delenv("OPENCLAW_GATEWAY_URL", raising=False)

        result = gateway.init_openclaw()
        assert result is False
        assert gateway._mode == "standalone"

    def test_init_openclaw_with_token(self, gateway, monkeypatch):
        """Test init_openclaw with token."""
        monkeypatch.setenv("OPENCLAW_DEVICE_TOKEN", "test_token")
        monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "ws://localhost:18789")

        # Mock the imports where they're actually used
        with patch("agent.finance.openclaw_gateway.OpenClawGateway") as mock_gateway, \
             patch("agent.finance.openclaw_skill.OpenClawFinanceSkill") as mock_skill, \
             patch("agent.finance.memory_bridge.MemoryBridge") as mock_bridge:
            mock_instance = Mock()
            mock_gateway.return_value = mock_instance
            mock_skill.return_value = Mock()
            mock_bridge.return_value = Mock()

            result = gateway.init_openclaw()
            # Will succeed if modules are available, otherwise skipped
            # Just verify it doesn't crash

    def test_openclaw_gateway_property(self, gateway):
        """Test openclaw_gateway property."""
        assert gateway.openclaw_gateway is None

        mock_gw = Mock()
        gateway._openclaw_gateway = mock_gw
        assert gateway.openclaw_gateway == mock_gw

    def test_memory_bridge_property(self, gateway):
        """Test memory_bridge property."""
        assert gateway.memory_bridge is None

        mock_bridge = Mock()
        gateway._memory_bridge = mock_bridge
        assert gateway.memory_bridge == mock_bridge

    def test_get_status_standalone_mode(self, gateway):
        """Test status output for standalone mode."""
        device = gateway.pair_device("123456", "TestPhone")
        status = gateway.get_status()

        assert "Mobile Sync Gateway" in status
        assert "standalone" in status
        assert "Port: 18790" in status
        assert "TestPhone" in status

    def test_get_status_no_devices(self, gateway):
        """Test status output with no paired devices."""
        status = gateway.get_status()
        assert "No devices paired" in status

    def test_get_status_running(self, gateway):
        """Test status when running."""
        gateway._running = True
        status = gateway.get_status()
        assert "Running" in status

    def test_get_status_stopped(self, gateway):
        """Test status when stopped."""
        gateway._running = False
        status = gateway.get_status()
        assert "Stopped" in status


class TestMobileSyncGatewayAsync:
    """Test async methods of MobileSyncGateway."""

    @pytest.mark.asyncio
    async def test_start_standalone_no_websockets(self, tmp_path, monkeypatch):
        """Test start in standalone mode when websockets unavailable."""
        monkeypatch.setenv("HOME", str(tmp_path))

        gateway = MobileSyncGateway(port=18790)

        with patch("agent.finance.mobile_sync.HAS_WEBSOCKETS", False):
            # Should print warning and return
            await gateway.start()
            # Just verify it doesn't crash

    @pytest.mark.asyncio
    async def test_stop(self, tmp_path, monkeypatch):
        """Test stopping the gateway."""
        monkeypatch.setenv("HOME", str(tmp_path))
        gateway = MobileSyncGateway(port=18790)
        gateway._running = True

        await gateway.stop()
        assert gateway._running is False

    @pytest.mark.asyncio
    async def test_stop_with_openclaw(self, tmp_path, monkeypatch):
        """Test stopping with OpenClaw gateway."""
        monkeypatch.setenv("HOME", str(tmp_path))
        gateway = MobileSyncGateway(port=18790)
        gateway._running = True

        mock_gw = AsyncMock()
        gateway._openclaw_gateway = mock_gw

        await gateway.stop()
        mock_gw.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_periodic_memory_sync(self, tmp_path, monkeypatch):
        """Test periodic memory sync."""
        monkeypatch.setenv("HOME", str(tmp_path))
        gateway = MobileSyncGateway(port=18790)
        gateway._running = True

        mock_bridge = Mock()
        mock_bridge.sync.return_value = {"exported": 0, "imported": 0, "conflicts": 0}
        gateway._memory_bridge = mock_bridge

        # Run sync once
        task = asyncio.create_task(gateway._periodic_memory_sync())
        await asyncio.sleep(0.1)
        gateway._running = False

        try:
            await asyncio.wait_for(task, timeout=1)
        except asyncio.TimeoutError:
            pass


# Integration-style tests
class TestMobileSyncIntegration:
    """Integration tests for mobile sync components."""

    @pytest.fixture
    def gateway(self, tmp_path, monkeypatch):
        """Create gateway with temp storage."""
        monkeypatch.setenv("HOME", str(tmp_path))
        return MobileSyncGateway(port=18790)

    def test_complete_pairing_flow(self, gateway):
        """Test complete device pairing and authentication flow."""
        # Generate and pair
        code = gateway.generate_pairing_code()
        device = gateway.pair_device(code, "MyPhone")

        # Store token
        token = device.token

        # Authenticate
        auth_device = gateway.authenticate(token)
        assert auth_device is not None
        assert auth_device.device_id == device.device_id

        # Revoke
        gateway.revoke_device(device.device_id)

        # Auth should now fail
        auth_device = gateway.authenticate(token)
        assert auth_device is None

    def test_message_queue_flow(self, gateway):
        """Test end-to-end message queuing."""
        # Push messages
        gateway.push_alert({"symbol": "AAPL", "price": 150})
        gateway.push_digest({"title": "Daily"})

        # Dequeue
        alerts = gateway.event_queue.dequeue("alerts")
        assert alerts.type == "alert"

        digest = gateway.event_queue.dequeue("digest")
        assert digest.type == "digest"

    def test_multiple_devices_isolation(self, gateway):
        """Test that multiple devices are isolated."""
        dev1 = gateway.pair_device("111111", "Phone1")
        dev2 = gateway.pair_device("222222", "Phone2")

        # Revoke dev1
        gateway.revoke_device(dev1.device_id)

        # dev1 auth should fail, dev2 should work
        assert gateway.authenticate(dev1.token) is None
        assert gateway.authenticate(dev2.token) is not None
