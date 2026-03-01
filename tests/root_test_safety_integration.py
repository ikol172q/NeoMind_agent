#!/usr/bin/env python3
"""
Test safety manager integration with CodeAnalyzer.
"""
import os
import sys
import tempfile
import shutil

# Add agent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.safety import SafetyManager
from agent.code_analyzer import CodeAnalyzer

def test_safety_manager_basic():
    """Test basic safety manager functionality."""
    print("=== Testing SafetyManager ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create safety manager with workspace = tmpdir
        sm = SafetyManager(workspace_root=tmpdir)

        # Create a test file
        test_file = os.path.join(tmpdir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("Hello World")

        # Test safe_read_file
        success, msg, content = sm.safe_read_file(test_file)
        assert success, f"safe_read_file failed: {msg}"
        assert content == "Hello World", f"Content mismatch: {content}"
        print("[OK] safe_read_file works")

        # Test safe_write_file
        new_content = "New content"
        success, msg, backup = sm.safe_write_file(test_file, new_content)
        assert success, f"safe_write_file failed: {msg}"
        print("[OK] safe_write_file works")

        # Verify write
        success, msg, content = sm.safe_read_file(test_file)
        assert content == new_content
        print("[OK] Write verified")

        # Test path safety
        safe, reason = sm.is_path_safe(test_file, 'read')
        assert safe, f"Path should be safe: {reason}"
        print("[OK] Path safety check works")

        # Test dangerous path
        dangerous = "/etc/passwd"
        safe, reason = sm.is_path_safe(dangerous, 'read')
        assert not safe, f"Dangerous path should be blocked: {reason}"
        print("[OK] Dangerous path blocked")

        # Check audit log exists
        audit_log = os.path.join(tmpdir, '.safety_audit.log')
        assert os.path.exists(audit_log), "Audit log should exist"
        with open(audit_log, 'r') as f:
            lines = f.readlines()
            assert len(lines) >= 2, f"Expected at least 2 audit entries, got {len(lines)}"
        print("[OK] Audit log created")

    print("SafetyManager tests passed.")

def test_code_analyzer_integration():
    """Test CodeAnalyzer integration with SafetyManager."""
    print("\n=== Testing CodeAnalyzer Integration ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = SafetyManager(workspace_root=tmpdir)
        ca = CodeAnalyzer(root_path=tmpdir, safety_manager=sm)

        # Create a test file
        test_file = os.path.join(tmpdir, "test.py")
        with open(test_file, 'w') as f:
            f.write("print('hello')")

        # Test read_file_safe (should use safety manager)
        success, msg, content = ca.read_file_safe(test_file)
        assert success, f"read_file_safe failed: {msg}"
        assert "print" in content
        print("[OK] CodeAnalyzer.read_file_safe works with safety manager")

        # Test write_file_safe
        success, msg = ca.write_file_safe(test_file, "new content", backup=False)
        assert success, f"write_file_safe failed: {msg}"
        print("[OK] CodeAnalyzer.write_file_safe works with safety manager")

        # Verify cache updated
        assert test_file in ca.file_cache
        print("[OK] Cache updated")

        # Test without safety manager (fallback)
        ca2 = CodeAnalyzer(root_path=tmpdir, safety_manager=None)
        success, msg, content = ca2.read_file_safe(test_file)
        assert success, f"Fallback read failed: {msg}"
        print("[OK] Fallback read works")

    print("CodeAnalyzer integration tests passed.")

def test_audit_log_entries():
    """Verify audit log entries contain expected actions."""
    print("\n=== Testing Audit Log Entries ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = SafetyManager(workspace_root=tmpdir)
        test_file = os.path.join(tmpdir, "audit_test.txt")
        sm.safe_write_file(test_file, "test")
        sm.safe_read_file(test_file)

        audit_log = os.path.join(tmpdir, '.safety_audit.log')
        with open(audit_log, 'r') as f:
            entries = [line.strip() for line in f if line.strip()]

        # Should have at least write and read entries
        actions = []
        for entry in entries:
            import json
            data = json.loads(entry)
            actions.append(data.get('action'))

        assert 'write' in actions, "Write action missing from audit log"
        assert 'read' in actions, "Read action missing from audit log"
        print(f"[OK] Audit log contains actions: {actions}")

    print("Audit log tests passed.")

if __name__ == '__main__':
    try:
        test_safety_manager_basic()
        test_code_analyzer_integration()
        test_audit_log_entries()
        print("\n[OK] All safety integration tests passed!")
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)