"""NeoMind Telegram Validation Suite — v1 (2026-04-10)

Authoritative scenario library for Phase B validation of the slash-command
taxonomy v5 cleanup and subsequent tool refactor. Every scenario sends a
REAL message via Telethon to @neomindagent_bot and verifies the REAL
reply — no mocks, no pexpect, no harness sanitization.

This file is the single source of truth for what "tested" means in this
session. Tester subagents reference subsets by name (e.g. `gate_0`,
`gate_b3`) via the SUBSETS dict.

Role contract:
  - This file is data. Tester agents IMPORT it, do not modify.
  - Fixer agents never run the scenarios; they only read reports.

Scenario tuple format:
  (sid, send_text, wait_seconds, expect_any_substrings, category)

Categories:
  R  — regression baseline (30)    — catches breakage in pre-existing features
  F  — fallthrough (10)             — validates 4847c6a graceful slash fallthrough
  D  — deletion graceful (6)        — validates ff141eb (archive/purge/setctx/memory)
  T  — /tune subcommands (8)        — validates ff141eb /tune promotion
  A  — Tier 4 admin (12)            — validates real-handler commands post-cleanup
  N  — NL tool triggering (15)      — fin-mode natural-language → tool call (Phase B.3+)
  E  — dual-entry equivalence (6)   — slash vs natural language consistency (Phase B.5+)
  C  — context / multi-turn (8)     — conversation stability
  X  — edge cases (10)              — stress / invalid input
  G  — group chat (8, optional)     — group-chat slash + mention handling

Gate subsets:
  gate_0   — R + F + D + T + A = 66 scenarios (retroactive for 4847c6a+ff141eb+eea40a0)
  gate_b3  — gate_0 + N = 81 scenarios (after fin tools wired into agentic loop)
  gate_b5  — gate_b3 + E = 87 scenarios (after Tier 2 slash thin-wrapper refactor)
  gate_b6  — gate_b5 + dual-entry specific = ~90 scenarios
  final    — all 108 scenarios (end of Phase B)

The comprehensive validation gate MAY tolerate a small number of pre-existing
flakes (S03 / S06 / U01 / U02 in the original 30-scenario baseline) if they
were already failing before this session. Hard thresholds are documented in
plans/2026-04-10_slash-command-taxonomy-v5-with-validation.md.
"""

from __future__ import annotations
from typing import Dict, List, Tuple

Scenario = Tuple[str, str, int, List[str], str]


# ── R — Regression baseline (30) ──────────────────────────────────────

