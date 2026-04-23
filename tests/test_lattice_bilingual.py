"""V5 · Bilingual output — contract + unit tests.

The output_language YAML switch must route through spec.py's
language_directive helper, get appended to the system prompt at
call time, and be one of the values in spec.OUTPUT_LANGUAGES.

This test file LOCKS the following facts:
  - spec.OUTPUT_LANGUAGES is exhaustively {en, zh-CN-mixed}
  - spec.language_directive("en") returns empty (no behaviour change)
  - spec.language_directive("zh-CN-mixed") returns a non-empty string
    containing the critical "Simplified Chinese" phrase AND the
    English-term preservation clause (tickers, sectors, IV/DTE/VIX)
  - themes._system_prompt() returns base unchanged when taxonomy
    reports en, extended when zh-CN-mixed
  - calls._system_prompt() same
  - Unknown languages fall back to default (no crash)

Actual LLM output verification (does the live DeepSeek reply in
Chinese?) is optional and lives in a lattice_slow integration
test at the bottom of this file — skipped when backend is down.
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from agent.finance.lattice import spec


pytestmark = pytest.mark.lattice_fast


# ── spec-level contract ────────────────────────────────

def test_spec_output_languages_are_exactly_en_and_zh_mixed():
    assert set(spec.OUTPUT_LANGUAGES) == {"en", "zh-CN-mixed"}
    assert spec.OUTPUT_LANGUAGE_DEFAULT == "en"
    assert spec.OUTPUT_LANGUAGE_DEFAULT in spec.OUTPUT_LANGUAGES


def test_language_directive_en_is_empty_string():
    """English directive must be empty — production prompts are
    English natively, so appending an empty string changes nothing
    for backward compatibility."""
    assert spec.language_directive("en") == ""


def test_language_directive_zh_cn_mixed_contains_bilingual_rules():
    """The Chinese directive must explicitly name:
      - Simplified Chinese as the output language
      - Preservation of tickers, sectors, and derivatives terms
        in English
    If anyone weakens these clauses, the directive stops working
    and this test catches it."""
    d = spec.language_directive("zh-CN-mixed")
    assert "Simplified Chinese" in d
    # Preservation clauses for tickers + sectors
    assert "ticker" in d.lower() or "AAPL" in d
    assert "sector" in d.lower()
    # At least a couple of key English-term preservation examples
    assert "IV" in d
    assert "VIX" in d


def test_language_directive_unknown_falls_back_to_default():
    """Typo or mis-config in YAML should NOT raise. Fall back to
    the default (empty for en)."""
    assert spec.language_directive("fr-FR") == ""
    assert spec.language_directive("") == ""
    assert spec.language_directive("zh-CN") == ""  # note: subtly wrong, must fall back


# ── Production wiring: system prompt assembly ──────────

def test_themes_base_prompt_unchanged_by_en_language(monkeypatch):
    """Locking backward compat: when the taxonomy says en, themes.
    _system_prompt() must equal the base prompt exactly. Any
    accidental trailing whitespace or extra sentence would break
    prompt caching AND the LLM's behaviour."""
    from agent.finance.lattice import themes, taxonomy as taxmod

    fake_tax = taxmod.Taxonomy(
        version=1, dimensions={}, themes=[], sub_themes=[],
        output_language="en",
    )
    monkeypatch.setattr(taxmod, "load_taxonomy", lambda *a, **kw: fake_tax)
    monkeypatch.setattr(themes, "load_taxonomy", lambda *a, **kw: fake_tax)
    assert themes._system_prompt() == themes._SYSTEM_PROMPT_BASE


def test_themes_prompt_extended_when_zh_cn_mixed(monkeypatch):
    from agent.finance.lattice import themes, taxonomy as taxmod

    fake_tax = taxmod.Taxonomy(
        version=1, dimensions={}, themes=[], sub_themes=[],
        output_language="zh-CN-mixed",
    )
    monkeypatch.setattr(taxmod, "load_taxonomy", lambda *a, **kw: fake_tax)
    monkeypatch.setattr(themes, "load_taxonomy", lambda *a, **kw: fake_tax)
    p = themes._system_prompt()
    assert p.startswith(themes._SYSTEM_PROMPT_BASE)
    assert "Simplified Chinese" in p
    assert len(p) > len(themes._SYSTEM_PROMPT_BASE)


def test_calls_base_prompt_unchanged_by_en_language(monkeypatch):
    from agent.finance.lattice import calls as calls_mod, taxonomy as taxmod

    fake_tax = taxmod.Taxonomy(
        version=1, dimensions={}, themes=[], sub_themes=[],
        output_language="en",
    )
    monkeypatch.setattr(taxmod, "load_taxonomy", lambda *a, **kw: fake_tax)
    assert calls_mod._system_prompt() == calls_mod._SYSTEM_PROMPT_BASE


