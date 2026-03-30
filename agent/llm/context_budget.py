"""
Context Budget Manager — Intelligent context window allocation.
Ensures NeoMind never exceeds model context limits while maximizing
information density.

Budget allocation (75% of model max for input):
  1. System prompt: ~500 tokens (required)
  2. Learnings: top 5, ~200 tokens (conditional)
  3. Skills: max 3, ~150 tokens (conditional)
  4. Briefing: fin/chat only, ~200 tokens (conditional)
  5. Goals: active only, ~100 tokens (conditional)
  6. Conversation: use remaining budget (variable)
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Rough token estimation: ~4 chars per token for mixed en/zh text
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Rough token count estimate (4 chars ≈ 1 token for mixed en/zh)."""
    return max(1, len(text) // CHARS_PER_TOKEN)


class ContextBudgetManager:
    """Manages context window budget allocation across prompt sections.

    Usage:
        budget = ContextBudgetManager(model_max_tokens=131072)
        sections = budget.build_prompt(
            mode="chat",
            system_prompt="You are NeoMind...",
            learnings_text="...",
            skills_text="...",
            briefing_text="...",
            goals_text="...",
            conversation_history=[...],
        )
    """

    def __init__(self, model_max_tokens: int = 131072,
                 budget_ratio: float = 0.75):
        self.model_max_tokens = model_max_tokens
        self.budget_ratio = budget_ratio
        self.input_budget = int(model_max_tokens * budget_ratio)

    def build_prompt(self, mode: str,
                     system_prompt: str,
                     learnings_text: str = "",
                     skills_text: str = "",
                     briefing_text: str = "",
                     goals_text: str = "",
                     conversation_history: Optional[list] = None,
                     user_query: str = "",
                     compress: bool = False) -> dict:
        """Build a budget-managed prompt with all sections.

        Args:
            compress: If True, compress learnings_text, skills_text, and briefing_text
                     sections before budgeting to save context space.

        Returns dict with sections and their token allocations.
        """
        sections = []
        used = 0

        # Optional compression stage
        if compress:
            compressor = TextCompressor(target_ratio=0.6)
            if learnings_text:
                learnings_text = compressor.compress(learnings_text)
            if skills_text:
                skills_text = compressor.compress(skills_text)
            if briefing_text:
                briefing_text = compressor.compress(briefing_text)

        # 1. System prompt (required)
        sys_tokens = estimate_tokens(system_prompt)
        sections.append({
            "role": "system",
            "content": system_prompt,
            "tokens": sys_tokens,
            "section": "system_prompt",
        })
        used += sys_tokens

        # 2. Learnings (conditional, capped at 200 tokens)
        if learnings_text:
            learn_tokens = min(200, estimate_tokens(learnings_text))
            if used + learn_tokens < self.input_budget:
                trimmed = learnings_text[:learn_tokens * CHARS_PER_TOKEN]
                sections.append({
                    "role": "system",
                    "content": trimmed,
                    "tokens": learn_tokens,
                    "section": "learnings",
                })
                used += learn_tokens

        # 3. Skills (conditional, capped at 150 tokens)
        if skills_text:
            skill_tokens = min(150, estimate_tokens(skills_text))
            if used + skill_tokens < self.input_budget:
                trimmed = skills_text[:skill_tokens * CHARS_PER_TOKEN]
                sections.append({
                    "role": "system",
                    "content": trimmed,
                    "tokens": skill_tokens,
                    "section": "skills",
                })
                used += skill_tokens

        # 4. Briefing (fin/chat only, capped at 200 tokens)
        if briefing_text and mode in ("chat", "fin"):
            brief_tokens = min(200, estimate_tokens(briefing_text))
            if used + brief_tokens < self.input_budget:
                trimmed = briefing_text[:brief_tokens * CHARS_PER_TOKEN]
                sections.append({
                    "role": "system",
                    "content": trimmed,
                    "tokens": brief_tokens,
                    "section": "briefing",
                })
                used += brief_tokens

        # 5. Goals (conditional, capped at 100 tokens)
        if goals_text:
            goal_tokens = min(100, estimate_tokens(goals_text))
            if used + goal_tokens < self.input_budget:
                trimmed = goals_text[:goal_tokens * CHARS_PER_TOKEN]
                sections.append({
                    "role": "system",
                    "content": trimmed,
                    "tokens": goal_tokens,
                    "section": "goals",
                })
                used += goal_tokens

        # 6. User query (required)
        if user_query:
            query_tokens = estimate_tokens(user_query)
            sections.append({
                "role": "user",
                "content": user_query,
                "tokens": query_tokens,
                "section": "user_query",
            })
            used += query_tokens

        # 7. Conversation history (use remaining budget)
        remaining = self.input_budget - used
        if conversation_history and remaining > 100:
            trimmed_history = self._trim_conversation(
                conversation_history, remaining
            )
            for msg in trimmed_history:
                msg_tokens = estimate_tokens(msg.get("content", ""))
                sections.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                    "tokens": msg_tokens,
                    "section": "conversation",
                })
                used += msg_tokens

        return {
            "sections": sections,
            "total_tokens": used,
            "budget": self.input_budget,
            "utilization": used / self.input_budget if self.input_budget > 0 else 0,
        }

    def _trim_conversation(self, history: list, max_tokens: int) -> list:
        """Trim conversation history to fit within token budget.

        Strategy: Keep recent messages, drop oldest first.
        Always keep the last message (most relevant).
        """
        if not history:
            return []

        # Estimate tokens per message
        messages_with_tokens = []
        for msg in history:
            tokens = estimate_tokens(msg.get("content", ""))
            messages_with_tokens.append((msg, tokens))

        # Start from most recent, work backwards
        result = []
        total = 0
        for msg, tokens in reversed(messages_with_tokens):
            if total + tokens > max_tokens:
                break
            result.append(msg)
            total += tokens

        return list(reversed(result))

    def get_budget_report(self) -> dict:
        """Get current budget configuration."""
        return {
            "model_max_tokens": self.model_max_tokens,
            "budget_ratio": self.budget_ratio,
            "input_budget": self.input_budget,
            "output_budget": self.model_max_tokens - self.input_budget,
        }