R_SCENARIOS: List[Scenario] = [
    # Finance — direct data-hub and fin-mode reasoning (6)
    ("R_F01", "/quant CAGR 100 200 5", 90, ["CAGR", "%", "14"], "R"),
    ("R_F02", "/quant compound 10000 0.08 10", 90,
        ["compound", "复利", "$", "21", "%"], "R"),
    ("R_F03", "如何用 DCF 给成长股估值? 核心假设是什么? 不要搜索", 120,
        ["DCF", "现金流", "折现", "永续", "增长", "WACC"], "R"),
    ("R_F04", "解释一下 Fama-French 三因子模型, 不要搜索", 120,
        ["Fama", "French", "市值", "价值", "size", "value", "market"], "R"),
    ("R_F05", "什么是 Sharpe ratio vs Sortino ratio 的区别? 不要搜索", 120,
        ["Sharpe", "Sortino", "下行", "波动", "风险"], "R"),
    ("R_F06", "巴菲特的 economic moat 概念有哪几种? 不要搜索", 120,
        ["moat", "护城河", "品牌", "网络", "成本", "规模"], "R"),

    # Mode + model switching (6)
    ("R_M01", "/mode fin", 10, ["fin", "已切换", "已经"], "R"),
    ("R_M02", "/model", 15, ["kimi-k2.5", "fin"], "R"),
    ("R_M03", "/mode coding", 10, ["coding", "已切换", "已经"], "R"),
    ("R_M04", "/model", 15, ["deepseek-chat", "coding"], "R"),
    ("R_M05", "/mode fin", 10, ["fin", "已切换", "已经"], "R"),
    ("R_M06", "/status", 15, ["mode", "model", "Router", "router", "🤖"], "R"),

    # Short Chinese Q&A — knowledge, no real-time data (6)
    ("R_Q01", "什么是市盈率? 不要搜索, 直接告诉我", 90, ["市盈率", "PE", "盈利"], "R"),
    ("R_Q02", "什么是夏普比率? 不要搜索", 90, ["夏普", "Sharpe", "波动"], "R"),
    ("R_Q03", "什么是 ETF? 直接回答, 不要搜索", 90, ["ETF", "基金", "fund"], "R"),
    ("R_Q04", "解释一下美元微笑理论, 不要搜索", 90, ["美元", "微笑", "dollar"], "R"),
    ("R_Q05", "什么是 DCA 定投? 不要搜索", 90, ["DCA", "定投", "average"], "R"),
    ("R_Q06", "什么是 risk parity? 不要搜索", 90, ["risk parity", "风险平价", "权重"], "R"),

    # Search behavior (6)
    ("R_S01", "今天 SPY 收盘价是多少", 90, ["SPY", "$", "美元", "收盘"], "R"),
    ("R_S02", "今天美元指数是多少", 90, ["美元", "DXY", "指数"], "R"),
    ("R_S03", "Just from your knowledge: name 3 Buffett quotes (no search)",
        60, ["Buffett", "巴菲特"], "R"),
    ("R_S04", "今天 BTC 多少美元", 90, ["BTC", "$"], "R"),
    ("R_S05", "Without searching: explain CAPM", 90,
        ["CAPM", "beta", "premium", "市场"], "R"),
    ("R_S06", "今天最大的财经新闻是什么", 90,
        ["新闻", "news", "today", "今天"], "R"),

    # System commands (6)
    ("R_U01", "/status", 15, ["mode", "model", "🤖", "Router", "router"], "R"),
    ("R_U02", "/context", 15, ["context", "token", "messages", "消息"], "R"),
    ("R_U03", "/usage", 15, ["usage", "tokens", "$", "费用", "成本", "调用"], "R"),
    ("R_U04", "/help", 15, ["help", "命令", "command"], "R"),
    ("R_U05", "/think", 10, ["think", "思考", "ON", "OFF"], "R"),
    ("R_U06", "/clear", 15, ["clear", "清空", "已", "✓", "归档"], "R"),
]


# ── F — Graceful slash fallthrough (10) ───────────────────────────────
# Validates commit 4847c6a: deleted pseudo-commands should fall through to
# natural-language processing without "unknown command" errors.

F_SCENARIOS: List[Scenario] = [
    ("F_F01", "/summarize 苹果公司 一句话介绍", 60,
        ["苹果", "Apple", "科技", "iPhone"], "F"),
    ("F_F02", "/explain 什么是 Black-Scholes 模型 不要搜索", 90,
        ["Black-Scholes", "期权", "定价", "波动率"], "F"),
    ("F_F03", "/tldr 给我用一句话解释什么叫流动性陷阱 不要搜索", 60,
        ["流动性", "陷阱", "利率", "零"], "F"),
    ("F_F04", "/deep 用一段话解释对冲基金多空策略 不要搜索", 90,
        ["对冲", "多空", "long", "short", "策略"], "F"),
    ("F_F05", "/refactor 这段话更简洁: 请问你能告诉我现在几点吗", 45,
        ["几点", "现在", "time"], "F"),
    ("F_F06", "/translate 牛市 英文是什么 不要搜索", 30,
        ["bull", "market"], "F"),
    ("F_F07", "/totallyfake 用一句话解释 CAPM 不要搜索", 60,
        ["CAPM", "beta", "市场", "Rf", "无风险"], "F"),
    ("F_F08", "/randomword 给我今天心情低落时的三句鼓励 不要搜索", 60,
        ["心情", "鼓励", "加油", "前行", "坚持"], "F"),
    ("F_F09", "/unknownxyz 巴菲特最著名的投资原则 不要搜索", 60,
        ["巴菲特", "Buffett", "价值", "长期"], "F"),
    ("F_F10", "/nonexistentcmd 一句话解释什么是流动性溢价 不要搜索", 60,
        ["流动性", "溢价", "premium"], "F"),
]


