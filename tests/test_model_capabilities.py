"""Unit tests for agent.llm.model_capabilities.

Run:  python3 tests/test_model_capabilities.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.llm.model_capabilities import (  # noqa: E402
    PORTABLE,
    ModelCapabilities,
    get_capabilities,
)


def test_deepseek_v4_is_native():
    for model in ("deepseek-v4-flash", "deepseek-v4-pro", "DeepSeek-V4-Flash"):
        c = get_capabilities(model)
        assert c.native_tools is True, model
        assert c.reasoning_effort is True, model
        assert c.thinking is True, model
        assert c.prompt_cache is True, model
        assert c.json_mode is True, model
        # DeepSeek supports json_object but NOT json_schema strict → fallback
        assert c.json_schema is False, model


def test_glm_is_native_tools_no_betas():
    c = get_capabilities("glm-5")
    assert c.native_tools is True
    assert c.json_mode is True
    assert c.reasoning_effort is False   # no DeepSeek-specific levers
    assert c.fim is False


def test_unknown_model_falls_back_to_portable():
    # THE model-swap-safety guarantee: a new/unknown model gets the portable
    # (all-off) set, so every call site auto-uses its old/fallback path.
    for model in ("gpt-5", "claude-opus-4-8", "llama-9", "some-future-model", ""):
        c = get_capabilities(model)
        assert c == PORTABLE, model
        assert c.native_tools is False, model
        assert c.reasoning_effort is False, model


def test_none_model_is_portable():
    assert get_capabilities(None) == PORTABLE


def test_reasoner_keeps_thinking_drops_native_tools():
    c = get_capabilities("deepseek-reasoner")
    assert c.native_tools is False     # reasoner rejects a tools array → fallback
    assert c.thinking is True


def test_portable_is_all_off():
    c = ModelCapabilities()
    assert c == PORTABLE
    for field in (
        "native_tools", "strict_tools", "reasoning_effort", "thinking",
        "prompt_cache", "json_mode", "json_schema", "fim", "prefix_completion",
    ):
        assert getattr(c, field) is False, field


def test_frozen_immutable():
    c = get_capabilities("deepseek-v4-flash")
    try:
        c.native_tools = False  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("ModelCapabilities should be frozen/immutable")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
