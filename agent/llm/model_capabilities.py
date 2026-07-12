"""Model capability registry — keeps the harness model-agnostic.

Every provider-native feature (native tool-calling, reasoning_effort, prompt
caching, JSON mode, FIM, prefix completion) is gated on a flag here. Call sites
do::

    caps = get_capabilities(model)
    if caps.native_tools:
        ... native OpenAI-style tools/tool_choice ...
    else:
        ... portable fallback (regex tool blocks / prompt-injected JSON) ...

so switching models is a *registry change, not a call-site rewrite*. The
DEFAULT (`PORTABLE`) is the conservative/portable set — everything off — and a
model must opt **in**. An unknown / newly-swapped model therefore falls back to
the old behavior automatically. This is the "leave a placeholder / keep the old
way" guarantee.

Capability values for DeepSeek/GLM were checked against provider docs on
2026-06-14; re-verify against current docs when adding a model. Notably DeepSeek
supports `json_object` but NOT `json_schema` strict (so `json_schema=False` →
the schema-in-prompt fallback is used).
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ModelCapabilities:
    native_tools: bool = False        # OpenAI-style `tools` / `tool_choice`
    strict_tools: bool = False        # server-side JSON-Schema arg validation (beta)
    reasoning_effort: bool = False    # `reasoning_effort` param
    thinking: bool = False            # explicit `thinking` enable/disable toggle
    prompt_cache: bool = False        # reports prompt_cache_hit_tokens (auto KV cache)
    json_mode: bool = False           # response_format {"type": "json_object"}
    json_schema: bool = False         # response_format json_schema strict (DeepSeek: NO)
    fim: bool = False                 # fill-in-the-middle /beta/completions
    prefix_completion: bool = False   # assistant-prefix completion (beta)


# Conservative default — portable everywhere, opt-in only. The safety floor.
PORTABLE = ModelCapabilities()

# DeepSeek V4 (deepseek-v4-flash / -pro) + legacy deepseek-chat: OpenAI-compatible
# native tools, reasoning_effort, thinking, automatic prompt caching, json_object,
# FIM + prefix-completion (beta). No json_schema strict.
_DEEPSEEK = ModelCapabilities(
    native_tools=True,
    strict_tools=True,
    reasoning_effort=True,
    thinking=True,
    prompt_cache=True,
    json_mode=True,
    json_schema=False,
    fim=True,
    prefix_completion=True,
)

# z.ai GLM: OpenAI-compatible tools + json_object. No DeepSeek-specific betas.
_GLM = ModelCapabilities(native_tools=True, json_mode=True)


def get_capabilities(model: str | None, provider: str | None = None) -> ModelCapabilities:
    """Capabilities for a model id. Unknown / swapped → PORTABLE (all fallbacks).

    `provider` is accepted for future disambiguation but model-id prefix is
    authoritative today.
    """
    m = (model or "").strip().lower()
    if m.startswith("deepseek-v4") or m.startswith("deepseek-chat"):
        return _DEEPSEEK
    if m.startswith("deepseek-reasoner"):
        # reasoner-style models historically reject a `tools` array → keep the
        # thinking lever but fall back to portable tool-calling.
        return replace(_DEEPSEEK, native_tools=False, strict_tools=False)
    if m.startswith("glm-"):
        return _GLM
    # Unknown / new / swapped model → portable old behavior (the safety floor).
    return PORTABLE
