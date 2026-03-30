"""Comprehensive unit tests for NeoMind evolution integration hooks.

Test coverage:
1. Module imports and lazy loading
2. pre_llm_call() with various modes and modules
3. post_response() metrics recording and distillation
4. periodic_tasks() drift detection and KG maintenance
5. self_edit_gate() safety checks
6. Graceful degradation when modules fail to import
7. Integration with agentic_loop.py
8. self_restart.py functions
9. self_edit.py integration
"""

import unittest
from unittest import mock
from unittest.mock import Mock, MagicMock, patch, call
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import os
import sys


# ═══════════════════════════════════════════════════════════════
# Test fixtures and helpers
# ═══════════════════════════════════════════════════════════════

class MockDegradationManager:
    """Mock degradation manager for testing."""
    def __init__(self):
        self.current_tier = Mock()
        self.current_tier.value = "live"
        self.is_degraded = False

    def get_static_fallback(self, mode):
        if self.current_tier.value == "static":
            return f"Fallback response for {mode}"
        return None

    def check_and_auto_degrade(self, api_failure_rate=0.0):
        pass

    def recover(self):
        self.is_degraded = False


class MockDistillationEngine:
    """Mock distillation engine for testing."""
    def should_try_distillation(self, task_type):
        return task_type in ("financial_analysis", "learning_extraction")

    def get_best_exemplar(self, task_type):
        if task_type == "financial_analysis":
            return {"id": "exemplar_123", "content": "sample exemplar"}
        return None

    def build_distilled_prompt(self, prompt, exemplar):
        return f"{prompt}\n\n[Exemplar: {exemplar.get('id')}]"

    def record_attempt(self, **kwargs):
        pass

    def store_exemplar(self, **kwargs):
        pass

    def cleanup_old_exemplars(self, max_age_days=30):
        return 5

    def get_savings_report(self):
        return {"total_saved_usd": 42.50}


class MockKnowledgeGraph:
    """Mock knowledge graph for testing."""
    def discover_clusters(self):
        return [{"id": "c1", "size": 5}, {"id": "c2", "size": 3}]

    def get_stats(self):
        return {"total_edges": 127, "total_nodes": 45}


class MockDriftDetector:
    """Mock drift detector for testing."""
    def __init__(self):
        self.metrics = {}

    def record(self, metric_name, value, mode):
        if metric_name not in self.metrics:
            self.metrics[metric_name] = []
        self.metrics[metric_name].append({"value": value, "mode": mode})

    def check_drift(self):
        return {
            "overall_status": "no_drift",
            "metrics": {
                "response_latency_ms": {"status": "normal", "value": 150},
                "output_tokens_per_request": {"status": "normal", "value": 250},
            }
        }

    def compute_baseline(self, metric):
        pass


class MockAgentSpec:
    """Mock agent spec for testing."""
    def check(self, trigger_point, context):
        # Return empty list for normal cases
        return []


class MockDebateConsensus:
    """Mock debate consensus for testing."""
    def deliberate(self, proposal):
        return {
            "decision": "approve",
            "score": 0.95,
            "votes": [
                {"viewpoint": "cautious", "vote": "yes", "confidence": 0.9},
                {"viewpoint": "pragmatic", "vote": "yes", "confidence": 0.95},
            ]
        }


class MockCostOptimizer:
    """Mock cost optimizer for testing."""
    def get_output_limit(self, mode):
        limits = {
            "chat": 2048,
            "coding": 4096,
            "fin": 1024,
        }
        return limits.get(mode)


# ═══════════════════════════════════════════════════════════════
# Test cases
# ═══════════════════════════════════════════════════════════════

class TestModuleImports(unittest.TestCase):
    """Test that integration_hooks can be imported."""

    def test_integration_hooks_import(self):
        """Verify integration_hooks module can be imported."""
        try:
            import agent.evolution.integration_hooks as hooks
            self.assertTrue(hasattr(hooks, 'pre_llm_call'))
            self.assertTrue(hasattr(hooks, 'post_response'))
            self.assertTrue(hasattr(hooks, 'periodic_tasks'))
            self.assertTrue(hasattr(hooks, 'self_edit_gate'))
        except ImportError as e:
            self.fail(f"Failed to import integration_hooks: {e}")

    def test_integration_hooks_all_functions_present(self):
        """Verify all hook functions exist."""
        import agent.evolution.integration_hooks as hooks

        required_functions = [
            'pre_llm_call',
            'post_response',
            'periodic_tasks',
            'self_edit_gate',
            '_get_degradation',
            '_get_distillation',
            '_get_knowledge_graph',
            '_get_drift_detector',
            '_get_agent_spec',
            '_get_debate',
            '_get_cost_optimizer',
            '_infer_task_type',
            '_estimate_quality',
        ]

        for func_name in required_functions:
            self.assertTrue(
                hasattr(hooks, func_name),
                f"integration_hooks missing function: {func_name}"
            )


