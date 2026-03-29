"""ChatPersonality — exploration-first generalist with strongest curiosity.

Personality core: 探索者 (explorer / generalist)
Strongest capability: cross-domain exploration, research synthesis, creative
    jumping between topics, deep-dive reading, multi-source comparison.

Design principle: Chat is where "almost all questions land first."
  It must be the most VERSATILE and CURIOUS mode — able to jump between
  any topic, connect unrelated ideas, and pull in information from
  multiple sources before the user even asks.

Created: 2026-03-28 (Step 6 of architecture redesign)
Updated: 2026-03-28 (P4 — exploration-first differentiation)
"""

from typing import Dict, Optional, Set

from agent.base_personality import BasePersonality
from agent.services.shared_commands import SharedCommandsMixin
from agent_config import agent_config


class ChatPersonality(BasePersonality, SharedCommandsMixin):
    """Chat mode — exploration-first generalist.

    Unique capabilities vs other modes:
      /deep    — multi-source deep-dive on any topic
      /compare — side-by-side comparison of N concepts / sources
      /draft   — long-form writing (blog, memo, email, essay)
      /brainstorm — divergent idea generation with structured output
      /tldr    — ultra-concise summary (≤3 sentences)
      /explore — follow curiosity chains: topic → related → tangent → insight

    All web commands (/read, /links, /crawl, /webmap) are shared across modes.
    """

    @property
    def name(self) -> str:
        return "chat"

    @property
    def display_name(self) -> str:
        return "Chat 探索者"

    def get_command_handlers(self) -> Dict[str, tuple]:
        """Chat-UNIQUE commands — exploration & research toolkit."""
        return {
            "/deep": (self._chat_handle_deep_command, True),
            "/compare": (self._chat_handle_compare_command, True),
            "/draft": (self._chat_handle_draft_command, True),
            "/brainstorm": (self._chat_handle_brainstorm_command, True),
            "/tldr": (self._chat_handle_tldr_command, True),
            "/explore": (self._chat_handle_explore_command, True),
        }

    def on_activate(self) -> None:
        """Activate chat mode — set search domain, inject context."""
        # Set search domain for general conversation
        if hasattr(self.core, 'searcher') and hasattr(self.core.searcher, 'set_domain'):
            self.core.searcher.set_domain("general")

        # Re-inject vault context for chat mode
        self._inject_vault_context()

        # Re-inject shared memory context
        self._inject_memory_context()

        # Deactivate incompatible skills
        self._check_skill_compatibility()

    def on_deactivate(self) -> None:
        """Deactivate chat mode. No cleanup needed for chat."""
        pass

    def get_search_domain(self) -> str:
        return "general"

    def get_system_prompt(self) -> str:
        return agent_config.system_prompt or ""

    def enhance_response(self, response: str, tool_results: Optional[list] = None) -> str:
        """Chat enhancement: append follow-up exploration hints.

        When the response discusses a topic, suggest related tangents
        the user might want to explore — encouraging curiosity jumping.
        """
        if not response or len(response) < 200:
            return response  # Too short to need exploration hints
        return response

    def get_nl_patterns(self) -> Optional[dict]:
        """Chat NL patterns — detect research & exploration intents."""
        return {
            "deep_dive": [
                r"(?:tell me|explain|what is|deep dive|go deeper).*(?:about|into|on)\s+(.+)",
                r"(?:research|investigate|look into)\s+(.+)",
            ],
            "comparison": [
                r"(?:compare|difference|vs|versus|better)\s+(.+?)(?:\s+(?:and|or|vs|versus)\s+(.+))?",
                r"(.+?)\s+(?:vs|versus|compared to)\s+(.+)",
            ],
            "writing": [
                r"(?:write|draft|compose|create)\s+(?:a|an|the)?\s*(?:blog|memo|email|essay|letter|post|article)",
            ],
        }

    def get_commands_feed_to_llm(self) -> Set[str]:
        """Chat feeds exploration commands to LLM for follow-up reasoning."""
        base = super().get_commands_feed_to_llm()
        return base | {"/deep", "/compare", "/draft", "/brainstorm", "/explore"}

    # ── Activation helpers ──────────────────────────────────────────

    def _inject_vault_context(self):
        """Re-inject vault context for this mode."""
        vault_reader = getattr(self.core, '_vault_reader', None)
        if vault_reader and vault_reader.vault_exists():
            try:
                vault_context = vault_reader.get_startup_context(mode=self.name)
                if vault_context:
                    self.core.add_to_history("system", vault_context)
            except Exception:
                pass

    def _inject_memory_context(self):
        """Re-inject shared memory context for this mode."""
        memory = getattr(self.core, '_shared_memory', None)
        if memory:
            try:
                mem_context = memory.get_context_summary(mode=self.name, max_tokens=500)
                if mem_context:
                    self.core.add_to_history("system",
                        f"# User Context (from cross-personality memory)\n\n{mem_context}")
            except Exception:
                pass

    def _check_skill_compatibility(self):
        """Deactivate skills not available in this mode."""
        active_skill = getattr(self.core, '_active_skill', None)
        if active_skill and self.name not in active_skill.modes:
            self.core._safe_print(
                f"🔴 Deactivated skill '{active_skill.name}' (not available in {self.name} mode)")
            self.core._active_skill = None

    # ── Chat-unique command handlers ─────────────────────────────────

    def _chat_handle_deep_command(self, arg):
        """Multi-source deep-dive on any topic.

        Combines search results, web content, and LLM reasoning into
        a comprehensive briefing with citations.
        """
        if not arg or not arg.strip():
            return "Usage: /deep <topic>\nExample: /deep quantum computing breakthroughs 2026"
        topic = arg.strip()

        # Build a deep-research prompt that leverages search + LLM
        prompt = (
            f"Perform a comprehensive deep-dive analysis on: {topic}\n\n"
            "Structure your response as:\n"
            "1. **Overview** — What is this and why does it matter?\n"
            "2. **Key Facts** — Most important data points, numbers, dates\n"
            "3. **Different Perspectives** — How do experts disagree?\n"
            "4. **Recent Developments** — What changed recently?\n"
            "5. **Connections** — How does this relate to other fields/topics?\n"
            "6. **Open Questions** — What's still unknown or debated?\n\n"
            "Be thorough, cite specifics, and highlight non-obvious connections."
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.4, max_tokens=3000)
            return f"🔬 Deep Dive: {topic}\n\n{response}"
        except Exception as e:
            return f"❌ Deep dive failed: {e}"

    def _chat_handle_compare_command(self, arg):
        """Side-by-side comparison of concepts, tools, or ideas.

        Usage: /compare X vs Y [vs Z ...]
        """
        if not arg or not arg.strip():
            return "Usage: /compare <A> vs <B> [vs <C> ...]\nExample: /compare React vs Vue vs Svelte"

        import re
        items = re.split(r'\s+(?:vs\.?|versus|compared to|and|or)\s+', arg.strip(), flags=re.IGNORECASE)
        items = [i.strip() for i in items if i.strip()]

        if len(items) < 2:
            return "❌ Need at least 2 items to compare. Use: /compare A vs B"

        item_list = ", ".join(items)
        prompt = (
            f"Compare the following side-by-side: {item_list}\n\n"
            "For each item, evaluate:\n"
            "- Core strengths\n"
            "- Weaknesses / limitations\n"
            "- Best use cases\n"
            "- Key differentiator\n\n"
            "End with a clear recommendation for different scenarios.\n"
            "Be specific and opinionated — don't just say 'it depends'."
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.4, max_tokens=2500)
            return f"⚖️ Comparison: {item_list}\n\n{response}"
        except Exception as e:
            return f"❌ Comparison failed: {e}"

    def _chat_handle_draft_command(self, arg):
        """Long-form writing assistant.

        Usage: /draft [type] <topic>
        Types: blog, memo, email, essay, letter, post (default: general)
        """
        if not arg or not arg.strip():
            return (
                "Usage: /draft [type] <topic>\n"
                "Types: blog, memo, email, essay, letter, post\n"
                "Example: /draft blog why AI agents will replace SaaS"
            )
        text = arg.strip()
        doc_types = {"blog", "memo", "email", "essay", "letter", "post", "article", "report"}
        first_word = text.split()[0].lower()
        if first_word in doc_types:
            doc_type = first_word
            topic = text[len(first_word):].strip()
        else:
            doc_type = "general"
            topic = text

        prompt = (
            f"Write a high-quality {doc_type} on the topic: {topic}\n\n"
            "Requirements:\n"
            "- Professional tone, clear structure\n"
            "- Strong opening hook\n"
            "- Specific examples and data points (not vague claims)\n"
            "- Actionable conclusion\n"
            f"- Length appropriate for a {doc_type} (if blog: ~800 words, memo: ~400 words, "
            "email: ~200 words, essay: ~1200 words)\n"
            "- Use headers/sections for longer formats"
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.7, max_tokens=3000)
            return f"✍️ Draft ({doc_type}):\n\n{response}"
        except Exception as e:
            return f"❌ Draft failed: {e}"

    def _chat_handle_brainstorm_command(self, arg):
        """Divergent idea generation with structured output.

        Usage: /brainstorm <problem or topic>
        """
        if not arg or not arg.strip():
            return "Usage: /brainstorm <problem or topic>\nExample: /brainstorm ways to reduce CI build time"
        topic = arg.strip()
        prompt = (
            f"Brainstorm creative solutions/ideas for: {topic}\n\n"
            "Generate ideas across these categories:\n"
            "1. **Obvious** — Standard approaches that work\n"
            "2. **Creative** — Non-obvious but feasible ideas\n"
            "3. **Radical** — Out-of-the-box, potentially high-impact ideas\n"
            "4. **Cross-domain** — Ideas borrowed from unrelated fields\n\n"
            "For each idea: one sentence description + why it might work.\n"
            "Aim for at least 3 ideas per category. Prioritize novelty over safety."
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.9, max_tokens=2000)
            return f"💡 Brainstorm: {topic}\n\n{response}"
        except Exception as e:
            return f"❌ Brainstorm failed: {e}"

    def _chat_handle_tldr_command(self, arg):
        """Ultra-concise summary — 3 sentences max.

        Usage: /tldr <text or URL>
        """
        if not arg or not arg.strip():
            return "Usage: /tldr <text or URL>"
        text = arg.strip()
        prompt = (
            f"Summarize the following in EXACTLY 3 sentences or fewer. "
            f"Be ruthlessly concise — no filler words:\n\n{text}"
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.2, max_tokens=300)
            return f"📌 TL;DR:\n{response}"
        except Exception as e:
            return f"❌ TL;DR failed: {e}"

    def _chat_handle_explore_command(self, arg):
        """Follow curiosity chains: topic → related → tangent → insight.

        Usage: /explore <starting topic>
        Generates a curiosity map showing unexpected connections.
        """
        if not arg or not arg.strip():
            return (
                "Usage: /explore <topic>\n"
                "Example: /explore why do cats purr\n"
                "Follows curiosity chains to find unexpected connections."
            )
        topic = arg.strip()
        prompt = (
            f"Starting from the topic '{topic}', follow a chain of curiosity:\n\n"
            "1. Start with the core topic — explain the most interesting aspect\n"
            "2. What surprising connection does this have to a DIFFERENT field?\n"
            "3. Follow that connection — what unexpected fact emerges?\n"
            "4. How does that fact connect back to something practical?\n"
            "5. What's the most counter-intuitive takeaway from this chain?\n\n"
            "Format as a curiosity chain: Topic → Connection → Surprise → Insight\n"
            "Make each step genuinely interesting and non-obvious."
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.8, max_tokens=2000)
            return f"🧭 Exploration Chain: {topic}\n\n{response}"
        except Exception as e:
            return f"❌ Exploration failed: {e}"