# ── D — Deletion graceful handling (6) ────────────────────────────────
# Validates commit ff141eb: /archive /purge /setctx /memory deletions.

D_SCENARIOS: List[Scenario] = [
    # Deleted commands fall through to natural language — expect any reply
    # that is NOT an error (any non-empty non-"未知命令" response is OK).
    ("D01", "/archive", 30, ["archive", "归档", "清空", "保存", "备份", "checkpoint"], "D"),
    ("D02", "/purge 历史", 30, ["purge", "删除", "清理", "归档", "history"], "D"),
    ("D03", "/setctx mykey myvalue", 30, ["context", "set", "key", "value", "无法", "不理解", "?"], "D"),
    ("D04", "/memory", 30, ["memory", "记忆", "dump", "admin", "?"], "D"),
    # Canonical replacements must still work
    ("D05", "/clear", 15, ["归档", "清空", "✓", "已"], "D"),
    ("D06", "/admin stats", 20, ["Stats", "database", "messages", "总数", "chats", "stats"], "D"),
]


# ── T — /tune sub-commands (8) ────────────────────────────────────────
# Validates commit ff141eb: /tune promoted to Tier 1 and its subcommands work.

T_SCENARIOS: List[Scenario] = [
    ("T01", "/tune", 15, ["tune", "prompt", "reset", "trigger", "status"], "T"),
    # Empty-state reply is "📋 No custom overrides — using all defaults."
    # — match on the English words the bot actually uses, not the Chinese
    # ones I assumed in v1.
    ("T02", "/tune status", 15,
        ["overrides", "defaults", "custom", "📋", "配置"], "T"),
    ("T03", "/tune prompt 回复请更简洁些", 20,
        ["已", "追加", "prompt", "更简洁"], "T"),
    ("T04", "/tune status", 15, ["更简洁"], "T"),  # confirms T03 persisted
    ("T05", "/tune trigger add 半导体", 15,
        ["已", "添加", "trigger", "半导体"], "T"),
    ("T06", "/tune reset", 15,
        ["已重置", "重置", "reset", "默认"], "T"),
    # Post-reset state returns to "No custom overrides" English empty state.
    ("T07", "/tune status", 15,
        ["overrides", "defaults", "No custom", "📋"], "T"),
    ("T08", "/tune 让搜索结果更偏向中文新闻源", 45,
        ["已", "中文", "新闻", "搜索", "源", "trigger"], "T"),
]


# ── A — Tier 4 admin coverage (12) ────────────────────────────────────
# Verify every real-handler command still works after cleanup.

A_SCENARIOS: List[Scenario] = [
    ("A01", "/sprint", 15, ["Sprint", "new", "status", "next"], "A"),
    ("A02", "/sprint new 研究 AAPL 估值", 30,
        ["Sprint", "✅", "id", "created"], "A"),
    ("A03", "/sprint status", 15,
        ["Sprint", "phase", "进度", "status", "no active"], "A"),
    ("A04", "/evidence", 15,
        ["Evidence", "trail", "audit", "entries", "记录", "log"], "A"),
    ("A05", "/careful", 15,
        ["careful", "ON", "OFF", "safety", "guard"], "A"),
    ("A06", "/persona list", 15,
        ["persona", "投资", "价值", "增长", "contrarian"], "A"),
    ("A07", "/rag stats", 15,
        ["RAG", "stats", "索引", "文档", "enabled", "未启用"], "A"),
    ("A08", "/skills", 15,
        ["skills", "available", "mode", "skill", "模式"], "A"),
    ("A09", "/hn top", 45,
        ["Hacker News", "HN", "top", "upvotes", "story", "news.ycombinator"], "A"),
    ("A10", "/hooks", 15,
        ["hooks", "钩子", "diagnostic", "registered", "active"], "A"),
    # /history reply on empty chat is "没有对话记录" (Chinese) — the
    # original v1 keywords were wrong. Accept either empty-state Chinese
    # or the verbose English "history active messages" form.
    ("A11", "/history", 15,
        ["对话", "记录", "messages", "history", "active", "消息", "没有"], "A"),
    ("A12", "/admin stats", 15,
        ["Stats", "database", "messages", "总数", "chats"], "A"),
]


