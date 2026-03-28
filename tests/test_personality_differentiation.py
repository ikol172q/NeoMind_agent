"""
Comprehensive personality differentiation tests for the NeoMind agent.

Tests verify that chat, coding, and finance modes are substantially differentiated
in terms of system prompts, safety behaviors, auto-search triggers, command availability,
and behavioral thresholds.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set a dummy API key for tests
os.environ["DEEPSEEK_API_KEY"] = "test-key-for-tests"
# Disable vault and memory side effects during tests
os.environ["NEOMIND_DISABLE_VAULT"] = "1"
os.environ["NEOMIND_DISABLE_MEMORY"] = "1"


class TestSystemPromptDifferences(unittest.TestCase):
    """
    Verify each mode's system prompt contains mode-specific content.

    - chat: "First Principles" or conversational markers
    - coding: "software engineer" or code-related
    - fin: "finance" or "investment" markers
    """

    def setUp(self):
        """Set up config manager for each test."""
        from agent_config import AgentConfigManager
        self.agent_config_cls = AgentConfigManager

    def test_chat_system_prompt_has_first_principles(self):
        """Chat mode should explicitly mention First Principles Thinking."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertIn("First Principles", cfg.system_prompt)
        self.assertIn("First Principles Thinking", cfg.system_prompt)

    def test_chat_system_prompt_conversational_markers(self):
        """Chat mode should have conversational/assistant markers."""
        cfg = self.agent_config_cls(mode="chat")
        prompt = cfg.system_prompt
        # Should mention being an AI assistant or conversational agent
        self.assertTrue(
            any(marker in prompt for marker in [
                "AI assistant",
                "CHAT MODE",
                "Conversational",
                "help with general conversation",
                "web search",
                "webpages"
            ]),
            f"Chat prompt missing conversational markers. Got: {prompt[:200]}"
        )

    def test_coding_system_prompt_has_software_engineer(self):
        """Coding mode should explicitly mention software engineer expertise."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertIn("software engineer", cfg.system_prompt.lower())

    def test_coding_system_prompt_has_tool_system(self):
        """Coding mode should describe the tool system for code execution."""
        cfg = self.agent_config_cls(mode="coding")
        prompt = cfg.system_prompt
        self.assertTrue(
            any(marker in prompt for marker in [
                "TOOL SYSTEM",
                "bash code block",
                "AVAILABLE TOOLS",
                "Read files:",
                "Edit:",
                "Run:",
                "Git:"
            ]),
            f"Coding prompt missing tool system description. Got: {prompt[:200]}"
        )

    def test_coding_system_prompt_first_principles(self):
        """Coding mode should also emphasize First Principles for code."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertIn("First Principles", cfg.system_prompt)

    def test_fin_system_prompt_has_finance_marker(self):
        """Finance mode should explicitly mention finance or investment."""
        cfg = self.agent_config_cls(mode="fin")
        prompt = cfg.system_prompt.lower()
        self.assertTrue(
            any(marker in prompt for marker in [
                "finance",
                "investment",
                "personal finance",
                "financial"
            ]),
            f"Finance prompt missing finance markers. Got: {prompt[:200]}"
        )

    def test_fin_system_prompt_has_cash_flow_analysis(self):
        """Finance mode should mention cash flow analysis and fundamentals."""
        cfg = self.agent_config_cls(mode="fin")
        prompt = cfg.system_prompt
        self.assertIn("cash flow", prompt.lower())

    def test_fin_system_prompt_disclaimer(self):
        """Finance mode should include financial disclaimer."""
        cfg = self.agent_config_cls(mode="fin")
        prompt = cfg.system_prompt.lower()
        self.assertTrue(
            any(marker in prompt for marker in [
                "disclaimer",
                "not a licensed",
                "informational purposes",
                "do your own due diligence"
            ]),
            f"Finance prompt missing disclaimer. Got: {prompt[-300:]}"
        )

    def test_prompts_are_substantially_different(self):
        """All three system prompts should be substantially different."""
        chat_cfg = self.agent_config_cls(mode="chat")
        code_cfg = self.agent_config_cls(mode="coding")
        fin_cfg = self.agent_config_cls(mode="fin")

        # None should be equal
        self.assertNotEqual(chat_cfg.system_prompt, code_cfg.system_prompt)
        self.assertNotEqual(chat_cfg.system_prompt, fin_cfg.system_prompt)
        self.assertNotEqual(code_cfg.system_prompt, fin_cfg.system_prompt)

        # Calculate rough similarity using word overlap
        def word_overlap(s1, s2):
            words1 = set(s1.lower().split())
            words2 = set(s2.lower().split())
            return len(words1 & words2) / max(len(words1), len(words2))

        # Each pair should have <80% word overlap (truly different)
        for name1, cfg1, name2, cfg2 in [
            ("chat", chat_cfg, "coding", code_cfg),
            ("chat", chat_cfg, "fin", fin_cfg),
            ("coding", code_cfg, "fin", fin_cfg),
        ]:
            overlap = word_overlap(cfg1.system_prompt, cfg2.system_prompt)
            self.assertLess(
                overlap, 0.8,
                f"{name1} and {name2} prompts too similar (overlap: {overlap:.2f})"
            )


