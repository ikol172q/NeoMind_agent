"""Dashboard-watching agent.

A Telegram (and CLI) agent that answers user questions by tool-calling
against the local NeoMind fin dashboard at http://127.0.0.1:8001. v1
is pull-only + read-only: it observes, narrates, and recommends but
never writes. Designed to be the user's "second self" — same dashboard,
on-demand, every claim cited.
"""

from agent.finance.dashboard_agent.agent import answer

__all__ = ["answer"]
