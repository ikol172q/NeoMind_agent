"""
Beta Header Manager — Model-aware beta/experimental header injection.

Manages HTTP headers for LLM API requests that enable beta/experimental
features. Each provider has different conventions (Anthropic uses
anthropic-beta, DeepSeek may use X-Experimental headers, etc.).

Inspired by Claude Code's constants/betas.ts and utils/betas.ts.

Usage:
    from agent.services.beta_headers import beta_headers

    headers = beta_headers.get_headers(model='deepseek-v4-flash',
                                        provider='deepseek')
    # Merges with request headers in LLM provider
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

from agent.agentic.feature_gate_registry import gates


class ProviderFamily(Enum):
    """LLM provider families with different beta header conventions."""
    ANTHROPIC = "anthropic"     # Uses anthropic-beta header
    DEEPSEEK = "deepseek"       # Uses X-Experimental or none
    OPENAI = "openai"           # Uses X-Experimental or none
    LITELLM = "litellm"         # Passes through to upstream provider


# ── Beta header constants ────────────────────────────────────────────
# Names follow the convention: <feature>-<YYYY-MM-DD>

# Tool system
TOOL_SEARCH = "advanced-tool-use-2025-11-20"
TOKEN_EFFICIENT_TOOLS = "token-efficient-tools-2026-03-28"

# Thinking
INTERLEAVED_THINKING = "interleaved-thinking-2025-05-14"
REDACT_THINKING = "redact-thinking-2026-02-12"

# Context
CONTEXT_1M = "context-1m-2025-08-07"
CONTEXT_MANAGEMENT = "context-management-2025-06-27"
PROMPT_CACHING_SCOPE = "prompt-caching-scope-2026-01-05"

# Quality
EFFORT = "effort-2025-11-24"
TASK_BUDGETS = "task-budgets-2026-03-13"
FAST_MODE = "fast-mode-2026-02-01"

# Structured output
STRUCTURED_OUTPUTS = "structured-outputs-2025-12-15"

# Search
WEB_SEARCH = "web-search-2025-03-05"

# Agent-specific
CLI_CODE = "claude-code-20250219"  # NeoMind equivalent marker
ADVISOR_TOOL = "advisor-tool-2026-03-01"


@dataclass
class BetaFeature:
    """Definition of a single beta feature.

    Attributes:
        name: Human-readable name
        header_value: Value sent in the beta header
        provider_families: Which providers support this beta
        required_gate: Feature gate that must be enabled (None = always on)
        min_context: Minimum context window this beta requires (0 = any)
        exclusive_with: Other beta features this conflicts with
    """
    name: str
    header_value: str
    provider_families: Set[ProviderFamily] = field(default_factory=lambda: {ProviderFamily.ANTHROPIC})
    required_gate: Optional[str] = None
    min_context: int = 0
    exclusive_with: Set[str] = field(default_factory=set)


# ── Registered beta features ─────────────────────────────────────────

BETA_FEATURES: Dict[str, BetaFeature] = {
    'interleaved_thinking': BetaFeature(
        name='Interleaved Thinking',
        header_value=INTERLEAVED_THINKING,
        provider_families={ProviderFamily.ANTHROPIC, ProviderFamily.DEEPSEEK},
    ),
    'context_management': BetaFeature(
        name='Context Management',
        header_value=CONTEXT_MANAGEMENT,
        provider_families={ProviderFamily.ANTHROPIC, ProviderFamily.DEEPSEEK},
    ),
    'effort': BetaFeature(
        name='Effort Control',
        header_value=EFFORT,
        provider_families={ProviderFamily.ANTHROPIC, ProviderFamily.DEEPSEEK},
    ),
    'structured_outputs': BetaFeature(
        name='Structured Outputs',
        header_value=STRUCTURED_OUTPUTS,
        provider_families={ProviderFamily.ANTHROPIC},
    ),
    'context_1m': BetaFeature(
        name='1M Context Window',
        header_value=CONTEXT_1M,
        provider_families={ProviderFamily.ANTHROPIC, ProviderFamily.DEEPSEEK},
        min_context=200_000,
    ),
    'prompt_caching_scope': BetaFeature(
        name='Prompt Caching Scope',
        header_value=PROMPT_CACHING_SCOPE,
        provider_families={ProviderFamily.ANTHROPIC, ProviderFamily.DEEPSEEK},
    ),
    'task_budgets': BetaFeature(
        name='Task Budgets',
        header_value=TASK_BUDGETS,
        provider_families={ProviderFamily.ANTHROPIC},
        required_gate='COMPACT_CACHE_PREFIX',
    ),
    'token_efficient_tools': BetaFeature(
        name='Token-Efficient Tools',
        header_value=TOKEN_EFFICIENT_TOOLS,
        provider_families={ProviderFamily.ANTHROPIC},
        exclusive_with={'structured_outputs'},
    ),
    'fast_mode': BetaFeature(
        name='Fast Mode',
        header_value=FAST_MODE,
        provider_families={ProviderFamily.ANTHROPIC, ProviderFamily.DEEPSEEK},
    ),
    'redact_thinking': BetaFeature(
        name='Redact Thinking',
        header_value=REDACT_THINKING,
        provider_families={ProviderFamily.ANTHROPIC, ProviderFamily.DEEPSEEK},
        exclusive_with={'interleaved_thinking'},
    ),
    'web_search': BetaFeature(
        name='Web Search',
        header_value=WEB_SEARCH,
        provider_families={ProviderFamily.ANTHROPIC},
    ),
    'advisor_tool': BetaFeature(
        name='Advisor Tool',
        header_value=ADVISOR_TOOL,
        provider_families={ProviderFamily.ANTHROPIC},
        required_gate='BUILTIN_AGENTS',
    ),
}


class BetaHeaderManager:
    """Manages beta header injection for LLM API requests.

    Resolution:
    1. Environment variable NEOMIND_BETAS (comma-separated, highest priority)
    2. Feature gate checks (required_gate must be enabled)
    3. Provider family compatibility
    4. Model context window checks
    5. Exclusivity constraints (exclusive_with)
    6. Disable switch: NEOMIND_DISABLE_EXPERIMENTAL_BETAS=1
    """

    # Header name used for Anthropic-family providers
    ANTHROPIC_BETA_HEADER = 'anthropic-beta'
    # Header name for other providers (DeepSeek, etc.)
    EXPERIMENTAL_HEADER = 'X-Experimental'

    def __init__(self):
        self._disabled = os.environ.get(
            'NEOMIND_DISABLE_EXPERIMENTAL_BETAS', ''
        ).strip().lower() in ('1', 'true', 'yes')

    # ── Public API ────────────────────────────────────────────────────

    def get_headers(
        self,
        model: str = '',
        provider: str = '',
        max_context: int = 0,
    ) -> Dict[str, str]:
        """Get beta headers for a specific model/provider combination.

        Args:
            model: Model ID (e.g. 'deepseek-v4-flash')
            provider: Provider name ('deepseek', 'anthropic', etc.)
            max_context: Model's max context window size

        Returns:
            Dict of header name → comma-separated beta values
        """
        if self._disabled:
            return {}

        family = self._resolve_family(provider)
        active = self._resolve_active_betas(family, max_context)
        if not active:
            return {}

        return self._build_header(family, active)

    def get_merged_headers(
        self,
        model: str = '',
        provider: str = '',
        max_context: int = 0,
        extra_betas: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Get beta headers merged with any extra beta values.

        Use this when callers have additional betas from other sources.
        """
        headers = self.get_headers(model, provider, max_context)

        if extra_betas:
            family = self._resolve_family(provider)
            header_name = self._header_name(family)
            existing = headers.get(header_name, '')
            all_values = (existing.split(',') if existing else []) + extra_betas
            headers[header_name] = ','.join(b for b in all_values if b)

        return headers

    def list_active(self, model: str = '', provider: str = '') -> List[str]:
        """List active beta feature names (for debugging)."""
        family = self._resolve_family(provider)
        return sorted(self._resolve_active_betas(family, 0))

    # ── Internal ──────────────────────────────────────────────────────

    def _resolve_family(self, provider: str) -> ProviderFamily:
        provider_lower = provider.lower()
        if 'anthropic' in provider_lower or 'claude' in provider_lower:
            return ProviderFamily.ANTHROPIC
        if 'deepseek' in provider_lower:
            return ProviderFamily.DEEPSEEK
        if 'openai' in provider_lower or 'gpt' in provider_lower:
            return ProviderFamily.OPENAI
        if 'litellm' in provider_lower:
            return ProviderFamily.LITELLM
        # Default to Anthropic conventions for safety
        return ProviderFamily.ANTHROPIC

    def _header_name(self, family: ProviderFamily) -> str:
        if family == ProviderFamily.ANTHROPIC:
            return self.ANTHROPIC_BETA_HEADER
        return self.EXPERIMENTAL_HEADER

    def _resolve_active_betas(
        self, family: ProviderFamily, max_context: int,
    ) -> List[str]:
        active: List[str] = []

        # 1. Environment variable override (highest priority)
        env_betas = os.environ.get('NEOMIND_BETAS', '').strip()
        if env_betas:
            return [b.strip() for b in env_betas.split(',') if b.strip()]

        for name, feature in BETA_FEATURES.items():
            # Provider compatibility
            if family not in feature.provider_families:
                continue

            # Gate check
            if feature.required_gate:
                if not gates.is_enabled(feature.required_gate):
                    continue

            # Context window check
            if feature.min_context > 0 and max_context < feature.min_context:
                continue

            # Exclusivity check
            if feature.exclusive_with:
                if any(e in active for e in feature.exclusive_with):
                    continue

            active.append(feature.header_value)

        return active

    def _build_header(
        self, family: ProviderFamily, values: List[str],
    ) -> Dict[str, str]:
        header_name = self._header_name(family)
        return {header_name: ','.join(values)}


# ── Global singleton ─────────────────────────────────────────────────

_instance: Optional[BetaHeaderManager] = None


def get_beta_headers() -> BetaHeaderManager:
    global _instance
    if _instance is None:
        _instance = BetaHeaderManager()
    return _instance


beta_headers = get_beta_headers()


# ── Convenience: inject into request headers ─────────────────────────

def inject_beta_headers(
    headers: Dict[str, str],
    model: str = '',
    provider: str = '',
    max_context: int = 0,
    extra_betas: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Merge beta headers into an existing headers dict.

    Usage in LLM provider:
        headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
        headers = inject_beta_headers(headers, model=model, provider='deepseek')
    """
    result = dict(headers)
    betas = beta_headers.get_merged_headers(model, provider, max_context, extra_betas)
    result.update(betas)
    return result