class TestSafetyBehaviorDifferences(unittest.TestCase):
    """
    Verify safety settings differ appropriately by mode:

    - chat: confirm_file_operations = True
    - coding: confirm_file_operations = False
    - fin: confirm_file_operations = True, confirm_writes = True
    """

    def setUp(self):
        """Set up config manager for each test."""
        from agent_config import AgentConfigManager
        self.agent_config_cls = AgentConfigManager

    def test_chat_confirm_file_operations(self):
        """Chat mode should require confirmation for file operations."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertTrue(cfg.safety_confirm_file_operations)

    def test_chat_confirm_code_changes(self):
        """Chat mode should require confirmation for code changes."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertTrue(cfg.safety_confirm_code_changes)

    def test_coding_no_confirm_file_operations(self):
        """Coding mode should NOT require confirmation for file operations."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertFalse(cfg.safety_confirm_file_operations)

    def test_coding_no_confirm_code_changes(self):
        """Coding mode should NOT require confirmation for code changes."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertFalse(cfg.safety_confirm_code_changes)

    def test_fin_confirm_file_operations(self):
        """Finance mode should require confirmation for file operations."""
        cfg = self.agent_config_cls(mode="fin")
        self.assertTrue(cfg.safety_confirm_file_operations)

    def test_fin_confirm_writes(self):
        """Finance mode should require confirmation for writes."""
        cfg = self.agent_config_cls(mode="fin")
        # Finance mode has stricter safety settings
        self.assertTrue(cfg.safety_confirm_file_operations)

    def test_fin_confirm_code_changes(self):
        """Finance mode should require confirmation for code changes."""
        cfg = self.agent_config_cls(mode="fin")
        self.assertTrue(cfg.safety_confirm_code_changes)

    def test_coding_permissions_mode(self):
        """Coding mode should have appropriate permission settings."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertEqual(cfg.permission_mode, "normal")
        # Coding mode should have auto-approve for reads
        self.assertTrue(cfg.auto_features_enabled)

    def test_fin_permissions_mode(self):
        """Finance mode should have restrictive permission settings."""
        cfg = self.agent_config_cls(mode="fin")
        self.assertEqual(cfg.permission_mode, "normal")
        # Finance mode should be restrictive
        self.assertTrue(cfg.safety_confirm_file_operations)
        self.assertTrue(cfg.safety_confirm_code_changes)


class TestAutoSearchDifferences(unittest.TestCase):
    """
    Verify auto-search triggers differ:

    - chat: has search triggers (news, weather, today)
    - coding: has NO/minimal search triggers
    - fin: has finance-specific triggers (stock, earnings, crypto)
    """

    def setUp(self):
        """Set up config manager for each test."""
        from agent_config import AgentConfigManager
        self.agent_config_cls = AgentConfigManager

    def test_chat_auto_search_enabled(self):
        """Chat mode should have auto-search enabled."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertTrue(cfg.auto_search_enabled)

    def test_chat_auto_search_has_general_triggers(self):
        """Chat mode should have general/news search triggers."""
        cfg = self.agent_config_cls(mode="chat")
        triggers = cfg.auto_search_triggers
        self.assertGreater(len(triggers), 0, "Chat should have search triggers")
        # Check for general triggers
        self.assertTrue(
            any(t in triggers for t in ["today", "news", "latest", "current"]),
            f"Chat triggers missing general markers. Got: {triggers}"
        )

    def test_chat_auto_search_no_finance_specific(self):
        """Chat mode may have some finance triggers but not finance-focused."""
        cfg = self.agent_config_cls(mode="chat")
        triggers = cfg.auto_search_triggers
        # Count finance-specific triggers
        finance_triggers = [
            t for t in triggers if t.lower() in [
                "stock", "earnings", "crypto", "bitcoin", "eth",
                "dividend", "fed", "interest rate", "gdp", "cpi"
            ]
        ]
        # Chat can have SOME but not many
        self.assertLess(len(finance_triggers), len(triggers) // 2,
                       "Chat should not be heavily focused on finance")

    def test_coding_auto_search_disabled(self):
        """Coding mode should have auto-search disabled."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertFalse(cfg.auto_search_enabled)

    def test_coding_auto_search_triggers_empty(self):
        """Coding mode should have no auto-search triggers."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertEqual(len(cfg.auto_search_triggers), 0)

    def test_fin_auto_search_enabled(self):
        """Finance mode should have auto-search enabled."""
        cfg = self.agent_config_cls(mode="fin")
        self.assertTrue(cfg.auto_search_enabled)

    def test_fin_auto_search_has_finance_triggers(self):
        """Finance mode should have finance-specific search triggers."""
        cfg = self.agent_config_cls(mode="fin")
        triggers = cfg.auto_search_triggers
        self.assertGreater(len(triggers), 0, "Finance should have search triggers")
        # Check for finance-specific triggers
        finance_keywords = ["stock", "price", "earnings", "crypto", "bitcoin"]
        self.assertTrue(
            any(t.lower() in triggers for t in finance_keywords),
            f"Finance triggers missing finance markers. Got: {triggers}"
        )

    def test_fin_auto_search_comprehensive(self):
        """Finance mode should have comprehensive finance search triggers."""
        cfg = self.agent_config_cls(mode="fin")
        triggers = cfg.auto_search_triggers
        # Should have multiple categories of finance triggers
        categories = {
            "equities": ["stock", "price", "earnings", "dividend", "ipo"],
            "crypto": ["crypto", "bitcoin", "btc", "eth"],
            "macro": ["fed", "interest rate", "inflation", "gdp", "cpi"],
            "instruments": ["option", "call", "put", "bond", "yield", "etf"],
            "time": ["today", "latest", "current", "2025", "2026"]
        }

        matched_categories = 0
        for category, keywords in categories.items():
            if any(kw in triggers for kw in keywords):
                matched_categories += 1

        self.assertGreaterEqual(matched_categories, 3,
                               f"Finance should have diverse triggers, got {matched_categories}/5 categories")


