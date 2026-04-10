"""NeoMind Dynamic Prompt Composer

Mirrors Claude Code's SYSTEM_PROMPT_DYNAMIC_BOUNDARY pattern:
- Static section: Identity, rules, thinking style (cacheable)
- Dynamic section: User preferences, memory, tools, mode context (per-turn)

This replaces the monolithic system_prompt YAML string with a modular
composition system that saves tokens via caching and adapts per-turn.

Architecture:
    DynamicPromptComposer
        ├── StaticSection (personality identity + rules)
        ├── ToolSection (auto-generated from ToolRegistry)
        ├── MemorySection (injected from SharedMemory)
        ├── ContextSection (workspace, project info)
        └── ModeSection (personality-specific additions)
"""

import logging
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)

# ─── The boundary marker (like Claude Code's SYSTEM_PROMPT_DYNAMIC_BOUNDARY) ──
PROMPT_DYNAMIC_BOUNDARY = "\n\n# ═══ DYNAMIC CONTEXT (below this line changes per-turn) ═══\n\n"


class PromptSection:
    """A single section of the system prompt.

    Attributes:
        name: Section identifier for debugging
        content: The text content
        cacheable: Whether this section is stable enough to cache
        priority: Higher priority sections appear first (0 = highest)
    """

    def __init__(
        self,
        name: str,
        content: str,
        cacheable: bool = True,
        priority: int = 50,
    ):
        self.name = name
        self.content = content
        self.cacheable = cacheable
        self.priority = priority

    def __repr__(self):
        return f"PromptSection({self.name}, {len(self.content)} chars, cache={self.cacheable})"