# ── N — Fin-mode NL tool triggering (15, Phase B.3+) ──────────────────
# Post Phase B.3-B.5: natural language in fin mode should trigger
# finance_* tool calls and return real data synthesized by the LLM.

N_SCENARIOS: List[Scenario] = [
    ("N01", "苹果今天股价大概多少", 90, ["Apple", "AAPL", "$"], "N"),
    ("N02", "特斯拉今天收盘价", 90, ["TSLA", "Tesla", "$"], "N"),
    ("N03", "BTC 今天多少美元", 90, ["BTC", "Bitcoin", "$"], "N"),
    ("N04", "ETH 今天现价", 90, ["ETH", "Ethereum", "$"], "N"),
    ("N05", "今天美股三大指数怎么样", 120,
        ["S&P", "纳斯达克", "道琼斯", "指数"], "N"),
    ("N06", "给我今天的市场摘要", 120,
        ["市场", "digest", "今日", "摘要"], "N"),
    ("N07", "帮我算一下 10000 元 8% 年化复利 10 年的终值", 60,
        ["21589", "21,589", "$21", "2.158"], "N"),
    ("N08", "初值 100 终值 200 五年的 CAGR 是多少", 60,
        ["14.87", "14.87%", "CAGR"], "N"),
    ("N09", "最近有什么关于半导体的新闻", 120,
        ["半导体", "芯片", "新闻", "TSMC", "SMCI", "chip"], "N"),
    ("N10", "下周有什么重要经济数据发布", 90,
        ["CPI", "PPI", "NFP", "PMI", "日", "发布"], "N"),
    ("N11", "假设 AAPL 年化 20% 波动 30% 无风险 4% 它的 Sharpe 比率大概多少", 60,
        ["Sharpe", "0.5", "0.53", "0.6"], "N"),
    ("N12", "显示我的持仓列表", 30,
        ["portfolio", "持仓", "holdings", "empty", "空"], "N"),
    ("N13", "显示我的关注列表", 30,
        ["watchlist", "关注", "empty", "list", "空"], "N"),
    ("N14", "从价值投资角度分析 AAPL", 120,
        ["价值", "Buffett", "Graham", "moat", "安全边际"], "N"),
    ("N15", "从文档里查 Apple 的最新营收指引", 60,
        ["Apple", "营收", "revenue", "guidance", "未启用"], "N"),
]


# ── E — Dual-entry equivalence (6, Phase B.5+) ────────────────────────
# Pairs of (slash, natural language) that should return equivalent data.
# Thin-wrapper refactor means both entries hit the same tool function.

E_SCENARIOS: List[Scenario] = [
    ("E01", "/stock AAPL", 45, ["AAPL", "Apple", "$"], "E"),
    ("E02", "苹果今天多少钱", 90, ["Apple", "AAPL", "$"], "E"),
    ("E03", "/crypto BTC", 45, ["BTC", "Bitcoin", "$"], "E"),
    ("E04", "BTC 现价", 90, ["BTC", "Bitcoin", "$"], "E"),
    ("E05", "/persona list", 15, ["价值", "增长", "contrarian"], "E"),
    ("E06", "列出所有可用的投资人格", 60, ["价值", "增长", "contrarian"], "E"),
]


# ── C — Context / multi-turn (8) ──────────────────────────────────────

C_SCENARIOS: List[Scenario] = [
    ("C01", "假设我持有 100 股 AAPL", 60,
        ["持有", "noted", "了解", "Apple", "100"], "C"),
    ("C02", "如果股价涨到 300 我赚多少", 90,
        ["赚", "profit", "收益", "30000", "$30"], "C"),
    ("C03", "/clear", 15, ["归档", "clear", "✓", "已"], "C"),
    ("C04", "如果股价涨到 300 我赚多少", 90,
        ["哪个", "什么股票", "没有上下文", "请告诉", "clarify"], "C"),
    ("C05", "今天天气不错", 45, ["天气", "weather", "好", "nice"], "C"),
    ("C06", "/context", 15, ["Context", "tokens", "messages", "occupancy"], "C"),
    ("C07", "用一句话讲一个关于程序员的冷笑话", 45,
        ["程序员", "bug", "代码", "?", "！"], "C"),
    ("C08",
        "请用一段话解释量化投资的三个核心要素，每个要素至少用两句话描述，总共 300 字以内，不要搜索",
        120, ["量化", "因子", "策略", "回测"], "C"),
]