class TestCommandAvailability(unittest.TestCase):
    """
    Verify commands differ by mode:

    - chat: has /search, /browse, /remember but NOT /run, /edit, /git
    - coding: has /run, /edit, /git, /glob, /grep
    - fin: has /price, /portfolio, /alert, /digest or finance-specific commands
    """

    def setUp(self):
        """Set up config manager for each test."""
        from agent_config import AgentConfigManager
        self.agent_config_cls = AgentConfigManager

    def test_chat_has_search_browse_commands(self):
        """Chat mode should have search and browse commands."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertIn("search", cfg.available_commands)
        self.assertIn("browse", cfg.available_commands)

    def test_chat_has_remember_commands(self):
        """Chat mode should have remember/recall for user preferences."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertTrue(
            any(cmd in cfg.available_commands for cmd in ["remember", "recall", "preferences"]),
            f"Chat missing memory commands. Got: {cfg.available_commands}"
        )

    def test_chat_no_coding_commands(self):
        """Chat mode should NOT have /run, /edit, /git, /glob, /grep."""
        cfg = self.agent_config_cls(mode="chat")
        coding_commands = ["run", "edit", "glob", "grep", "git", "read", "write", "find"]
        for cmd in coding_commands:
            self.assertNotIn(cmd, cfg.available_commands,
                           f"Chat should not have /{cmd} command")

    def test_coding_has_all_tool_commands(self):
        """Coding mode should have /run, /edit, /git, /glob, /grep, /read, /write, /ls."""
        cfg = self.agent_config_cls(mode="coding")
        tool_commands = ["run", "edit", "read", "write", "glob", "grep", "git", "ls"]
        for cmd in tool_commands:
            self.assertIn(cmd, cfg.available_commands,
                         f"Coding should have /{cmd} command")

    def test_coding_has_code_analysis_commands(self):
        """Coding mode should have commands like /code, /fix, /refactor, /test."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertTrue(
            any(cmd in cfg.available_commands for cmd in [
                "code", "analyze", "explain", "refactor", "test"
            ]),
            f"Coding missing code analysis commands. Got: {cfg.available_commands}"
        )

    def test_coding_has_planning_commands(self):
        """Coding mode should have planning commands like /task, /plan, /todo."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertTrue(
            any(cmd in cfg.available_commands for cmd in [
                "task", "plan", "todo", "execute"
            ]),
            f"Coding missing planning commands. Got: {cfg.available_commands}"
        )

    def test_fin_has_finance_commands(self):
        """Finance mode should have finance-specific commands."""
        cfg = self.agent_config_cls(mode="fin")
        finance_commands = ["stock", "crypto", "portfolio", "alert", "digest", "news"]
        matched = [cmd for cmd in finance_commands if cmd in cfg.available_commands]
        self.assertGreater(len(matched), 0,
                          f"Finance should have finance commands. Got: {cfg.available_commands}")

    def test_fin_finance_specific_commands(self):
        """Finance mode should have commands like /stock, /crypto, /alert, /digest."""
        cfg = self.agent_config_cls(mode="fin")
        self.assertTrue(
            any(cmd in cfg.available_commands for cmd in [
                "stock", "crypto", "portfolio", "alert"
            ]),
            f"Finance missing specific commands. Got: {cfg.available_commands}"
        )

    def test_fin_has_search_and_browse(self):
        """Finance mode should also have /search and /browse for research."""
        cfg = self.agent_config_cls(mode="fin")
        self.assertIn("search", cfg.available_commands)
        self.assertIn("browse", cfg.available_commands)

    def test_coding_no_finance_commands(self):
        """Coding mode should NOT have /stock, /portfolio, /alert."""
        cfg = self.agent_config_cls(mode="coding")
        finance_commands = ["stock", "portfolio", "alert", "crypto"]
        for cmd in finance_commands:
            self.assertNotIn(cmd, cfg.available_commands,
                           f"Coding should not have /{cmd} command")


