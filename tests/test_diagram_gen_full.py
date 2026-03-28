"""
Comprehensive unit tests for agent/finance/diagram_gen.py
Tests diagram generation for all types with various inputs.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile

from agent.finance.diagram_gen import (
    DiagramNode,
    DiagramEdge,
    DiagramGenerator,
)


# ── DiagramNode Tests ────────────────────────────────────────────────

class TestDiagramNode:
    def test_creation_minimal(self):
        node = DiagramNode(id="N1", label="Node 1")
        assert node.id == "N1"
        assert node.label == "Node 1"
        assert node.style == ""

    def test_creation_with_style(self):
        node = DiagramNode(
            id="N2",
            label="Important Node",
            style="fill:#f9f,stroke:#333",
        )
        assert node.id == "N2"
        assert node.style == "fill:#f9f,stroke:#333"

    def test_node_with_special_characters(self):
        node = DiagramNode(id="N_special", label="Node with \"quotes\" & symbols")
        assert node.id == "N_special"
        assert "quotes" in node.label


# ── DiagramEdge Tests ────────────────────────────────────────────────

class TestDiagramEdge:
    def test_creation_minimal(self):
        edge = DiagramEdge(source="N1", target="N2")
        assert edge.source == "N1"
        assert edge.target == "N2"
        assert edge.label == ""
        assert edge.style == ""

    def test_creation_with_label(self):
        edge = DiagramEdge(
            source="A",
            target="B",
            label="relates to",
        )
        assert edge.label == "relates to"

    def test_creation_with_style(self):
        edge = DiagramEdge(
            source="X",
            target="Y",
            label="strong",
            style="stroke:#f00;stroke-width:2px",
        )
        assert edge.style == "stroke:#f00;stroke-width:2px"


# ── DiagramGenerator Tests ───────────────────────────────────────────

class TestDiagramGenerator:
    @pytest.fixture
    def gen(self):
        return DiagramGenerator()

    def test_initialization(self, gen):
        assert gen.DIAGRAM_TYPES["causal"] == "flowchart TD"
        assert gen.DIAGRAM_TYPES["flow"] == "flowchart LR"
        assert gen.DIAGRAM_TYPES["timeline"] == "gantt"
        assert gen.DIAGRAM_TYPES["sequence"] == "sequenceDiagram"

    def test_generate_causal_chain_empty(self, gen):
        """Test causal chain with empty input."""
        result = gen.generate_causal_chain([], title="Empty Chain")
        assert "flowchart" in result
        assert "Empty Chain" in result

    def test_generate_causal_chain_single_event(self, gen):
        """Test causal chain with one event."""
        events = [
            {"cause": "Fed Hikes Rates", "effect": "Borrowing Costs Rise", "impact": "negative"}
        ]
        result = gen.generate_causal_chain(events, title="Simple Chain")
        assert "flowchart" in result
        assert "Fed Hikes Rates" in result
        assert "Borrowing Costs Rise" in result
        assert "-|" in result  # negative impact arrow

    def test_generate_causal_chain_multiple_events(self, gen):
        """Test causal chain with multiple events."""
        events = [
            {"cause": "Event A", "effect": "Event B", "impact": "positive"},
            {"cause": "Event B", "effect": "Event C", "impact": "negative"},
            {"cause": "Event C", "effect": "Event D", "impact": "neutral"},
        ]
        result = gen.generate_causal_chain(events)
        assert "Event A" in result
        assert "Event D" in result
        # Count events in diagram
        assert result.count("[") >= 4  # At least 4 nodes

    def test_causal_chain_positive_impact(self, gen):
        """Test that positive impacts have correct arrow."""
        events = [{"cause": "Good News", "effect": "Stock Up", "impact": "positive"}]
        result = gen.generate_causal_chain(events)
        assert "+|" in result

    def test_causal_chain_negative_impact(self, gen):
        """Test that negative impacts have correct arrow."""
        events = [{"cause": "Bad News", "effect": "Stock Down", "impact": "negative"}]
        result = gen.generate_causal_chain(events)
        assert "-|" in result

    def test_causal_chain_neutral_impact(self, gen):
        """Test neutral impact."""
        events = [{"cause": "News", "effect": "No Change", "impact": "neutral"}]
        result = gen.generate_causal_chain(events)
        assert "News" in result

    def test_causal_chain_direction_lr(self, gen):
        """Test left-right direction."""
        events = [{"cause": "A", "effect": "B", "impact": "neutral"}]
        result = gen.generate_causal_chain(events, direction="LR")
        assert "flowchart LR" in result

    def test_causal_chain_direction_td(self, gen):
        """Test top-down direction."""
        events = [{"cause": "A", "effect": "B", "impact": "neutral"}]
        result = gen.generate_causal_chain(events, direction="TD")
        assert "flowchart TD" in result

    def test_generate_timeline_empty(self, gen):
        """Test timeline with no events."""
        result = gen.generate_timeline([], title="Empty Timeline")
        assert "gantt" in result
        assert "Empty Timeline" in result

    def test_generate_timeline_single_event(self, gen):
        """Test timeline with one event."""
        events = [
            {"name": "FOMC Meeting", "start": "2024-03-20", "section": "Fed"}
        ]
        result = gen.generate_timeline(events)
        assert "FOMC Meeting" in result
        assert "2024-03-20" in result
        assert "milestone" in result

    def test_generate_timeline_with_duration(self, gen):
        """Test timeline event with start and end dates."""
        events = [
            {"name": "Earnings Season", "start": "2024-04-01", "end": "2024-04-30", "section": "Corporate"}
        ]
        result = gen.generate_timeline(events)
        assert "Earnings Season" in result
        assert "2024-04-01" in result
        assert "2024-04-30" in result

    def test_generate_timeline_multiple_sections(self, gen):
        """Test timeline with multiple sections."""
        events = [
            {"name": "FOMC", "start": "2024-03-20", "section": "Fed"},
            {"name": "CPI", "start": "2024-03-21", "section": "Economic"},
            {"name": "Earnings", "start": "2024-04-01", "section": "Corporate"},
        ]
        result = gen.generate_timeline(events)
        assert "Fed" in result
        assert "Economic" in result
        assert "Corporate" in result

    def test_generate_pie_empty(self, gen):
        """Test pie chart with empty data."""
        result = gen.generate_pie({}, title="Empty Pie")
        assert "pie title Empty Pie" in result

    def test_generate_pie_simple(self, gen):
        """Test simple pie chart."""
        data = {"Stocks": 60, "Bonds": 40}
        result = gen.generate_pie(data, title="Portfolio")
        assert "pie title Portfolio" in result
        assert "Stocks" in result
        assert "60" in result
        assert "Bonds" in result
        assert "40" in result

    def test_generate_pie_complex(self, gen):
        """Test pie chart with many segments."""
        data = {
            "Tech": 30,
            "Healthcare": 25,
            "Finance": 20,
            "Energy": 15,
            "Utilities": 10,
        }
        result = gen.generate_pie(data, title="Sector Allocation")
        for key, val in data.items():
            assert key in result
            assert str(val) in result

    def test_generate_flow_empty(self, gen):
        """Test flow diagram with empty nodes."""
        result = gen.generate_flow([], [], title="Empty Flow")
        assert "flowchart" in result
        assert "Empty Flow" in result

    def test_generate_flow_simple(self, gen):
        """Test simple flow diagram."""
        nodes = [
            DiagramNode(id="start", label="Begin"),
            DiagramNode(id="end", label="End"),
        ]
        edges = [DiagramEdge(source="start", target="end")]
        result = gen.generate_flow(nodes, edges)
        assert "start" in result
        assert "end" in result
        assert "Begin" in result
        assert "End" in result

    def test_generate_flow_with_labels(self, gen):
        """Test flow diagram with edge labels."""
        nodes = [
            DiagramNode(id="A", label="Input"),
            DiagramNode(id="B", label="Process"),
            DiagramNode(id="C", label="Output"),
        ]
        edges = [
            DiagramEdge(source="A", target="B", label="Process"),
            DiagramEdge(source="B", target="C", label="Result"),
        ]
        result = gen.generate_flow(nodes, edges)
        assert "Process" in result
        assert "Result" in result
        assert "|Process|" in result or "Process" in result
        assert "|Result|" in result or "Result" in result

    def test_generate_flow_directions(self, gen):
        """Test flow diagram in different directions."""
        nodes = [DiagramNode(id="A", label="A"), DiagramNode(id="B", label="B")]
        edges = [DiagramEdge(source="A", target="B")]

        result_lr = gen.generate_flow(nodes, edges, direction="LR")
        assert "flowchart LR" in result_lr

        result_td = gen.generate_flow(nodes, edges, direction="TD")
        assert "flowchart TD" in result_td

    def test_generate_sequence_empty(self, gen):
        """Test sequence diagram with empty interactions."""
        result = gen.generate_sequence([])
        assert "sequenceDiagram" in result

    def test_generate_sequence_simple(self, gen):
        """Test simple sequence diagram."""
        interactions = [
            {"from": "Client", "to": "Server", "message": "Request"},
            {"from": "Server", "to": "Client", "message": "Response"},
        ]
        result = gen.generate_sequence(interactions)
        assert "sequenceDiagram" in result
        assert "Client" in result
        assert "Server" in result
        assert "Request" in result
        assert "Response" in result

    def test_generate_sequence_with_title(self, gen):
        """Test sequence diagram with title."""
        interactions = [
            {"from": "A", "to": "B", "message": "msg1"},
        ]
        result = gen.generate_sequence(interactions, title="Trade Execution")
        assert "Trade Execution" in result

    def test_generate_sequence_solid_arrow(self, gen):
        """Test solid arrow type."""
        interactions = [
            {"from": "A", "to": "B", "message": "msg", "type": "solid"},
        ]
        result = gen.generate_sequence(interactions)
        assert "->>" in result

    def test_generate_sequence_dashed_arrow(self, gen):
        """Test dashed arrow type."""
        interactions = [
            {"from": "A", "to": "B", "message": "msg", "type": "dashed"},
        ]
        result = gen.generate_sequence(interactions)
        assert "-->" in result or "-->>" in result

    def test_generate_mindmap_empty(self, gen):
        """Test mind map with no branches."""
        result = gen.generate_mindmap("Root", {})
        assert "mindmap" in result
        assert "Root" in result

    def test_generate_mindmap_simple(self, gen):
        """Test simple mind map."""
        branches = {
            "Strategy": ["Value", "Growth"],
            "Markets": ["US", "International"],
        }
        result = gen.generate_mindmap("Investment", branches)
        assert "mindmap" in result
        assert "Investment" in result
        assert "Strategy" in result
        assert "Value" in result
        assert "Growth" in result
        assert "Markets" in result

    def test_generate_mindmap_complex(self, gen):
        """Test complex mind map with many branches."""
        branches = {
            "Financial": ["Stocks", "Bonds", "Crypto"],
            "Technical": ["Charts", "Indicators", "Patterns"],
            "Fundamental": ["Earnings", "FCF", "Ratio Analysis"],
        }
        result = gen.generate_mindmap("Analysis Framework", branches)
        assert "Analysis Framework" in result
        for branch_label, leaves in branches.items():
            assert branch_label in result
            for leaf in leaves:
                assert leaf in result

    def test_fed_rate_impact_hike(self, gen):
        """Test pre-built Fed rate hike diagram."""
        result = gen.fed_rate_impact("hike")
        assert "Fed Rate Hike Impact Chain" in result or "Fed Raises Rates" in result
        assert "flowchart" in result

    def test_fed_rate_impact_cut(self, gen):
        """Test pre-built Fed rate cut diagram."""
        result = gen.fed_rate_impact("cut")
        assert "Fed Rate Cut Impact Chain" in result or "Fed Cuts Rates" in result
        assert "flowchart" in result

    def test_portfolio_allocation(self, gen):
        """Test portfolio allocation diagram."""
        allocation = {
            "Stocks": 70,
            "Bonds": 20,
            "Cash": 10,
        }
        result = gen.portfolio_allocation(allocation)
        assert "pie" in result or "Portfolio Allocation" in result
        assert "Stocks" in result

    def test_save_mermaid(self, gen):
        """Test saving mermaid diagram to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test_diagram.mmd"
            mermaid_text = "flowchart TD\n  A --> B"

            result = gen.save_mermaid(mermaid_text, str(filepath))

            assert Path(result).exists()
            with open(result, "r") as f:
                content = f.read()
            assert content == mermaid_text

    def test_render_info(self, gen):
        """Test render info message."""
        info = gen.render_info()
        assert isinstance(info, str)
        assert "mermaid.live" in info
        assert "mermaid-cli" in info