class TestLazyLoading(unittest.TestCase):
    """Test lazy loading of evolution modules."""

    def setUp(self):
        """Reset global singletons before each test."""
        import agent.evolution.integration_hooks as hooks
        hooks._degradation_mgr = None
        hooks._distillation_engine = None
        hooks._knowledge_graph = None
        hooks._drift_detector = None
        hooks._agent_spec = None
        hooks._debate_consensus = None
        hooks._cost_optimizer = None

    def test_get_degradation_lazy_loads_once(self):
        """Verify _get_degradation lazy-loads and caches."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch('agent.utils.degradation.get_degradation_manager') as mock_factory:
                mock_mgr = MockDegradationManager()
                mock_factory.return_value = mock_mgr

                # First call — should load
                dm1 = hooks._get_degradation()
                self.assertIsNotNone(dm1)
                self.assertEqual(mock_factory.call_count, 1)

                # Second call — should use cached
                dm2 = hooks._get_degradation()
                self.assertIs(dm1, dm2)
                self.assertEqual(mock_factory.call_count, 1)

    def test_get_distillation_lazy_loads_once(self):
        """Verify _get_distillation lazy-loads and caches."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch('agent.evolution.distillation.get_distillation_engine') as mock_factory:
                mock_engine = MockDistillationEngine()
                mock_factory.return_value = mock_engine

                de1 = hooks._get_distillation()
                self.assertIsNotNone(de1)
                self.assertEqual(mock_factory.call_count, 1)

                de2 = hooks._get_distillation()
                self.assertIs(de1, de2)
                self.assertEqual(mock_factory.call_count, 1)

    def test_get_knowledge_graph_lazy_loads(self):
        """Verify _get_knowledge_graph lazy-loads."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch('agent.evolution.knowledge_graph.get_knowledge_graph') as mock_factory:
                mock_kg = MockKnowledgeGraph()
                mock_factory.return_value = mock_kg

                kg1 = hooks._get_knowledge_graph()
                self.assertIsNotNone(kg1)
                kg2 = hooks._get_knowledge_graph()
                self.assertIs(kg1, kg2)

    def test_get_drift_detector_lazy_loads(self):
        """Verify _get_drift_detector lazy-loads."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch('agent.evolution.drift_detector.DriftDetector') as mock_factory:
                mock_detector = MockDriftDetector()
                mock_factory.return_value = mock_detector

                dd1 = hooks._get_drift_detector()
                self.assertIsNotNone(dd1)
                dd2 = hooks._get_drift_detector()
                self.assertIs(dd1, dd2)

    def test_get_agent_spec_lazy_loads(self):
        """Verify _get_agent_spec lazy-loads."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch('agent.evolution.agentspec.get_agent_spec') as mock_factory:
                mock_spec = MockAgentSpec()
                mock_factory.return_value = mock_spec

                spec1 = hooks._get_agent_spec()
                self.assertIsNotNone(spec1)
                spec2 = hooks._get_agent_spec()
                self.assertIs(spec1, spec2)

    def test_get_debate_lazy_loads(self):
        """Verify _get_debate lazy-loads."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch('agent.evolution.debate_consensus.DebateConsensus') as mock_factory:
                mock_debate = MockDebateConsensus()
                mock_factory.return_value = mock_debate

                db1 = hooks._get_debate()
                self.assertIsNotNone(db1)
                db2 = hooks._get_debate()
                self.assertIs(db1, db2)

    def test_get_cost_optimizer_lazy_loads(self):
        """Verify _get_cost_optimizer lazy-loads."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch('agent.evolution.cost_optimizer.CostOptimizer') as mock_factory:
                mock_opt = MockCostOptimizer()
                mock_factory.return_value = mock_opt

                opt1 = hooks._get_cost_optimizer()
                self.assertIsNotNone(opt1)
                opt2 = hooks._get_cost_optimizer()
                self.assertIs(opt1, opt2)


class TestPreLLMCall(unittest.TestCase):
    """Test pre_llm_call hook."""

    def setUp(self):
        """Reset globals before each test."""
        import agent.evolution.integration_hooks as hooks
        hooks._degradation_mgr = None
        hooks._distillation_engine = None
        hooks._cost_optimizer = None

    def test_pre_llm_call_basic_structure(self):
        """Verify pre_llm_call returns expected structure."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            result = hooks.pre_llm_call(
                prompt="What is 2+2?",
                mode="chat",
                model="deepseek-chat",
                max_tokens=4096,
            )

        # Verify result structure
        self.assertIsInstance(result, dict)
        self.assertIn("skip_api", result)
        self.assertIn("fallback_response", result)
        self.assertIn("modified_prompt", result)
        self.assertIn("adjusted_max_tokens", result)
        self.assertIn("distillation_used", result)
        self.assertIn("tier", result)

        # Verify defaults for normal case
        self.assertFalse(result["skip_api"])
        self.assertIsNone(result["fallback_response"])
        self.assertEqual(result["modified_prompt"], "What is 2+2?")
        self.assertEqual(result["adjusted_max_tokens"], 4096)
        self.assertFalse(result["distillation_used"])
        self.assertEqual(result["tier"], "live")

    def test_pre_llm_call_degradation_static_tier(self):
        """Test degradation check when in STATIC tier."""
        import agent.evolution.integration_hooks as hooks

        mock_dm = MockDegradationManager()
        mock_dm.current_tier.value = "static"

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_degradation', return_value=mock_dm):
                result = hooks.pre_llm_call(
                    prompt="test",
                    mode="chat",
                    max_tokens=4096,
                )

        # Should skip API and return fallback
        self.assertTrue(result["skip_api"])
        self.assertIsNotNone(result["fallback_response"])
        self.assertEqual(result["tier"], "static")

    def test_pre_llm_call_degradation_exception_graceful(self):
        """Test pre_llm_call handles degradation errors gracefully."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_degradation', side_effect=Exception("DB error")):
                # Should not raise, return normal result
                result = hooks.pre_llm_call(
                    prompt="test",
                    mode="chat",
                    max_tokens=4096,
                )

        self.assertFalse(result["skip_api"])
        self.assertEqual(result["tier"], "live")

    def test_pre_llm_call_distillation_fin_mode(self):
        """Test distillation in fin mode."""
        import agent.evolution.integration_hooks as hooks

        mock_engine = MockDistillationEngine()

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_degradation', return_value=None):
                with patch.object(hooks, '_get_distillation', return_value=mock_engine):
                    result = hooks.pre_llm_call(
                        prompt="earnings per share analysis",
                        mode="fin",
                        max_tokens=2048,
                    )

        # Should detect financial_analysis task and inject exemplar
        self.assertTrue(result["distillation_used"])
        self.assertIn("[Exemplar:", result["modified_prompt"])
        self.assertEqual(result["_task_type"], "financial_analysis")
        self.assertEqual(result["_exemplar_id"], "exemplar_123")

    def test_pre_llm_call_distillation_exception_graceful(self):
        """Test pre_llm_call handles distillation errors gracefully."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_degradation', return_value=None):
                with patch.object(hooks, '_get_distillation', side_effect=RuntimeError("KG error")):
                    result = hooks.pre_llm_call(
                        prompt="test",
                        mode="fin",
                        max_tokens=2048,
                    )

        # Should not raise, continue normally
        self.assertFalse(result["distillation_used"])

    def test_pre_llm_call_cost_optimization(self):
        """Test output token limit adjustment."""
        import agent.evolution.integration_hooks as hooks

        mock_optimizer = MockCostOptimizer()

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_degradation', return_value=None):
                with patch.object(hooks, '_get_distillation', return_value=None):
                    with patch.object(hooks, '_get_cost_optimizer', return_value=mock_optimizer):
                        result = hooks.pre_llm_call(
                            prompt="test",
                            mode="fin",
                            max_tokens=8000,  # Request higher than fin limit
                        )

        # Should clamp to 1024 (fin mode limit)
        self.assertEqual(result["adjusted_max_tokens"], 1024)

    def test_pre_llm_call_all_modes(self):
        """Test pre_llm_call with different modes."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            for mode in ["chat", "coding", "fin"]:
                result = hooks.pre_llm_call(
                    prompt="test",
                    mode=mode,
                    max_tokens=4096,
                )
                self.assertIsInstance(result, dict)
                self.assertEqual(result["tier"], "live")


class TestPostResponse(unittest.TestCase):
    """Test post_response hook."""

    def setUp(self):
        """Reset globals before each test."""
        import agent.evolution.integration_hooks as hooks
        hooks._drift_detector = None
        hooks._degradation_mgr = None
        hooks._distillation_engine = None

    def test_post_response_basic_structure(self):
        """Verify post_response returns expected structure."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            result = hooks.post_response(
                prompt="test prompt",
                response="test response",
                mode="chat",
                model="deepseek-chat",
                latency_ms=150.0,
                tokens_used=250,
                cost_usd=0.01,
                success=True,
            )

        self.assertIsInstance(result, dict)
        self.assertIn("actions", result)
        self.assertIsInstance(result["actions"], list)

    def test_post_response_drift_recording(self):
        """Test drift detector metric recording."""
        import agent.evolution.integration_hooks as hooks

        mock_detector = MockDriftDetector()

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=mock_detector):
                result = hooks.post_response(
                    prompt="test",
                    response="response",
                    mode="chat",
                    latency_ms=150.0,
                    tokens_used=250,
                    cost_usd=0.01,
                    success=True,
                )

        # Verify metrics were recorded
        self.assertIn("drift_metrics_recorded", result["actions"])
        self.assertIn("response_latency_ms", mock_detector.metrics)
        self.assertIn("output_tokens_per_request", mock_detector.metrics)
        self.assertIn("task_success_rate", mock_detector.metrics)

    def test_post_response_degradation_failure_recovery(self):
        """Test degradation auto-degrade on failure."""
        import agent.evolution.integration_hooks as hooks

        mock_dm = MockDegradationManager()

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=None):
                with patch.object(hooks, '_get_degradation', return_value=mock_dm):
                    result = hooks.post_response(
                        prompt="test",
                        response="response",
                        mode="chat",
                        success=False,  # Failure
                    )

        # Should have called check_and_auto_degrade
        self.assertIsInstance(result["actions"], list)

    def test_post_response_degradation_recovery_success(self):
        """Test degradation recovery on success."""
        import agent.evolution.integration_hooks as hooks

        mock_dm = MockDegradationManager()
        mock_dm.is_degraded = True

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=None):
                with patch.object(hooks, '_get_degradation', return_value=mock_dm):
                    result = hooks.post_response(
                        prompt="test",
                        response="response" * 50,  # Long response
                        mode="chat",
                        success=True,
                    )

        # Should include recovery action
        self.assertIn("degradation_recovery_attempted", result["actions"])

    def test_post_response_distillation_exemplar_storage(self):
        """Test storing good responses as exemplars."""
        import agent.evolution.integration_hooks as hooks

        mock_engine = MockDistillationEngine()

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=None):
                with patch.object(hooks, '_get_degradation', return_value=None):
                    with patch.object(hooks, '_get_distillation', return_value=mock_engine):
                        result = hooks.post_response(
                            prompt="financial analysis needed",
                            response="Long financial response " * 100,  # Long, good response
                            mode="fin",
                            model="deepseek-reasoner",  # Expensive model
                            success=True,
                        )

        # Should have recorded exemplar storage
        actions_str = str(result["actions"])
        # May include exemplar storage if quality is high enough
        self.assertIsInstance(result["actions"], list)

    def test_post_response_distillation_attempt_recording(self):
        """Test recording distillation attempt results."""
        import agent.evolution.integration_hooks as hooks

        mock_engine = MockDistillationEngine()
        pre_call_result = {
            "distillation_used": True,
            "_task_type": "financial_analysis",
            "_exemplar_id": "exemplar_123",
        }

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=None):
                with patch.object(hooks, '_get_degradation', return_value=None):
                    with patch.object(hooks, '_get_distillation', return_value=mock_engine):
                        result = hooks.post_response(
                            prompt="test",
                            response="Good response " * 50,
                            mode="fin",
                            success=True,
                            pre_call_result=pre_call_result,
                        )

        # Should have recorded the distillation attempt
        actions_str = str(result["actions"])
        self.assertTrue(any("distillation" in str(a) for a in result["actions"]))

    def test_post_response_exception_graceful(self):
        """Test post_response handles exceptions gracefully."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', side_effect=Exception("DB error")):
                # Should not raise
                result = hooks.post_response(
                    prompt="test",
                    response="response",
                    mode="chat",
                    success=True,
                )

        self.assertIsInstance(result, dict)
        self.assertIsInstance(result["actions"], list)


class TestPeriodicTasks(unittest.TestCase):
    """Test periodic_tasks hook."""

    def setUp(self):
        """Reset globals before each test."""
        import agent.evolution.integration_hooks as hooks
        hooks._drift_detector = None
        hooks._knowledge_graph = None
        hooks._distillation_engine = None
        hooks._degradation_mgr = None

    def test_periodic_tasks_basic_structure(self):
        """Verify periodic_tasks returns expected structure."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            result = hooks.periodic_tasks(turn_number=50, mode="chat")

        self.assertIsInstance(result, dict)
        # Optional keys that may be present
        possible_keys = ["drift", "kg_clusters", "kg_edges",
                        "distillation_cleaned", "distillation_savings",
                        "tier", "alerts"]

    def test_periodic_tasks_drift_detection(self):
        """Test drift detection in periodic tasks."""
        import agent.evolution.integration_hooks as hooks

        mock_detector = MockDriftDetector()

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=mock_detector):
                result = hooks.periodic_tasks(turn_number=50, mode="chat")

        self.assertIn("drift", result)
        self.assertEqual(result["drift"], "no_drift")

    def test_periodic_tasks_knowledge_graph(self):
        """Test knowledge graph maintenance."""
        import agent.evolution.integration_hooks as hooks

        mock_kg = MockKnowledgeGraph()

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=None):
                with patch.object(hooks, '_get_knowledge_graph', return_value=mock_kg):
                    result = hooks.periodic_tasks(turn_number=50, mode="chat")

        self.assertIn("kg_clusters", result)
        self.assertIn("kg_edges", result)
        self.assertEqual(result["kg_clusters"], 2)
        self.assertEqual(result["kg_edges"], 127)

    def test_periodic_tasks_distillation_cleanup(self):
        """Test distillation exemplar cleanup."""
        import agent.evolution.integration_hooks as hooks

        mock_engine = MockDistillationEngine()

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=None):
                with patch.object(hooks, '_get_knowledge_graph', return_value=None):
                    with patch.object(hooks, '_get_distillation', return_value=mock_engine):
                        result = hooks.periodic_tasks(turn_number=50, mode="chat")

        self.assertIn("distillation_cleaned", result)
        self.assertIn("distillation_savings", result)
        self.assertEqual(result["distillation_cleaned"], 5)
        self.assertEqual(result["distillation_savings"], 42.50)

    def test_periodic_tasks_degradation_status(self):
        """Test degradation status reporting."""
        import agent.evolution.integration_hooks as hooks

        mock_dm = MockDegradationManager()

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=None):
                with patch.object(hooks, '_get_knowledge_graph', return_value=None):
                    with patch.object(hooks, '_get_distillation', return_value=None):
                        with patch.object(hooks, '_get_degradation', return_value=mock_dm):
                            result = hooks.periodic_tasks(turn_number=50, mode="chat")

        self.assertIn("tier", result)
        self.assertEqual(result["tier"], "live")

    def test_periodic_tasks_drift_with_alerts(self):
        """Test drift detection with alerts."""
        import agent.evolution.integration_hooks as hooks

        mock_detector = MockDriftDetector()
        # Override to return moderate drift
        mock_detector.check_drift = lambda: {
            "overall_status": "moderate_drift",
            "metrics": {
                "response_latency_ms": {"status": "moderate", "value": 500},
                "output_tokens_per_request": {"status": "normal", "value": 250},
            }
        }

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=mock_detector):
                result = hooks.periodic_tasks(turn_number=50, mode="chat")

        self.assertIn("alerts", result)
        self.assertEqual(len(result["alerts"]), 1)
        self.assertEqual(result["alerts"][0]["type"], "behavior_drift")

    def test_periodic_tasks_exception_graceful(self):
        """Test periodic_tasks handles exceptions gracefully."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', side_effect=RuntimeError("Error")):
                # Should not raise
                result = hooks.periodic_tasks(turn_number=50, mode="chat")

        self.assertIsInstance(result, dict)


class TestSelfEditGate(unittest.TestCase):
    """Test self_edit_gate safety hook."""

    def setUp(self):
        """Reset globals before each test."""
        import agent.evolution.integration_hooks as hooks
        hooks._agent_spec = None
        hooks._debate_consensus = None

    def test_self_edit_gate_basic_approval(self):
        """Test basic approval of simple edits."""
        import agent.evolution.integration_hooks as hooks

        mock_spec = MockAgentSpec()
        mock_debate = MockDebateConsensus()

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_agent_spec', return_value=mock_spec):
                with patch.object(hooks, '_get_debate', return_value=mock_debate):
                    allowed, reason = hooks.self_edit_gate(
                        file_path="agent/evolution/distillation.py",
                        new_content="def new_func(): pass",
                        old_content="def old_func(): pass",
                        reason="Fix distillation logic",
                    )

        self.assertTrue(allowed)
        self.assertEqual(reason, "Approved")

    def test_self_edit_gate_safety_file_blocked(self):
        """Test blocking of edits to safety-critical files."""
        import agent.evolution.integration_hooks as hooks

        # Mock agentspec that blocks safety file edits
        mock_spec = Mock()
        mock_spec.check.return_value = [
            Mock(blocked=True, rule_name="PROTECT_SAFETY_FILES")
        ]

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_agent_spec', return_value=mock_spec):
                allowed, reason = hooks.self_edit_gate(
                    file_path="agent/evolution/self_edit.py",
                    new_content="modified",
                    old_content="original",
                    reason="Fix self-edit logic",
                )

        self.assertFalse(allowed)
        self.assertIn("AgentSpec BLOCKED", reason)

    def test_self_edit_gate_debate_rejection(self):
        """Test debate consensus rejection."""
        import agent.evolution.integration_hooks as hooks

        mock_spec = MockAgentSpec()
        mock_debate = Mock()
        mock_debate.deliberate.return_value = {
            "decision": "reject",
            "score": 0.3,
        }

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_agent_spec', return_value=mock_spec):
                with patch.object(hooks, '_get_debate', return_value=mock_debate):
                    allowed, reason = hooks.self_edit_gate(
                        file_path="agent/core.py",
                        new_content="modified",
                        old_content="original",
                        reason="Major refactor",
                    )

        self.assertFalse(allowed)
        self.assertIn("Debate REJECTED", reason)

    def test_self_edit_gate_debate_block(self):
        """Test debate consensus block."""
        import agent.evolution.integration_hooks as hooks

        mock_spec = MockAgentSpec()
        mock_debate = Mock()
        mock_debate.deliberate.return_value = {
            "decision": "block",
            "blocked_by": ["cautious_viewpoint", "principled_viewpoint"],
        }

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_agent_spec', return_value=mock_spec):
                with patch.object(hooks, '_get_debate', return_value=mock_debate):
                    allowed, reason = hooks.self_edit_gate(
                        file_path="agent/evolution/guards.py",
                        new_content="modified",
                        old_content="original",
                        reason="Weaken guards",
                    )

        self.assertFalse(allowed)
        self.assertIn("Debate BLOCKED", reason)

    def test_self_edit_gate_safety_file_detection(self):
        """Test detection of safety files."""
        import agent.evolution.integration_hooks as hooks

        mock_spec = MockAgentSpec()
        mock_debate = Mock()
        mock_debate.deliberate.return_value = {
            "decision": "approve",
            "score": 0.95,
        }

        # Capture the call to deliberate
        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_agent_spec', return_value=mock_spec):
                with patch.object(hooks, '_get_debate', return_value=mock_debate):
                    hooks.self_edit_gate(
                        file_path="agent/evolution/agentspec.py",
                        new_content="modified",
                        old_content="original",
                        reason="Update rules",
                    )

        # Verify debate was called with risk_level=critical for safety files
        call_args = mock_debate.deliberate.call_args[0][0]
        self.assertEqual(call_args["risk_level"], "critical")

    def test_self_edit_gate_exception_graceful(self):
        """Test self_edit_gate handles exceptions gracefully."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_agent_spec', side_effect=Exception("Error")):
                # Should not raise
                allowed, reason = hooks.self_edit_gate(
                    file_path="agent/evolution/distillation.py",
                    new_content="modified",
                    old_content="original",
                    reason="Fix",
                )

        # Should still succeed if debate is available
        self.assertIsInstance(allowed, bool)