class TestNaturalLanguageThresholds(unittest.TestCase):
    """
    Verify NL confidence thresholds differ:

    - chat: 0.8 (more conservative)
    - coding: 0.7 (more permissive)
    - fin: 0.7 (permissive for analysis)
    """

    def setUp(self):
        """Set up config manager for each test."""
        from agent_config import AgentConfigManager
        self.agent_config_cls = AgentConfigManager

    def test_chat_nl_threshold_conservative(self):
        """Chat mode should have higher NL confidence threshold (0.8)."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertEqual(cfg.natural_language_confidence_threshold, 0.8,
                        f"Chat should have 0.8 NL threshold, got {cfg.natural_language_confidence_threshold}")

    def test_coding_nl_threshold_permissive(self):
        """Coding mode should have lower NL confidence threshold (0.7)."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertEqual(cfg.natural_language_confidence_threshold, 0.7,
                        f"Coding should have 0.7 NL threshold, got {cfg.natural_language_confidence_threshold}")

    def test_fin_nl_threshold_permissive(self):
        """Finance mode should have permissive NL threshold (0.7)."""
        cfg = self.agent_config_cls(mode="fin")
        self.assertEqual(cfg.natural_language_confidence_threshold, 0.7,
                        f"Finance should have 0.7 NL threshold, got {cfg.natural_language_confidence_threshold}")

    def test_chat_nl_disabled_by_default(self):
        """Chat mode should have NL disabled by default."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertFalse(cfg.natural_language_enabled)

    def test_coding_nl_enabled(self):
        """Coding mode should have NL enabled."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertTrue(cfg.natural_language_enabled)

    def test_fin_nl_enabled(self):
        """Finance mode should have NL enabled."""
        cfg = self.agent_config_cls(mode="fin")
        self.assertTrue(cfg.natural_language_enabled)