# ── X — Edge cases (10) ───────────────────────────────────────────────

X_SCENARIOS: List[Scenario] = [
    ("X01", "//status", 20,
        ["status", "mode", "router", "?", "unknown"], "X"),
    ("X02", "/", 15, ["help", "?", "命令"], "X"),
    ("X03", "/stock", 15, ["Usage", "用法", "symbol"], "X"),
    ("X04", "/stock XYZNOTREAL999", 45,
        ["not found", "未找到", "No data", "⚠", "无"], "X"),
    ("X05", "/crypto", 15, ["Usage", "用法", "symbol"], "X"),
    ("X06", "/mode invalidmode", 15,
        ["invalid", "chat", "coding", "fin", "unknown", "?"], "X"),
    ("X07", "/model nonexistent-model-xxx", 15,
        ["not found", "invalid", "unknown", "available"], "X"),
    ("X08", "🚀🚀🚀 你好", 30,
        ["你好", "hello", "🚀", "?"], "X"),
    ("X09", "你好", 30, ["你好", "hello", "hi"], "X"),
    ("X10",
        "请你总结 NeoMind 这个项目的几个核心特性，包括自我进化、多模式、金融工具、代码编辑等。" * 3,
        120, ["NeoMind", "进化", "模式", "工具"], "X"),
]


# ── G — Group chat (8, OPTIONAL — skip if no test group) ──────────────

G_SCENARIOS: List[Scenario] = [
    ("G01", "/status@neomindagent_bot", 15, ["status", "kimi", "router"], "G"),
    ("G02", "@neomindagent_bot 苹果今天多少钱", 90, ["Apple", "AAPL", "$"], "G"),
    ("G03", "/stock@neomindagent_bot AAPL", 30, ["AAPL", "$"], "G"),
    ("G04", "/clear@neomindagent_bot", 15, ["归档", "clear"], "G"),
    ("G05", "random message no mention no slash", 10, [], "G"),  # expect NO reply
    ("G06", "/help@neomindagent_bot", 15, ["commands", "help", "命令"], "G"),
    ("G07", "@neomindagent_bot 什么是 PE 不要搜索", 90, ["市盈率", "PE"], "G"),
    ("G08", "/mode@neomindagent_bot fin", 15, ["fin", "已切换"], "G"),
]


# ── Combined registry ─────────────────────────────────────────────────

ALL_SCENARIOS: List[Scenario] = (
    R_SCENARIOS
    + F_SCENARIOS
    + D_SCENARIOS
    + T_SCENARIOS
    + A_SCENARIOS
    + N_SCENARIOS
    + E_SCENARIOS
    + C_SCENARIOS
    + X_SCENARIOS
    + G_SCENARIOS
)

SCENARIOS_BY_SID: Dict[str, Scenario] = {
    s[0]: s for s in ALL_SCENARIOS
}


# ── Gate subsets ──────────────────────────────────────────────────────
# Named scenario subsets that each phase gate runs. Tester subagents
# reference these names, never enumerate SIDs by hand.