class DynamicPromptComposer:
    """Compose system prompts from modular sections.

    Mirrors Claude Code's context.ts + prompts.ts architecture:
    - Static sections are assembled once and cached
    - Dynamic sections are rebuilt every turn
    - Tool prompts are auto-generated from the registry

    Usage:
        composer = DynamicPromptComposer()
        composer.set_static("identity", "You are NeoMind...")
        composer.set_static("rules", "FORBIDDEN PATTERNS...")
        prompt = composer.compose(mode="coding", tool_registry=registry)
    """

    def __init__(self):
        self._static_sections: Dict[str, PromptSection] = {}
        self._dynamic_providers: List[Callable[..., Optional[PromptSection]]] = []
        self._cached_static: Optional[str] = None
        self._cache_dirty = True

    # ── Static section management ──────────────────────────────────────

    def set_static(self, name: str, content: str, priority: int = 50):
        """Set a static (cacheable) prompt section.

        Static sections don't change between turns. Examples:
        - Identity ("You are NeoMind...")
        - Rules ("FORBIDDEN PATTERNS...")
        - Thinking style

        Args:
            name: Unique section name
            content: Section text
            priority: Sort order (lower = earlier in prompt)
        """
        self._static_sections[name] = PromptSection(
            name=name,
            content=content,
            cacheable=True,
            priority=priority,
        )
        self._cache_dirty = True

    def remove_static(self, name: str):
        """Remove a static section."""
        if name in self._static_sections:
            del self._static_sections[name]
            self._cache_dirty = True

    # ── Dynamic section providers ──────────────────────────────────────

    def add_dynamic_provider(self, provider: Callable[..., Optional[PromptSection]]):
        """Register a provider that generates dynamic prompt content.

        Providers are called every turn with (mode, tool_registry, budget)
        and should return a PromptSection or None.

        Examples of dynamic providers:
        - Tool schema generator
        - Memory context injector
        - Workspace file list
        """
        self._dynamic_providers.append(provider)

    # ── Composition ────────────────────────────────────────────────────

    def compose(
        self,
        mode: str = "chat",
        tool_registry=None,
        budget=None,
        extra_context: Optional[Dict[str, str]] = None,
    ) -> str:
        """Compose the full system prompt.

        Returns the complete prompt with static and dynamic sections
        separated by PROMPT_DYNAMIC_BOUNDARY.

        Args:
            mode: Current personality mode (chat/coding/fin)
            tool_registry: ToolRegistry for auto-generating tool prompts
            budget: TokenBudget for usage info
            extra_context: Additional key-value pairs to inject

        Returns:
            Complete system prompt string
        """
        parts = []

        # 1. Static section (cached)
        static_text = self._get_cached_static()
        if static_text:
            parts.append(static_text)

        # 2. Boundary marker
        parts.append(PROMPT_DYNAMIC_BOUNDARY)

        # 3. Dynamic sections
        dynamic_sections = []

        # 3a. Tool system (auto-generated from registry)
        if tool_registry:
            tool_section = self._build_tool_section(tool_registry)
            if tool_section:
                dynamic_sections.append(tool_section)

        # 3b. Run all dynamic providers
        for provider in self._dynamic_providers:
            try:
                section = provider(
                    mode=mode,
                    tool_registry=tool_registry,
                    budget=budget,
                )
                if section:
                    dynamic_sections.append(section)
            except Exception as e:
                logger.warning(f"Dynamic provider failed: {e}")

        # 3c. Extra context
        if extra_context:
            for key, value in extra_context.items():
                dynamic_sections.append(PromptSection(
                    name=f"extra_{key}",
                    content=f"# {key}\n{value}",
                    cacheable=False,
                    priority=80,
                ))

        # 3d. Budget info (if approaching limits)
        if budget and budget.usage_ratio > 0.5:
            dynamic_sections.append(PromptSection(
                name="budget_status",
                content=(
                    f"# Context Budget Status\n"
                    f"Usage: {budget.usage_ratio:.0%} of {budget.max_context_tokens} tokens. "
                    f"{'⚠️ Approaching limit — be concise.' if budget.usage_ratio > 0.7 else ''}"
                ),
                cacheable=False,
                priority=90,
            ))

        # Sort dynamic sections by priority and join
        dynamic_sections.sort(key=lambda s: s.priority)
        for section in dynamic_sections:
            parts.append(section.content)

        return "\n\n".join(parts)

    def _get_cached_static(self) -> str:
        """Get the static portion, rebuilding cache if dirty."""
        if self._cache_dirty or self._cached_static is None:
            sections = sorted(
                self._static_sections.values(),
                key=lambda s: s.priority,
            )
            self._cached_static = "\n\n".join(s.content for s in sections)
            self._cache_dirty = False
        return self._cached_static

    def _build_tool_section(self, tool_registry) -> Optional[PromptSection]:
        """Auto-generate tool system prompt from registry.

        Mirrors Claude Code's per-tool prompt.ts pattern:
        each tool contributes its own schema to the system prompt.
        """
        try:
            # Use the existing generate_tool_prompt function
            from agent.coding.tool_schema import generate_tool_prompt
            tools = tool_registry.get_all_definitions()
            if tools:
                prompt_text = generate_tool_prompt(tools)
                return PromptSection(
                    name="tool_system",
                    content=prompt_text,
                    cacheable=False,  # Tools can change (MCP dynamic)
                    priority=20,
                )
        except Exception as e:
            logger.warning(f"Failed to build tool section: {e}")
        return None

    # ── Convenience: load from YAML config ────────────────────────────

    @classmethod
    def from_config(cls, config) -> "DynamicPromptComposer":
        """Create a composer pre-loaded with the current config's prompt.

        Splits the monolithic system_prompt into static sections.

        Args:
            config: AgentConfigManager instance

        Returns:
            Pre-configured DynamicPromptComposer
        """
        composer = cls()

        # Load the full system prompt from config
        system_prompt = config.system_prompt or ""

        if system_prompt:
            # Split into logical sections
            # The YAML prompts have clear section markers (═══)
            sections = _split_prompt_sections(system_prompt)
            for i, (name, content) in enumerate(sections):
                composer.set_static(name, content, priority=i * 10)

        return composer


def _split_prompt_sections(prompt: str) -> List[tuple]:
    """Split a monolithic prompt into named sections.

    Detects section headers like ═══ SECTION NAME ═══ and splits on them.
    Falls back to treating the whole prompt as one section.
    """
    import re
    # Match: ═══ SECTION NAME ═══ or similar Unicode box-drawing headers
    pattern = r"═{3,}\s*(.+?)\s*═{3,}"
    parts = re.split(pattern, prompt)

    if len(parts) <= 1:
        # No section headers found — treat as single section
        return [("identity", prompt)]

    sections = []
    # parts[0] is text before first header
    if parts[0].strip():
        sections.append(("preamble", parts[0].strip()))

    # pairs: (header_name, content)
    for i in range(1, len(parts), 2):
        name = parts[i].strip().lower().replace(" ", "_")
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            sections.append((name, content))

    return sections if sections else [("identity", prompt)]