def test_calls_prompt_extended_when_zh_cn_mixed(monkeypatch):
    from agent.finance.lattice import calls as calls_mod, taxonomy as taxmod

    fake_tax = taxmod.Taxonomy(
        version=1, dimensions={}, themes=[], sub_themes=[],
        output_language="zh-CN-mixed",
    )
    monkeypatch.setattr(taxmod, "load_taxonomy", lambda *a, **kw: fake_tax)
    p = calls_mod._system_prompt()
    assert p.startswith(calls_mod._SYSTEM_PROMPT_BASE)
    assert "Simplified Chinese" in p


# ── Taxonomy loader: YAML switch wiring ────────────────

def test_taxonomy_loads_output_language_from_yaml(tmp_path):
    yaml_body = dedent("""
        version: 1
        output_language: zh-CN-mixed
        dimensions:
          symbol:
            description: "x"
          market:
            valid_values: [US]
        themes: []
    """).strip()
    p = tmp_path / "tax.yaml"
    p.write_text(yaml_body, encoding="utf-8")
    from agent.finance.lattice.taxonomy import load_taxonomy
    t = load_taxonomy(path=p)
    assert t.output_language == "zh-CN-mixed"


def test_taxonomy_defaults_to_en_when_yaml_omits_language(tmp_path):
    yaml_body = dedent("""
        version: 1
        dimensions:
          symbol:
            description: "x"
        themes: []
    """).strip()
    p = tmp_path / "tax.yaml"
    p.write_text(yaml_body, encoding="utf-8")
    from agent.finance.lattice.taxonomy import load_taxonomy
    t = load_taxonomy(path=p)
    assert t.output_language == spec.OUTPUT_LANGUAGE_DEFAULT


def test_taxonomy_falls_back_to_default_on_invalid_language(tmp_path, caplog):
    yaml_body = dedent("""
        version: 1
        output_language: klingon
        dimensions:
          symbol:
            description: "x"
        themes: []
    """).strip()
    p = tmp_path / "tax.yaml"
    p.write_text(yaml_body, encoding="utf-8")
    from agent.finance.lattice.taxonomy import load_taxonomy
    import logging
    with caplog.at_level(logging.WARNING):
        t = load_taxonomy(path=p)
    assert t.output_language == spec.OUTPUT_LANGUAGE_DEFAULT
    # Warning must be emitted so a silent misconfig is visible in logs
    assert any("klingon" in r.message or "unknown" in r.message
               for r in caplog.records)


# ── Shipped YAML: real file check ──────────────────────

def test_shipped_taxonomy_has_valid_output_language():
    from agent.finance.lattice.taxonomy import load_taxonomy
    t = load_taxonomy()
    assert t.output_language in spec.OUTPUT_LANGUAGES


# ── Live integration (slow, skip when backend/LLM unavailable) ──

@pytest.mark.lattice_slow
def test_live_narrative_contains_chinese_when_switched(monkeypatch):
    """Switch taxonomy to zh-CN-mixed, bust the narrative cache,
    and verify the live narrative for at least one theme contains
    at least one CJK unified ideograph. Requires a live backend +
    DeepSeek."""
    import os
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("no DEEPSEEK_API_KEY")
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=3) as r:
            if r.status != 200:
                pytest.skip("backend unreachable")
    except Exception:
        pytest.skip("backend unreachable")

    from agent.finance.lattice import themes, taxonomy as taxmod
    real_tax = taxmod.load_taxonomy()
    forced = taxmod.Taxonomy(
        version=real_tax.version,
        dimensions=real_tax.dimensions,
        themes=real_tax.themes,
        sub_themes=real_tax.sub_themes,
        output_language="zh-CN-mixed",
    )
    monkeypatch.setattr(taxmod, "load_taxonomy", lambda *a, **kw: forced)
    monkeypatch.setattr(themes, "load_taxonomy", lambda *a, **kw: forced)
    # Bust the narrative cache so we hit the LLM with the new prompt
    themes._narrative_cache.clear()

    from agent.finance.lattice.observations import Observation
    members = [(
        Observation(id="obs_test_001", kind="earnings_soon",
                    text="AAPL reports in 7d (2026-04-30).",
                    tags=["symbol:AAPL", "risk:earnings"],
                    numbers={"days_until": 7}, severity="warn"),
        0.85,
    )]
    result = themes.generate_narrative(
        "theme_earnings_risk", "Earnings risk", members, fresh=True,
    )
    narrative = result["narrative"]
    # CJK Unified Ideographs range U+4E00 .. U+9FFF
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in narrative)
    assert has_cjk, f"expected Chinese characters, got: {narrative!r}"
    # AAPL preserved in English
    assert "AAPL" in narrative