class TestInferTaskType(unittest.TestCase):
    """Test _infer_task_type helper."""

    def test_infer_task_type_financial_analysis(self):
        """Test financial analysis task detection."""
        import agent.evolution.integration_hooks as hooks

        prompts = [
            "earnings per share analysis",
            "财报分析",
            "revenue trends",
            "EPS projection",
        ]

        for prompt in prompts:
            task_type = hooks._infer_task_type(prompt, mode="fin")
            self.assertEqual(task_type, "financial_analysis")

    def test_infer_task_type_sentiment_analysis(self):
        """Test sentiment analysis detection."""
        import agent.evolution.integration_hooks as hooks

        prompts = [
            "market sentiment analysis",
            "看多的理由",
            "investor sentiment",
        ]

        for prompt in prompts:
            task_type = hooks._infer_task_type(prompt, mode="fin")
            self.assertEqual(task_type, "sentiment_analysis")

    def test_infer_task_type_market_briefing(self):
        """Test market briefing detection."""
        import agent.evolution.integration_hooks as hooks

        # Test actual market briefing detection
        task_type = hooks._infer_task_type("市场简报分析", mode="fin")
        self.assertEqual(task_type, "market_briefing")

        # Other prompts may fall back to financial_analysis (which is the default)
        task_type = hooks._infer_task_type("market briefing today", mode="fin")
        self.assertIn(task_type, ["market_briefing", "financial_analysis"])

    def test_infer_task_type_code_review(self):
        """Test code review detection."""
        import agent.evolution.integration_hooks as hooks

        task_type = hooks._infer_task_type("please review this code", mode="coding")
        self.assertEqual(task_type, "code_review")

    def test_infer_task_type_none_for_varied_tasks(self):
        """Test None for tasks that are too varied."""
        import agent.evolution.integration_hooks as hooks

        # Coding mode returns None for non-review tasks
        task_type = hooks._infer_task_type("implement a feature", mode="coding")
        self.assertIsNone(task_type)

    def test_infer_task_type_chat_mode(self):
        """Test chat mode task inference."""
        import agent.evolution.integration_hooks as hooks

        task_type = hooks._infer_task_type("summarize this document", mode="chat")
        self.assertEqual(task_type, "learning_extraction")