SUBSETS: Dict[str, List[Scenario]] = {
    # Retroactive validation for commits 4847c6a + ff141eb + eea40a0
    "gate_0": R_SCENARIOS + F_SCENARIOS + D_SCENARIOS + T_SCENARIOS + A_SCENARIOS,

    # After Phase B.2 (fin tools module written but not wired)
    "gate_b2": R_SCENARIOS + F_SCENARIOS + D_SCENARIOS + T_SCENARIOS + A_SCENARIOS,

    # After Phase B.3 (fin tools wired into agentic loop with mode gating)
    "gate_b3": (
        R_SCENARIOS + F_SCENARIOS + D_SCENARIOS + T_SCENARIOS + A_SCENARIOS
        + N_SCENARIOS
    ),

    # After Phase B.5 (Tier 2 slash thin-wrapper refactor)
    "gate_b5": (
        R_SCENARIOS + F_SCENARIOS + D_SCENARIOS + T_SCENARIOS + A_SCENARIOS
        + N_SCENARIOS + E_SCENARIOS
    ),

    # After Phase B.6 (3 dual-entry tools)
    "gate_b6": (
        R_SCENARIOS + F_SCENARIOS + D_SCENARIOS + T_SCENARIOS + A_SCENARIOS
        + N_SCENARIOS + E_SCENARIOS
    ),

    # Final comprehensive run (end of Phase B)
    "final": ALL_SCENARIOS,  # includes C, X, G if available

    # Smoke subset for quick sanity check
    "smoke": R_SCENARIOS[:8] + F_SCENARIOS[:2] + D_SCENARIOS[:2],
}


# ── Pass thresholds per gate ──────────────────────────────────────────
# Minimum PASS counts required for a gate to be considered validated.
# Flakes in R_S03 / R_S06 / R_U01 / R_U02 are tolerated because they
# were pre-existing before this session.

GATE_THRESHOLDS: Dict[str, Dict[str, int]] = {
    "gate_0": {
        "R": 28,   # tolerate up to 2 pre-existing flakes
        "F": 10,   # all must pass
        "D": 6,    # all must pass
        "T": 8,    # all must pass
        "A": 10,   # tolerate up to 2 module-init issues
    },
    "gate_b3": {
        "R": 28, "F": 10, "D": 6, "T": 8, "A": 10,
        "N": 12,   # tolerate 3 tool-call hallucination flakes
    },
    "gate_b5": {
        "R": 28, "F": 10, "D": 6, "T": 8, "A": 10,
        "N": 12, "E": 5,
    },
    "gate_b6": {
        "R": 28, "F": 10, "D": 6, "T": 8, "A": 10,
        "N": 12, "E": 5,
    },
    "final": {
        "R": 28, "F": 10, "D": 6, "T": 8, "A": 11,
        "N": 13, "E": 5,
        "C": 7, "X": 8, "G": 0,  # G is optional, don't gate on it
    },
}


def get_scenarios_for_gate(gate_name: str) -> List[Scenario]:
    """Return the scenario list for a named gate."""
    if gate_name not in SUBSETS:
        raise ValueError(
            f"Unknown gate: {gate_name}. Valid: {list(SUBSETS.keys())}"
        )
    return SUBSETS[gate_name]


def get_thresholds_for_gate(gate_name: str) -> Dict[str, int]:
    """Return the per-category PASS thresholds for a gate."""
    if gate_name not in GATE_THRESHOLDS:
        return {}
    return GATE_THRESHOLDS[gate_name]


if __name__ == "__main__":
    # Quick sanity check when run directly
    import sys
    print(f"Total scenarios: {len(ALL_SCENARIOS)}")
    print(f"Categories:")
    for cat, scenarios in [
        ("R", R_SCENARIOS), ("F", F_SCENARIOS), ("D", D_SCENARIOS),
        ("T", T_SCENARIOS), ("A", A_SCENARIOS), ("N", N_SCENARIOS),
        ("E", E_SCENARIOS), ("C", C_SCENARIOS), ("X", X_SCENARIOS),
        ("G", G_SCENARIOS),
    ]:
        print(f"  {cat}: {len(scenarios):3d}")
    print()
    print(f"Gate subsets:")
    for name, scenarios in SUBSETS.items():
        print(f"  {name:10s}: {len(scenarios):3d} scenarios")

    # Verify SID uniqueness
    sids = [s[0] for s in ALL_SCENARIOS]
    if len(sids) != len(set(sids)):
        duplicates = [sid for sid in sids if sids.count(sid) > 1]
        print(f"❌ DUPLICATE SIDS: {set(duplicates)}")
        sys.exit(1)
    print("✅ All SIDs unique")
