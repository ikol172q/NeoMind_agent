# agent/finance/diagram_gen.py
"""
Diagram Generator — mermaid-based visualization for complex relationships.

Creates visual representations of:
- Causal chains (Fed rate → housing → consumer spending)
- Timelines (earnings calendar, FOMC schedule)
- Comparisons (risk vs return)
- Flow diagrams (money flow, trade execution)
- Mind maps (sector breakdown)

Shared between fin and coding modes.
Output: mermaid syntax (can render to SVG/PNG with mermaid-cli).
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class DiagramNode:
    """A node in a diagram."""
    id: str
    label: str
    style: str = ""  # e.g., "fill:#f9f,stroke:#333"


@dataclass
class DiagramEdge:
    """An edge between two nodes."""
    source: str
    target: str
    label: str = ""
    style: str = ""  # e.g., "stroke:#f00"


class DiagramGenerator:
    """
    Generate mermaid diagrams for financial and technical relationships.
    Usable in both fin and coding modes.
    """

    DIAGRAM_TYPES = {
        "causal": "flowchart TD",
        "flow": "flowchart LR",
        "timeline": "gantt",
        "sequence": "sequenceDiagram",
        "mindmap": "mindmap",
        "pie": "pie",
    }

    # ── Causal Chain Diagrams ─────────────────────────────────────────

    def generate_causal_chain(
        self,
        events: List[Dict],
        title: str = "Causal Chain",
        direction: str = "TD",
    ) -> str:
        """
        Generate a causal chain flowchart.

        Args:
            events: List of {cause: str, effect: str, impact: str}
                    where impact is "positive", "negative", or "neutral"
            title: Diagram title
            direction: "TD" (top-down) or "LR" (left-right)

        Returns:
            Mermaid syntax string
        """
        lines = [f"---", f"title: {title}", f"---", f"flowchart {direction}"]

        # Track unique nodes
        nodes = set()
        node_counter = 0

        def get_node_id(label: str) -> str:
            nonlocal node_counter
            safe = label.replace(" ", "_").replace("'", "").replace('"', "")[:20]
            node_id = f"N{safe}"
            if node_id not in nodes:
                nodes.add(node_id)
            return node_id

        for event in events:
            cause_id = get_node_id(event["cause"])
            effect_id = get_node_id(event["effect"])

            # Style based on impact
            impact = event.get("impact", "neutral")
            if impact == "positive":
                arrow = f"-->{{\"+\"}}"
                lines.append(f"    {cause_id}[\"{event['cause']}\"] -->|+| {effect_id}[\"{event['effect']}\"]")
            elif impact == "negative":
                lines.append(f"    {cause_id}[\"{event['cause']}\"] -->|-| {effect_id}[\"{event['effect']}\"]")
            else:
                lines.append(f"    {cause_id}[\"{event['cause']}\"] --> {effect_id}[\"{event['effect']}\"]")

        # Add styling
        lines.append("")
        lines.append("    classDef positive fill:#d4edda,stroke:#28a745")
        lines.append("    classDef negative fill:#f8d7da,stroke:#dc3545")
        lines.append("    classDef neutral fill:#e2e3e5,stroke:#6c757d")

        return "\n".join(lines)

    # ── Timeline / Gantt Diagrams ─────────────────────────────────────

    def generate_timeline(
        self,
        events: List[Dict],
        title: str = "Financial Events Timeline",
    ) -> str:
        """
        Generate a Gantt-style timeline.

        Args:
            events: List of {name: str, start: str, end: str, section: str}
                    dates in YYYY-MM-DD format

        Returns:
            Mermaid Gantt syntax
        """
        lines = [
            f"gantt",
            f"    title {title}",
            f"    dateFormat YYYY-MM-DD",
        ]

        # Group by section
        sections: Dict[str, List[Dict]] = {}
        for event in events:
            section = event.get("section", "Events")
            sections.setdefault(section, []).append(event)

        for section, items in sections.items():
            lines.append(f"    section {section}")
            for item in items:
                start = item["start"]
                end = item.get("end", start)
                name = item["name"]
                if start == end:
                    lines.append(f"        {name} : milestone, {start}, 0d")
                else:
                    lines.append(f"        {name} : {start}, {end}")

        return "\n".join(lines)

    # ── Comparison / Pie Charts ───────────────────────────────────────

    def generate_pie(
        self,
        data: Dict[str, float],
        title: str = "Allocation",
    ) -> str:
        """
        Generate a pie chart.

        Args:
            data: {label: value} dict

        Returns:
            Mermaid pie syntax
        """
        lines = [f'pie title {title}']
        for label, value in data.items():
            lines.append(f'    "{label}" : {value}')
        return "\n".join(lines)

    # ── Flow Diagrams ─────────────────────────────────────────────────

    def generate_flow(
        self,
        nodes: List[DiagramNode],
        edges: List[DiagramEdge],
        title: str = "",
        direction: str = "LR",
    ) -> str:
        """
        Generate a custom flowchart from nodes and edges.

        Args:
            nodes: List of DiagramNode
            edges: List of DiagramEdge
            direction: "LR", "TD", "RL", "BT"
        """
        lines = []
        if title:
            lines.extend(["---", f"title: {title}", "---"])
        lines.append(f"flowchart {direction}")

        # Define nodes
        for node in nodes:
            if node.style:
                lines.append(f"    {node.id}[\"{node.label}\"]:::{node.style}")
            else:
                lines.append(f"    {node.id}[\"{node.label}\"]")

        # Define edges
        for edge in edges:
            if edge.label:
                lines.append(f"    {edge.source} -->|{edge.label}| {edge.target}")
            else:
                lines.append(f"    {edge.source} --> {edge.target}")

        return "\n".join(lines)

    # ── Sequence Diagrams ─────────────────────────────────────────────

    def generate_sequence(
        self,
        interactions: List[Dict],
        title: str = "",
    ) -> str:
        """
        Generate a sequence diagram.

        Args:
            interactions: List of {from: str, to: str, message: str, type: str}
                         type: "solid" (->>) or "dashed" (-->>)
        """
        lines = ["sequenceDiagram"]
        if title:
            lines.append(f"    Note over {interactions[0]['from']}: {title}")

        for interaction in interactions:
            arrow = "->>" if interaction.get("type", "solid") == "solid" else "-->>"
            lines.append(
                f"    {interaction['from']}{arrow}{interaction['to']}: {interaction['message']}"
            )

        return "\n".join(lines)

    # ── Mind Map ──────────────────────────────────────────────────────

    def generate_mindmap(
        self,
        root: str,
        branches: Dict[str, List[str]],
    ) -> str:
        """
        Generate a mind map.

        Args:
            root: Central topic
            branches: {branch_label: [leaf1, leaf2, ...]}
        """
        lines = ["mindmap", f"  root(({root}))"]
        for branch, leaves in branches.items():
            lines.append(f"    {branch}")
            for leaf in leaves:
                lines.append(f"      {leaf}")
        return "\n".join(lines)

    # ── Pre-built Financial Diagrams ──────────────────────────────────

    def fed_rate_impact(self, direction: str = "hike") -> str:
        """Pre-built: Fed rate hike/cut causal chain."""
        if direction == "hike":
            events = [
                {"cause": "Fed Raises Rates", "effect": "Borrowing Costs Up", "impact": "negative"},
                {"cause": "Borrowing Costs Up", "effect": "Mortgage Rates Up", "impact": "negative"},
                {"cause": "Mortgage Rates Up", "effect": "Housing Demand Down", "impact": "negative"},
                {"cause": "Housing Demand Down", "effect": "Construction Slows", "impact": "negative"},
                {"cause": "Borrowing Costs Up", "effect": "Corporate Debt Costs Up", "impact": "negative"},
                {"cause": "Corporate Debt Costs Up", "effect": "Profit Margins Squeezed", "impact": "negative"},
                {"cause": "Borrowing Costs Up", "effect": "USD Strengthens", "impact": "positive"},
                {"cause": "USD Strengthens", "effect": "Exports Less Competitive", "impact": "negative"},
                {"cause": "Fed Raises Rates", "effect": "Bonds More Attractive", "impact": "positive"},
                {"cause": "Bonds More Attractive", "effect": "Stocks Less Attractive", "impact": "negative"},
            ]
            return self.generate_causal_chain(events, "Fed Rate Hike Impact Chain")
        else:
            events = [
                {"cause": "Fed Cuts Rates", "effect": "Borrowing Costs Down", "impact": "positive"},
                {"cause": "Borrowing Costs Down", "effect": "Mortgage Rates Down", "impact": "positive"},
                {"cause": "Mortgage Rates Down", "effect": "Housing Demand Up", "impact": "positive"},
                {"cause": "Borrowing Costs Down", "effect": "Corporate Debt Cheaper", "impact": "positive"},
                {"cause": "Corporate Debt Cheaper", "effect": "More Investment", "impact": "positive"},
                {"cause": "Fed Cuts Rates", "effect": "USD Weakens", "impact": "negative"},
                {"cause": "USD Weakens", "effect": "Exports More Competitive", "impact": "positive"},
                {"cause": "Fed Cuts Rates", "effect": "Bonds Less Attractive", "impact": "negative"},
                {"cause": "Bonds Less Attractive", "effect": "Capital Flows to Stocks", "impact": "positive"},
            ]
            return self.generate_causal_chain(events, "Fed Rate Cut Impact Chain")

    def portfolio_allocation(self, allocations: Dict[str, float]) -> str:
        """Pre-built: Portfolio allocation pie chart."""
        return self.generate_pie(allocations, "Portfolio Allocation")

    # ── Render to File ────────────────────────────────────────────────

    def save_mermaid(self, mermaid_text: str, filepath: str) -> str:
        """Save mermaid syntax to a .mmd file."""
        with open(filepath, 'w') as f:
            f.write(mermaid_text)
        return filepath

    def render_info(self) -> str:
        """Info about how to render mermaid diagrams."""
        return (
            "Mermaid diagram generated. To render:\n"
            "  1. View online: paste at https://mermaid.live/\n"
            "  2. CLI render: npx @mermaid-js/mermaid-cli -i diagram.mmd -o diagram.svg\n"
            "  3. Python: pip install mermaid-py && python -c 'import mermaid; ...'\n"
            "  4. VS Code: install 'Markdown Preview Mermaid Support' extension"
        )