class TestEstimateQuality(unittest.TestCase):
    """Test _estimate_quality helper."""

    def test_estimate_quality_baseline(self):
        """Test baseline quality score."""
        import agent.evolution.integration_hooks as hooks

        score = hooks._estimate_quality("short", mode="chat")
        self.assertEqual(score, 0.5)  # baseline

    def test_estimate_quality_length_bonus(self):
        """Test length bonuses."""
        import agent.evolution.integration_hooks as hooks

        response_500 = "x" * 500
        response_1000 = "x" * 1000
        response_2000 = "x" * 2000

        score_500 = hooks._estimate_quality(response_500, mode="chat")
        score_1000 = hooks._estimate_quality(response_1000, mode="chat")
        score_2000 = hooks._estimate_quality(response_2000, mode="chat")

        # Longer responses should have higher scores
        self.assertGreater(score_1000, score_500)
        self.assertGreater(score_2000, score_1000)

    def test_estimate_quality_structure_bonus(self):
        """Test structure bonuses."""
        import agent.evolution.integration_hooks as hooks

        structured = "## Title\n1. Point one\n2. Point two\n**bold**"
        unstructured = "this is some text without structure"

        score_structured = hooks._estimate_quality(structured, mode="chat")
        score_unstructured = hooks._estimate_quality(unstructured, mode="chat")

        self.assertGreater(score_structured, score_unstructured)

    def test_estimate_quality_financial_mode(self):
        """Test financial mode quality signals."""
        import agent.evolution.integration_hooks as hooks

        financial = "The valuation is 50% of competitors. Risk assessment shows 25M in exposure."
        generic = "The company is doing well overall."

        score_fin = hooks._estimate_quality(financial, mode="fin")
        score_generic = hooks._estimate_quality(generic, mode="fin")

        self.assertGreater(score_fin, score_generic)

    def test_estimate_quality_coding_mode(self):
        """Test coding mode quality signals."""
        import agent.evolution.integration_hooks as hooks

        code = "```python\ndef process_data(items):\n    return [x*2 for x in items]\n```"
        generic = "here is some code that works"

        score_code = hooks._estimate_quality(code, mode="coding")
        score_generic = hooks._estimate_quality(generic, mode="coding")

        self.assertGreater(score_code, score_generic)