# ── LLMLingua-2 Inspired Compression ─────────────────────────
# Research: Round 1 — LLMLingua-2 achieves 2-20x compression with minimal quality loss
# Our implementation: pure Python, no external dependencies

# Filler words and low-information tokens to strip first
FILLER_WORDS = {
    "basically", "actually", "essentially", "literally", "simply",
    "really", "very", "quite", "just", "kind of", "sort of",
    "you know", "i mean", "like", "well", "so", "um", "uh",
    "anyway", "however", "moreover", "furthermore", "additionally",
    "in fact", "as a matter of fact", "to be honest", "honestly",
    "obviously", "clearly", "naturally", "certainly", "definitely",
}

# Chinese filler equivalents
FILLER_WORDS_ZH = {
    "其实", "基本上", "本质上", "简单来说", "实际上", "确实",
    "事实上", "总之", "当然", "显然", "毫无疑问",
}


class TextCompressor:
    """LLMLingua-2 inspired prompt compression for context budget management.

    Core techniques:
    1. Filler word removal (lowest-hanging fruit, ~10-15% reduction)
    2. Redundancy detection (repeated phrases, ~5-10% reduction)
    3. Sentence importance scoring (TF-based, keep most informative)
    4. Whitespace normalization

    Usage:
        compressor = TextCompressor(target_ratio=0.5)
        compressed = compressor.compress(long_text)
    """

    def __init__(self, target_ratio: float = 0.5):
        """
        Args:
            target_ratio: Target size as fraction of original (0.5 = 50% of original size)
        """
        self.target_ratio = max(0.1, min(1.0, target_ratio))

    def compress(self, text: str, target_ratio: Optional[float] = None) -> str:
        """Compress text to target ratio while preserving key information.

        Args:
            text: Input text to compress
            target_ratio: Override default ratio for this call

        Returns:
            Compressed text
        """
        if not text or len(text) < 100:
            return text

        ratio = target_ratio or self.target_ratio
        target_len = int(len(text) * ratio)

        # Stage 1: Normalize whitespace
        result = self._normalize_whitespace(text)
        if len(result) <= target_len:
            return result

        # Stage 2: Remove filler words
        result = self._remove_fillers(result)
        if len(result) <= target_len:
            return result

        # Stage 3: Remove redundant sentences
        result = self._remove_redundancy(result)
        if len(result) <= target_len:
            return result

        # Stage 4: Score and filter sentences by importance
        result = self._importance_filter(result, target_len)

        return result

    def _normalize_whitespace(self, text: str) -> str:
        """Collapse multiple spaces/newlines into single space."""
        # Collapse whitespace but preserve paragraph breaks
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _remove_fillers(self, text: str) -> str:
        """Remove low-information filler words."""
        result = text
        # English fillers (word boundary matching)
        for filler in FILLER_WORDS:
            pattern = r'\b' + re.escape(filler) + r'\b'
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        # Chinese fillers (no word boundaries needed)
        for filler in FILLER_WORDS_ZH:
            result = result.replace(filler, '')
        # Clean up double spaces from removal
        result = re.sub(r'  +', ' ', result)
        return result.strip()

    def _remove_redundancy(self, text: str) -> str:
        """Remove sentences that are near-duplicates of earlier sentences."""
        sentences = self._split_sentences(text)
        if len(sentences) <= 2:
            return text

        seen_ngrams = set()
        unique_sentences = []

        for sent in sentences:
            # Create 4-gram set for this sentence
            words = sent.lower().split()
            if len(words) < 4:
                unique_sentences.append(sent)
                continue

            ngrams = set()
            for i in range(len(words) - 3):
                ngrams.add(tuple(words[i:i+4]))

            # Check overlap with previously seen n-grams
            if seen_ngrams:
                overlap = len(ngrams & seen_ngrams) / max(1, len(ngrams))
                if overlap > 0.6:  # >60% overlap → redundant
                    continue

            seen_ngrams.update(ngrams)
            unique_sentences.append(sent)

        return ' '.join(unique_sentences)

    def _importance_filter(self, text: str, target_len: int) -> str:
        """Score sentences by importance and keep the most informative ones."""
        sentences = self._split_sentences(text)
        if not sentences:
            return text

        # Calculate word frequencies across entire text
        all_words = text.lower().split()
        word_freq = {}
        for w in all_words:
            word_freq[w] = word_freq.get(w, 0) + 1

        # Score each sentence
        scored = []
        for i, sent in enumerate(sentences):
            words = sent.lower().split()
            if not words:
                continue

            # TF-IDF-like scoring: rare words are more informative
            max_freq = max(word_freq.values()) if word_freq else 1
            score = sum(1.0 - (word_freq.get(w, 0) / max_freq) for w in words) / len(words)

            # Positional boost: first and last sentences are more important
            if i == 0:
                score *= 1.5
            elif i == len(sentences) - 1:
                score *= 1.3

            scored.append((score, i, sent))

        # Sort by importance, keep enough to fit target
        scored.sort(reverse=True)

        kept = []
        current_len = 0
        for score, idx, sent in scored:
            if current_len + len(sent) > target_len:
                break
            kept.append((idx, sent))
            current_len += len(sent)

        # Restore original order
        kept.sort(key=lambda x: x[0])
        return ' '.join(s for _, s in kept)

    @staticmethod
    def _split_sentences(text: str) -> list:
        """Split text into sentences (handles both English and Chinese)."""
        # Split on sentence-ending punctuation
        parts = re.split(r'(?<=[.!?。！？])\s+', text)
        return [p.strip() for p in parts if p.strip()]

    def get_compression_report(self, original: str, compressed: str) -> dict:
        """Report compression statistics."""
        orig_tokens = estimate_tokens(original)
        comp_tokens = estimate_tokens(compressed)
        return {
            "original_chars": len(original),
            "compressed_chars": len(compressed),
            "original_tokens": orig_tokens,
            "compressed_tokens": comp_tokens,
            "ratio": round(len(compressed) / max(1, len(original)), 3),
            "tokens_saved": orig_tokens - comp_tokens,
        }