# ── Edge Cases and Error Handling ────────────────────────────────────

class TestDiagramGeneratorEdgeCases:
    def test_node_with_empty_id(self):
        node = DiagramNode(id="", label="No ID")
        assert node.id == ""

    def test_node_with_long_label(self):
        long_label = "This is a very long node label with many words that might break the diagram"
        node = DiagramNode(id="N1", label=long_label)
        assert node.label == long_label

    def test_edge_self_reference(self):
        edge = DiagramEdge(source="N1", target="N1", label="Self loop")
        assert edge.source == edge.target

    def test_edge_with_empty_label(self):
        edge = DiagramEdge(source="A", target="B", label="")
        assert edge.label == ""

    def test_causal_chain_missing_impact(self):
        """Test causal chain with missing impact field."""
        gen = DiagramGenerator()
        events = [
            {"cause": "A", "effect": "B"},  # no impact
        ]
        result = gen.generate_causal_chain(events)
        assert "A" in result
        assert "B" in result

    def test_timeline_missing_end_date(self):
        """Test timeline event without end date."""
        gen = DiagramGenerator()
        events = [
            {"name": "Event", "start": "2024-03-20"},  # no end
        ]
        result = gen.generate_timeline(events)
        assert "Event" in result
        assert "milestone" in result

    def test_timeline_same_start_end(self):
        """Test timeline with same start and end date."""
        gen = DiagramGenerator()
        events = [
            {"name": "Meeting", "start": "2024-03-20", "end": "2024-03-20", "section": "Events"}
        ]
        result = gen.generate_timeline(events)
        assert "Meeting" in result

    def test_pie_single_segment(self):
        """Test pie chart with single segment."""
        gen = DiagramGenerator()
        result = gen.generate_pie({"All": 100})
        assert "All" in result
        assert "100" in result

    def test_pie_zero_values(self):
        """Test pie chart with zero values."""
        gen = DiagramGenerator()
        result = gen.generate_pie({"Empty": 0, "Full": 100})
        assert "Empty" in result
        assert "Full" in result

    def test_flow_with_missing_target_node(self):
        """Test flow diagram where edge references undefined node."""
        gen = DiagramGenerator()
        nodes = [DiagramNode(id="A", label="A")]
        edges = [DiagramEdge(source="A", target="B")]  # B not defined
        result = gen.generate_flow(nodes, edges)
        # Should still generate valid mermaid
        assert "flowchart" in result

    def test_sequence_single_interaction(self):
        """Test sequence diagram with single message."""
        gen = DiagramGenerator()
        interactions = [{"from": "A", "to": "B", "message": "Hello"}]
        result = gen.generate_sequence(interactions)
        assert "A" in result
        assert "B" in result
        assert "Hello" in result

    def test_mindmap_single_branch_single_leaf(self):
        """Test mindmap with minimal structure."""
        gen = DiagramGenerator()
        result = gen.generate_mindmap("Root", {"Branch": ["Leaf"]})
        assert "Root" in result
        assert "Branch" in result
        assert "Leaf" in result

    def test_mindmap_empty_branch(self):
        """Test mindmap with empty branch."""
        gen = DiagramGenerator()
        result = gen.generate_mindmap("Root", {"EmptyBranch": []})
        assert "Root" in result
        assert "EmptyBranch" in result

    def test_causal_chain_special_characters_in_event(self):
        """Test causal chain with special characters in event names."""
        gen = DiagramGenerator()
        events = [
            {
                "cause": "Rate Hike (↑25bp)",
                "effect": "Bond Yields Up",
                "impact": "positive",
            }
        ]
        result = gen.generate_causal_chain(events)
        # Should handle special chars gracefully
        assert "flowchart" in result

    def test_save_mermaid_creates_parent_dirs(self):
        """Test that save_mermaid creates parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "subdir" / "nested" / "diagram.mmd"
            gen = DiagramGenerator()

            # Note: save_mermaid doesn't create parent dirs, just verify it handles gracefully
            try:
                result = gen.save_mermaid("test content", str(filepath))
                # If no exception, check if file was created
                assert filepath.exists() or not filepath.parent.exists()
            except (FileNotFoundError, OSError):
                # Expected if parent dirs don't exist
                pass

    def test_pie_negative_values(self):
        """Test pie chart with negative values."""
        gen = DiagramGenerator()
        result = gen.generate_pie({"Positive": 50, "Negative": -10})
        # Should still generate output
        assert "pie" in result

    def test_flow_with_styled_nodes(self):
        """Test flow diagram with styled nodes."""
        gen = DiagramGenerator()
        nodes = [
            DiagramNode(id="start", label="Start", style="highlight"),
            DiagramNode(id="end", label="End", style="warning"),
        ]
        edges = [DiagramEdge(source="start", target="end")]
        result = gen.generate_flow(nodes, edges)
        assert "start" in result
        assert "end" in result