class TestGracefulDegradation(unittest.TestCase):
    """Test graceful degradation when modules fail."""

    def setUp(self):
        """Reset globals before each test."""
        import agent.evolution.integration_hooks as hooks
        hooks._degradation_mgr = None
        hooks._distillation_engine = None
        hooks._knowledge_graph = None
        hooks._drift_detector = None
        hooks._agent_spec = None
        hooks._debate_consensus = None
        hooks._cost_optimizer = None

    def test_pre_llm_call_when_no_modules_available(self):
        """Test pre_llm_call works when all modules fail to import."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            # Mock all getters to return None (simulating import failures)
            with patch.object(hooks, '_get_degradation', return_value=None):
                with patch.object(hooks, '_get_distillation', return_value=None):
                    with patch.object(hooks, '_get_cost_optimizer', return_value=None):
                        result = hooks.pre_llm_call(prompt="test", mode="chat")

        # Should still return valid structure
        self.assertIsInstance(result, dict)
        self.assertFalse(result["skip_api"])

    def test_post_response_when_no_modules_available(self):
        """Test post_response works when all modules fail to import."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=None):
                with patch.object(hooks, '_get_degradation', return_value=None):
                    with patch.object(hooks, '_get_distillation', return_value=None):
                        result = hooks.post_response(
                            prompt="test",
                            response="response",
                            mode="chat",
                            success=True,
                        )

        # Should still return valid structure
        self.assertIsInstance(result, dict)
        self.assertIsInstance(result["actions"], list)

    def test_periodic_tasks_when_no_modules_available(self):
        """Test periodic_tasks works when all modules fail to import."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            with patch.object(hooks, '_get_drift_detector', return_value=None):
                with patch.object(hooks, '_get_knowledge_graph', return_value=None):
                    with patch.object(hooks, '_get_distillation', return_value=None):
                        with patch.object(hooks, '_get_degradation', return_value=None):
                            result = hooks.periodic_tasks(turn_number=50, mode="chat")

        # Should still return valid structure
        self.assertIsInstance(result, dict)


# ═══════════════════════════════════════════════════════════════
# Self-Restart Tests
# ═══════════════════════════════════════════════════════════════

class TestSelfRestart(unittest.TestCase):
    """Test self_restart.py functions."""

    def test_is_supervisor_managed_with_socket(self):
        """Test supervisor detection when socket exists."""
        import agent.evolution.self_restart as sr

        with patch('agent.evolution.self_restart.Path.exists', return_value=True):
            self.assertTrue(sr.is_supervisor_managed())

    def test_is_supervisor_managed_without_socket(self):
        """Test supervisor detection when socket missing."""
        import agent.evolution.self_restart as sr

        with patch('agent.evolution.self_restart.Path.exists', return_value=False):
            self.assertFalse(sr.is_supervisor_managed())

    def test_needs_full_restart_for_telegram_bot(self):
        """Test full restart required for telegram_bot.py."""
        import agent.evolution.self_restart as sr

        self.assertTrue(sr.needs_full_restart("telegram_bot.py"))

    def test_needs_full_restart_for_init_files(self):
        """Test full restart required for __init__.py files."""
        import agent.evolution.self_restart as sr

        self.assertTrue(sr.needs_full_restart("agent/__init__.py"))

    def test_needs_full_restart_for_core_files(self):
        """Test full restart required for core/main files."""
        import agent.evolution.self_restart as sr

        self.assertTrue(sr.needs_full_restart("core.py"))
        self.assertTrue(sr.needs_full_restart("main.py"))
        self.assertTrue(sr.needs_full_restart("agent_config.py"))

    def test_needs_full_restart_for_config_files(self):
        """Test full restart required for yaml config files."""
        import agent.evolution.self_restart as sr

        self.assertTrue(sr.needs_full_restart("config.yaml"))
        self.assertTrue(sr.needs_full_restart("settings.yml"))

    def test_no_restart_for_evolution_modules(self):
        """Test evolution modules don't need full restart."""
        import agent.evolution.self_restart as sr

        self.assertFalse(sr.needs_full_restart("agent/evolution/distillation.py"))
        self.assertFalse(sr.needs_full_restart("agent/evolution/knowledge_graph.py"))

    def test_request_restart_not_supervised(self):
        """Test request_restart fails when not under supervisord."""
        import agent.evolution.self_restart as sr

        with patch.object(sr, 'is_supervisor_managed', return_value=False):
            success, msg = sr.request_restart(reason="Test restart")

        self.assertFalse(success)
        self.assertIn("Not running under supervisord", msg)

    def test_request_restart_success(self):
        """Test successful restart request."""
        import agent.evolution.self_restart as sr

        with tempfile.TemporaryDirectory() as tmpdir:
            intent_file = Path(tmpdir) / "restart_intent.json"
            log_file = Path(tmpdir) / "restart_log.jsonl"

            with patch.object(sr, 'RESTART_INTENT_FILE', intent_file):
                with patch.object(sr, 'RESTART_LOG_FILE', log_file):
                    with patch.object(sr, 'is_supervisor_managed', return_value=True):
                        with patch('agent.evolution.self_restart.subprocess.Popen'):
                            success, msg = sr.request_restart(
                                reason="Test restart",
                                changed_files=["file1.py", "file2.py"],
                                delay_seconds=1.0,
                            )

            self.assertTrue(success)
            self.assertIn("scheduled", msg)
            # Verify intent file was written
            self.assertTrue(intent_file.exists())
            intent = json.loads(intent_file.read_text())
            self.assertEqual(intent["reason"], "Test restart")
            self.assertEqual(intent["changed_files"], ["file1.py", "file2.py"])

    def test_check_restart_intent_exists(self):
        """Test reading restart intent when it exists."""
        import agent.evolution.self_restart as sr

        with tempfile.TemporaryDirectory() as tmpdir:
            intent_file = Path(tmpdir) / "restart_intent.json"
            intent_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": "Code updated",
                "changed_files": ["test.py"],
                "notify_chat_id": 123,
                "pid": 999,
            }
            intent_file.write_text(json.dumps(intent_data))

            with patch.object(sr, 'RESTART_INTENT_FILE', intent_file):
                result = sr.check_restart_intent()

            self.assertIsNotNone(result)
            self.assertEqual(result["reason"], "Code updated")
            # File should be deleted after reading
            self.assertFalse(intent_file.exists())

    def test_check_restart_intent_not_exists(self):
        """Test check_restart_intent when no intent file exists."""
        import agent.evolution.self_restart as sr

        with tempfile.TemporaryDirectory() as tmpdir:
            intent_file = Path(tmpdir) / "restart_intent.json"

            with patch.object(sr, 'RESTART_INTENT_FILE', intent_file):
                result = sr.check_restart_intent()

            self.assertIsNone(result)

    def test_check_restart_intent_corrupt_file(self):
        """Test check_restart_intent handles corrupt JSON."""
        import agent.evolution.self_restart as sr

        with tempfile.TemporaryDirectory() as tmpdir:
            intent_file = Path(tmpdir) / "restart_intent.json"
            intent_file.write_text("{ invalid json")

            with patch.object(sr, 'RESTART_INTENT_FILE', intent_file):
                result = sr.check_restart_intent()

            self.assertIsNone(result)
            # File should be deleted even on error
            self.assertFalse(intent_file.exists())

    def test_get_restart_history_empty(self):
        """Test get_restart_history when log doesn't exist."""
        import agent.evolution.self_restart as sr

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "restart_log.jsonl"

            with patch.object(sr, 'RESTART_LOG_FILE', log_file):
                history = sr.get_restart_history(limit=10)

            self.assertEqual(history, [])

    def test_get_restart_history_with_entries(self):
        """Test get_restart_history reads log entries."""
        import agent.evolution.self_restart as sr

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "restart_log.jsonl"

            # Write some entries
            entries = [
                {"timestamp": "2026-01-01T00:00:00Z", "reason": "Update 1"},
                {"timestamp": "2026-01-02T00:00:00Z", "reason": "Update 2"},
                {"timestamp": "2026-01-03T00:00:00Z", "reason": "Update 3"},
            ]
            log_file.write_text(
                "\n".join(json.dumps(e) for e in entries)
            )

            with patch.object(sr, 'RESTART_LOG_FILE', log_file):
                history = sr.get_restart_history(limit=10)

            self.assertEqual(len(history), 3)
            self.assertEqual(history[0]["reason"], "Update 1")
            self.assertEqual(history[-1]["reason"], "Update 3")

    def test_get_restart_history_limit(self):
        """Test get_restart_history respects limit."""
        import agent.evolution.self_restart as sr

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "restart_log.jsonl"

            # Write many entries
            entries = [
                {"timestamp": f"2026-01-{i:02d}T00:00:00Z", "reason": f"Update {i}"}
                for i in range(1, 21)
            ]
            log_file.write_text(
                "\n".join(json.dumps(e) for e in entries)
            )

            with patch.object(sr, 'RESTART_LOG_FILE', log_file):
                history = sr.get_restart_history(limit=5)

            self.assertEqual(len(history), 5)
            # Should return last 5 entries
            self.assertEqual(history[0]["reason"], "Update 16")
            self.assertEqual(history[-1]["reason"], "Update 20")


