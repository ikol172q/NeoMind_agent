# agent/finance/agent_collab.py
"""
Inter-Agent Collaboration — NeoMind ↔ OpenClaw peer protocol.

When both agents are in the same Telegram group, they can:
1. @mention each other to delegate tasks
2. Collaborate on complex queries (OpenClaw does general, NeoMind does finance)
3. Share context via Docker-internal HTTP or shared volume
4. Avoid duplicate responses (one agent yields to the other)

Protocol:
- Telegram @mention: User says "@neomind ask @openclaw to check the weather"
  → NeoMind posts: "@openclaw 帮忙查一下天气"
  → OpenClaw responds to the group

- Domain detection: If someone asks a finance question in a group with both bots,
  NeoMind claims it. If someone asks a general question, NeoMind stays silent.

- Handoff: NeoMind can explicitly hand off to OpenClaw with a formatted message
  that OpenClaw recognizes as a skill invocation.
"""

import re
import json
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class AgentIdentity:
    """Identity of a known agent in the group."""
    name: str
    telegram_username: str     # without @
    domains: list              # what topics this agent handles
    is_self: bool = False


class AgentCollaborator:
    """
    Manages multi-agent collaboration in a shared Telegram group.

    Key responsibilities:
    1. Domain routing: who should respond to what?
    2. Delegation: format @mention messages for handoff
    3. Deconfliction: prevent duplicate responses
    """

    def __init__(self, self_username: str, peers: Optional[Dict[str, AgentIdentity]] = None):
        self.self_identity = AgentIdentity(
            name="NeoMind Finance",
            telegram_username=self_username,
            domains=["finance", "stocks", "crypto", "market", "investment",
                     "金融", "股票", "加密", "投资"],
            is_self=True,
        )

        self.peers = peers or {}

    def register_peer(self, name: str, username: str, domains: list):
        """Register another agent in the group."""
        self.peers[username.lower()] = AgentIdentity(
            name=name,
            telegram_username=username.lower(),
            domains=domains,
        )

    def register_openclaw(self, username: str = ""):
        """Register OpenClaw as a peer with its known domains."""
        username = username or "openclaw_bot"
        self.register_peer(
            name="OpenClaw",
            username=username,
            domains=["general", "coding", "search", "browser", "email",
                     "calendar", "tasks", "shell", "files"],
        )

    def classify_domain(self, text: str) -> str:
        """Classify which domain a message belongs to.

        Returns: "finance", "general", "ambiguous", or a peer's username.
        """
        text_lower = text.lower()

        # Finance signals
        finance_score = 0
        finance_words = [
            "stock", "price", "market", "earnings", "crypto", "bitcoin",
            "portfolio", "invest", "fed", "inflation", "dividend", "ipo",
            "nasdaq", "s&p", "bond", "yield", "rate cut", "rate hike",
            "股票", "股价", "行情", "财报", "加密", "央行", "利率",
            "A股", "港股", "美股", "基金", "通胀",
        ]
        for word in finance_words:
            if word in text_lower:
                finance_score += 1

        # General/coding signals
        general_score = 0
        general_words = [
            "code", "file", "folder", "email", "calendar", "meeting",
            "weather", "recipe", "translate", "summarize", "write",
            "search", "browse", "shell", "command", "git",
            "代码", "文件", "邮件", "日程", "会议", "天气",
        ]
        for word in general_words:
            if word in text_lower:
                general_score += 1

        # Ticker patterns strongly signal finance
        if re.search(r'\$[A-Z]{1,5}\b', text):
            finance_score += 3

        if finance_score > general_score and finance_score > 0:
            return "finance"
        elif general_score > finance_score and general_score > 0:
            return "general"
        elif finance_score > 0 and general_score > 0:
            return "ambiguous"
        else:
            return "ambiguous"

    def should_i_respond(self, text: str, is_mention: bool, is_reply: bool) -> Tuple[bool, str]:
        """Decide if NeoMind should respond to this message.

        Returns (should_respond, reason).
        """
        # Always respond to direct @mention or reply
        if is_mention or is_reply:
            return True, "direct"

        # Check domain
        domain = self.classify_domain(text)

        if domain == "finance":
            return True, "finance_domain"
        elif domain == "general":
            return False, "general_domain"  # let OpenClaw handle it
        else:
            # Ambiguous — only respond if explicitly finance-related
            return False, "ambiguous"

    def format_handoff(self, peer_username: str, query: str, context: str = "") -> str:
        """Format a handoff message to another agent.

        Returns a message string that @mentions the peer agent.
        """
        lines = [f"@{peer_username}"]
        if context:
            lines.append(f"({context})")
        lines.append(query)
        return " ".join(lines)

    def format_collab_response(self, my_response: str, delegated_to: str = "") -> str:
        """Format a response that includes delegation info."""
        if delegated_to:
            peer = self.peers.get(delegated_to.lower())
            peer_name = peer.name if peer else delegated_to
            return f"{my_response}\n\n🤝 我也让 @{delegated_to} ({peer_name}) 来协助"
        return my_response

    def parse_incoming_handoff(self, text: str) -> Optional[Dict]:
        """Check if another agent is handing off a task to us.

        OpenClaw might send: "@neomind_fin_bot /stock AAPL — user asked for stock price"
        """
        me = self.self_identity.telegram_username
        if f"@{me}" not in text.lower():
            return None

        # Extract the query after our @mention
        pattern = rf'@{re.escape(me)}\s+(.*)'
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            query = match.group(1).strip()
            # Try to identify who sent the handoff
            sender = None
            for username, peer in self.peers.items():
                if f"@{username}" in text.lower():
                    sender = peer.name
                    break
            return {
                "query": query,
                "from_agent": sender or "unknown",
                "raw": text,
            }
        return None