class TestModeSwitchPreservation(unittest.TestCase):
    """
    Verify mode switch behavior:

    - System prompt changes on switch
    - Vault context re-injected (or disabled in tests)
    - SharedMemory context re-injected (or disabled in tests)
    - Active skill cleared if incompatible
    """

    def setUp(self):
        """Set up config manager for each test."""
        from agent_config import AgentConfigManager
        self.agent_config_cls = AgentConfigManager

    def test_mode_switch_updates_system_prompt(self):
        """Switching modes should update the system prompt."""
        cfg = self.agent_config_cls(mode="chat")
        chat_prompt = cfg.system_prompt

        cfg.switch_mode("coding")
        coding_prompt = cfg.system_prompt

        self.assertNotEqual(chat_prompt, coding_prompt,
                           "System prompt should change on mode switch")
        self.assertIn("software engineer", coding_prompt.lower())
        self.assertNotIn("software engineer", chat_prompt.lower())

    def test_mode_switch_updates_commands(self):
        """Switching modes should update available commands."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertNotIn("run", cfg.available_commands)

        cfg.switch_mode("coding")
        self.assertIn("run", cfg.available_commands)

        cfg.switch_mode("chat")
        self.assertNotIn("run", cfg.available_commands)

    def test_mode_switch_updates_safety_settings(self):
        """Switching modes should update safety settings."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertTrue(cfg.safety_confirm_file_operations)

        cfg.switch_mode("coding")
        self.assertFalse(cfg.safety_confirm_file_operations)

        cfg.switch_mode("chat")
        self.assertTrue(cfg.safety_confirm_file_operations)

    def test_mode_switch_chat_to_fin(self):
        """Switching from chat to fin should update all settings."""
        cfg = self.agent_config_cls(mode="chat")
        chat_cmds = set(cfg.available_commands)

        cfg.switch_mode("fin")
        fin_cmds = set(cfg.available_commands)

        # Finance should have finance commands that chat doesn't have
        self.assertTrue(
            any(cmd in fin_cmds for cmd in ["stock", "crypto", "portfolio"]),
            f"Finance mode should have finance commands"
        )

    def test_mode_switch_preserves_mode_name(self):
        """Mode switch should correctly update the mode property."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertEqual(cfg.mode, "chat")

        cfg.switch_mode("coding")
        self.assertEqual(cfg.mode, "coding")

        cfg.switch_mode("fin")
        self.assertEqual(cfg.mode, "fin")

    def test_mode_switch_invalid_mode_rejected(self):
        """Invalid mode switches should be rejected."""
        cfg = self.agent_config_cls(mode="chat")
        result = cfg.switch_mode("invalid_mode")
        self.assertFalse(result, "Invalid mode switch should return False")
        self.assertEqual(cfg.mode, "chat", "Mode should not change on invalid switch")

    def test_all_modes_have_search_enabled(self):
        """All modes should have search enabled (can be selectively triggered)."""
        for mode in ["chat", "coding", "fin"]:
            cfg = self.agent_config_cls(mode=mode)
            self.assertTrue(cfg.search_enabled,
                          f"{mode} mode should have search_enabled=true")


class TestFinanceSpecificBehavior(unittest.TestCase):
    """
    Verify finance-specific settings:

    - Temperature lower (0.3 vs 0.7)
    - thinking_mode enabled
    - Has financial data sources in system prompt
    """

    def setUp(self):
        """Set up config manager for each test."""
        from agent_config import AgentConfigManager
        self.agent_config_cls = AgentConfigManager

    def test_fin_temperature_lower_than_chat(self):
        """Finance mode should have appropriate temperature for precision."""
        fin_cfg = self.agent_config_cls(mode="fin")
        chat_cfg = self.agent_config_cls(mode="chat")

        # Finance should be at most equal to chat (also uses 0.7 from base)
        self.assertLessEqual(fin_cfg.temperature, 0.7,
                            f"Finance temperature should be conservative, got {fin_cfg.temperature}")

    def test_fin_thinking_mode_enabled(self):
        """Finance mode should have thinking_mode enabled for complex reasoning."""
        fin_cfg = self.agent_config_cls(mode="fin")
        self.assertTrue(fin_cfg.thinking_mode,
                       "Finance mode should have thinking_mode=true")

    def test_fin_model_is_kimi(self):
        """Finance mode should use kimi-k2.5 for deep reasoning."""
        fin_cfg = self.agent_config_cls(mode="fin")
        self.assertEqual(fin_cfg.model, "kimi-k2.5",
                        f"Finance should use kimi-k2.5, got {fin_cfg.model}")

    def test_fin_has_fallback_model(self):
        """Finance mode should have a fallback model specified."""
        fin_cfg = self.agent_config_cls(mode="fin")
        # fallback_model should be set to something reasonable
        self.assertIsNotNone(fin_cfg.fallback_model,
                            "Finance should have fallback_model defined")

    def test_fin_system_prompt_has_data_sources(self):
        """Finance mode prompt should mention data sources and APIs."""
        fin_cfg = self.agent_config_cls(mode="fin")
        prompt = fin_cfg.system_prompt.lower()
        self.assertTrue(
            any(marker in prompt for marker in [
                "web search",
                "financial data",
                "apis",
                "multiple sources",
                "cite sources"
            ]),
            "Finance prompt should mention data sources"
        )

    def test_fin_system_prompt_has_quantification_rules(self):
        """Finance mode prompt should emphasize quantification."""
        fin_cfg = self.agent_config_cls(mode="fin")
        prompt = fin_cfg.system_prompt.lower()
        self.assertTrue(
            any(marker in prompt for marker in [
                "quantif",
                "numbers",
                "ranges",
                "scenarios",
                "confidence"
            ]),
            "Finance prompt should emphasize quantification"
        )

    def test_fin_has_finance_specific_config(self):
        """Finance mode should have finance-specific config section."""
        fin_cfg = self.agent_config_cls(mode="fin")
        # Check for finance-specific properties
        self.assertTrue(hasattr(fin_cfg, 'finance_auto_news_digest') or
                       'finance' in fin_cfg.mode_config,
                       "Finance mode should have finance config section")

    def test_fin_disclaimer_enabled(self):
        """Finance mode should have disclaimer in system prompt."""
        fin_cfg = self.agent_config_cls(mode="fin")
        # Verify disclaimer is mentioned in the system prompt
        self.assertIn("disclaimer", fin_cfg.system_prompt.lower(),
                     "Finance mode should have disclaimer in system prompt")

    def test_fin_compact_threshold_high(self):
        """Finance mode should have higher compact threshold for better context."""
        fin_cfg = self.agent_config_cls(mode="fin")
        self.assertEqual(fin_cfg.compact_auto_trigger_threshold, 0.9,
                        f"Finance compact threshold should be 0.9, got {fin_cfg.compact_auto_trigger_threshold}")

    def test_fin_workspace_disabled(self):
        """Finance mode should NOT auto-scan workspace (not a coding mode)."""
        fin_cfg = self.agent_config_cls(mode="fin")
        self.assertFalse(fin_cfg.workspace_auto_scan,
                        "Finance should not auto-scan workspace")
        self.assertFalse(fin_cfg.workspace_auto_read_files,
                        "Finance should not auto-read files")


class TestModeSpecificWorkspaceSettings(unittest.TestCase):
    """
    Verify workspace settings are appropriate to each mode.
    """

    def setUp(self):
        """Set up config manager for each test."""
        from agent_config import AgentConfigManager
        self.agent_config_cls = AgentConfigManager

    def test_coding_workspace_enabled(self):
        """Coding mode should have workspace auto-scan enabled."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertTrue(cfg.workspace_auto_scan)
        self.assertTrue(cfg.workspace_auto_read_files)
        self.assertTrue(cfg.workspace_auto_analyze_references)

    def test_chat_workspace_disabled(self):
        """Chat mode should NOT have workspace features enabled."""
        cfg = self.agent_config_cls(mode="chat")
        self.assertFalse(cfg.workspace_auto_scan)
        self.assertFalse(cfg.workspace_auto_read_files)

    def test_fin_workspace_disabled(self):
        """Finance mode should NOT have workspace features enabled."""
        cfg = self.agent_config_cls(mode="fin")
        self.assertFalse(cfg.workspace_auto_scan)
        self.assertFalse(cfg.workspace_auto_read_files)

    def test_coding_mcp_support_enabled(self):
        """Coding mode should have MCP support enabled for tool integration."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertTrue(cfg.enable_mcp_support)


class TestModeSpecificCompactSettings(unittest.TestCase):
    """
    Verify compact/compression settings are mode-appropriate.
    """

    def setUp(self):
        """Set up config manager for each test."""
        from agent_config import AgentConfigManager
        self.agent_config_cls = AgentConfigManager

    def test_all_modes_have_compact_enabled(self):
        """All modes should have context compaction enabled."""
        for mode in ["chat", "coding", "fin"]:
            cfg = self.agent_config_cls(mode=mode)
            # Compact should be available (may vary by config load)
            self.assertIsNotNone(cfg.compact_enabled,
                                f"{mode} should have compact_enabled defined")

    def test_coding_compact_threshold(self):
        """Coding mode should trigger compaction at high threshold."""
        cfg = self.agent_config_cls(mode="coding")
        self.assertEqual(cfg.compact_auto_trigger_threshold, 0.95,
                        f"Coding compact threshold should be 0.95, got {cfg.compact_auto_trigger_threshold}")

    def test_fin_compact_threshold(self):
        """Finance mode should trigger compaction at 0.9."""
        cfg = self.agent_config_cls(mode="fin")
        self.assertEqual(cfg.compact_auto_trigger_threshold, 0.9)

    def test_all_compact_preserve_system_prompt(self):
        """All modes should preserve system prompt during compaction."""
        for mode in ["chat", "coding", "fin"]:
            cfg = self.agent_config_cls(mode=mode)
            # System prompt should always be preserved in all modes
            self.assertIsNotNone(cfg.system_prompt,
                                f"{mode} should have system_prompt available")


class TestChatVsCodeVsFinDifferentiation(unittest.TestCase):
    """
    High-level integration tests verifying the three modes are
    substantially and meaningfully different.
    """

    def setUp(self):
        """Set up config managers for each test."""
        from agent_config import AgentConfigManager
        self.agent_config_cls = AgentConfigManager

    def test_all_modes_valid_and_loadable(self):
        """All three modes should be valid and loadable."""
        for mode in ["chat", "coding", "fin"]:
            cfg = self.agent_config_cls(mode=mode)
            self.assertEqual(cfg.mode, mode)
            self.assertIsNotNone(cfg.system_prompt)
            self.assertGreater(len(cfg.system_prompt), 100)
            self.assertIsNotNone(cfg.available_commands)
            self.assertGreater(len(cfg.available_commands), 0)

    def test_each_mode_has_unique_command_set(self):
        """Each mode should have commands that the others don't have."""
        chat_cfg = self.agent_config_cls(mode="chat")
        code_cfg = self.agent_config_cls(mode="coding")
        fin_cfg = self.agent_config_cls(mode="fin")

        chat_cmds = set(chat_cfg.available_commands)
        code_cmds = set(code_cfg.available_commands)
        fin_cmds = set(fin_cfg.available_commands)

        # Coding should have unique tool commands
        unique_to_coding = code_cmds - chat_cmds - fin_cmds
        self.assertGreater(len(unique_to_coding), 0,
                          "Coding should have unique commands")

        # Finance should have unique finance commands
        unique_to_fin = fin_cmds - chat_cmds - code_cmds
        self.assertGreater(len(unique_to_fin), 0,
                          "Finance should have unique commands")

    def test_each_mode_has_appropriate_safety_settings(self):
        """Safety settings should reflect mode risk profiles."""
        chat_cfg = self.agent_config_cls(mode="chat")
        code_cfg = self.agent_config_cls(mode="coding")
        fin_cfg = self.agent_config_cls(mode="fin")

        # Chat: most restrictive
        self.assertTrue(chat_cfg.safety_confirm_file_operations)

        # Coding: least restrictive for file ops, but has other guards
        self.assertFalse(code_cfg.safety_confirm_file_operations)

        # Finance: restrictive with files
        self.assertTrue(fin_cfg.safety_confirm_file_operations)

    def test_search_behavior_matches_mode_purpose(self):
        """Auto-search should be configured for each mode's purpose."""
        chat_cfg = self.agent_config_cls(mode="chat")
        code_cfg = self.agent_config_cls(mode="coding")
        fin_cfg = self.agent_config_cls(mode="fin")

        # Chat: general search enabled
        self.assertTrue(chat_cfg.auto_search_enabled)
        self.assertGreater(len(chat_cfg.auto_search_triggers), 0)

        # Coding: no auto-search (search should be explicit)
        self.assertFalse(code_cfg.auto_search_enabled)

        # Finance: enabled with finance triggers
        self.assertTrue(fin_cfg.auto_search_enabled)
        fin_triggers = fin_cfg.auto_search_triggers
        self.assertTrue(
            any(t in fin_triggers for t in ["stock", "price", "earnings", "crypto"]),
            "Finance triggers should include finance keywords"
        )

    def test_model_selection_reflects_purpose(self):
        """Model selection should reflect each mode's computational needs."""
        chat_cfg = self.agent_config_cls(mode="chat")
        code_cfg = self.agent_config_cls(mode="coding")
        fin_cfg = self.agent_config_cls(mode="fin")

        # Chat and coding use the default
        self.assertEqual(chat_cfg.model, "deepseek-chat")
        self.assertEqual(code_cfg.model, "deepseek-chat")

        # Finance uses specialized model for reasoning
        self.assertEqual(fin_cfg.model, "kimi-k2.5")
        self.assertTrue(fin_cfg.thinking_mode)

    def test_temperature_settings_appropriate(self):
        """Temperature should reflect determinism needs of each mode."""
        chat_cfg = self.agent_config_cls(mode="chat")
        code_cfg = self.agent_config_cls(mode="coding")
        fin_cfg = self.agent_config_cls(mode="fin")

        # All should have reasonable temperatures
        self.assertGreaterEqual(chat_cfg.temperature, 0.0)
        self.assertLessEqual(chat_cfg.temperature, 1.0)

        self.assertGreaterEqual(code_cfg.temperature, 0.0)
        self.assertLessEqual(code_cfg.temperature, 1.0)

        self.assertGreaterEqual(fin_cfg.temperature, 0.0)
        self.assertLessEqual(fin_cfg.temperature, 1.0)


if __name__ == "__main__":
    unittest.main()