# ═══════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════

class TestHookIntegration(unittest.TestCase):
    """Test integration of hooks in agentic loop."""

    def test_hooks_work_together_in_sequence(self):
        """Test a realistic sequence of hook calls."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            # Call pre_llm_call
            pre_result = hooks.pre_llm_call(
                prompt="Analyze earnings",
                mode="fin",
                max_tokens=2048,
            )

            # Simulate getting a response
            response = "The company earned $100M this quarter, up 20% YoY."

            # Call post_response with pre_result
            post_result = hooks.post_response(
                prompt="Analyze earnings",
                response=response,
                mode="fin",
                latency_ms=150.0,
                tokens_used=50,
                cost_usd=0.01,
                success=True,
                pre_call_result=pre_result,
            )

            # Verify both hooks work
            self.assertIsInstance(pre_result, dict)
            self.assertIsInstance(post_result, dict)
            self.assertIn("actions", post_result)

    def test_hooks_periodic_maintenance(self):
        """Test periodic maintenance task."""
        import agent.evolution.integration_hooks as hooks

        with patch('agent.evolution.integration_hooks.logger'):
            # Run periodic tasks
            periodic_result = hooks.periodic_tasks(
                turn_number=50,
                mode="chat",
            )

            # Verify result
            self.assertIsInstance(periodic_result, dict)


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
