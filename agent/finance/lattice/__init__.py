"""Insight Lattice — layered distillation of dashboard data.

Four layers (n=3 distillation hops):

    L0  Raw widgets          (existing dashboard state)
    L1  Observations         (deterministic, tagged facts)
    L2  Clusters             (tag-based soft membership — overlap preserved)
    L3  Apex                 (Toulmin-structured calls)

See plans/2026-04-20_insight-lattice.md for the design doc.
"""
