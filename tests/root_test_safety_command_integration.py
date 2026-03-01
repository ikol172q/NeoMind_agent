#!/usr/bin/env python3
"""
Test safety integration with command handlers.
Verifies that file operations go through SafetyManager and audit logging works.
"""
import os
import sys
import tempfile
import shutil
import json
# Ensure UTF-8 encoding for stdout/stderr to handle emojis
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None
sys.stderr.reconfigure(encoding='utf-8') if hasattr(sys.stderr, 'reconfigure') else None

# Add agent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core import DeepSeekStreamingChat
from agent.safety import SafetyManager

def test_write_command_safety():
    """Test that /write command uses safety manager."""
    print("=== Testing /write command safety ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create agent with dummy API key
        agent = DeepSeekStreamingChat(api_key="dummy_key")
        # Replace safety manager with one using tmpdir as workspace
        new_sm = SafetyManager(workspace_root=tmpdir, agent_root=tmpdir)
        agent.safety_manager = new_sm
        # Ensure code analyzer uses this safety manager
        agent.code_analyzer = None  # force reinitialization with new safety manager

        test_file = os.path.join(tmpdir, "test.txt")
        content = "Hello safety"

        # Call handle_write_command directly
        result = agent.handle_write_command(f"{test_file} {content}")
        # result may contain Unicode characters; skip printing to avoid encoding issues

        # Verify file was written
        assert os.path.exists(test_file), "File should exist"
        with open(test_file, 'r', encoding='utf-8') as f:
            actual = f.read()
        assert actual == content, f"Content mismatch: {actual}"

        # Verify audit log contains write entry
        audit_log = os.path.join(tmpdir, '.safety_audit.log')
        assert os.path.exists(audit_log), "Audit log should exist"
        with open(audit_log, 'r') as f:
            entries = [json.loads(line.strip()) for line in f if line.strip()]
        write_entries = [e for e in entries if e.get('action') == 'write']
        assert len(write_entries) > 0, "No write entry in audit log"
        # Check that the path matches
        path_matches = [e for e in write_entries if e.get('path') == test_file]
        assert len(path_matches) > 0, f"No write entry for path {test_file}"
        print("[OK] /write command uses safety manager and logs audit")

        # Verify that reading via /read also logs audit
        result = agent.handle_read_command(test_file)
        # Should have read entry
        with open(audit_log, 'r') as f:
            entries = [json.loads(line.strip()) for line in f if line.strip()]
        read_entries = [e for e in entries if e.get('action') == 'read']
        assert len(read_entries) > 0, "No read entry in audit log"
        print("[OK] /read command logs audit")

        # Test that safety manager blocked dangerous extension (if configured)
        dangerous = os.path.join(tmpdir, "evil.exe")
        result = agent.handle_write_command(f"{dangerous} malicious")
        # Check if file was created; if safety manager blocks .exe, file should not exist
        # But safety manager may allow within workspace. We'll just note.
        if not os.path.exists(dangerous):
            print("[OK] Dangerous extension blocked")
        else:
            print("[INFO] Dangerous extension allowed within workspace")

        print("[OK] Write command safety test passed")
        return True

def test_safety_manager_blocks_dangerous_paths():
    """Test safety manager blocks dangerous paths."""
    print("\n=== Testing dangerous path blocking ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = SafetyManager(workspace_root=tmpdir, agent_root=tmpdir)

        # Test system directory
        if os.name != 'nt':
            sys_path = "/etc/passwd"
        else:
            sys_path = "C:\\Windows\\System32\\cmd.exe"
        safe, reason = sm.is_path_safe(sys_path, 'read')
        assert not safe, f"System path should be blocked: {reason}"
        print("[OK] System directory blocked")

        # Test path traversal
        traversal = os.path.join(tmpdir, "..", "outside.txt")
        safe, reason = sm.is_path_safe(traversal, 'read')
        assert not safe, f"Path traversal should be blocked: {reason}"
        print("[OK] Path traversal blocked")

        # Test dangerous extension (within workspace may be allowed)
        dangerous_ext = os.path.join(tmpdir, "test.exe")
        safe, reason = sm.is_path_safe(dangerous_ext, 'write')
        # This may be allowed within workspace; check if extension is in dangerous list
        if safe:
            print("[INFO] Dangerous extension allowed within workspace (config)")
        else:
            print("[OK] Dangerous extension blocked")

        # Test size limit
        # Create a large content (>10MB)
        large_content = "x" * (11 * 1024 * 1024)  # 11MB
        large_file = os.path.join(tmpdir, "large.txt")
        # safe_write_file should reject
        success, msg, backup = sm.safe_write_file(large_file, large_content, create_backup=False)
        assert not success, f"Large file should be blocked: {msg}"
        print("[OK] Size limit enforced")

        print("[OK] Dangerous path blocking test passed")
        return True

def main():
    """Run all safety integration tests."""
    try:
        test_write_command_safety()
        test_safety_manager_blocks_dangerous_paths()
        print("\n[OK] All safety command integration tests passed!")
        return 0
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n[FAIL] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())