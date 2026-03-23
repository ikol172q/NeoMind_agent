"""Shared test configuration for all test modules."""

import os

# Disable vault side-effects during tests (vault writes to ~/neomind-vault,
# which leaks state across test runs and breaks conversation_history assertions).
# Vault-specific tests in test_vault_*.py use their own tmp_path fixtures.
os.environ["NEOMIND_DISABLE_VAULT"] = "1"
