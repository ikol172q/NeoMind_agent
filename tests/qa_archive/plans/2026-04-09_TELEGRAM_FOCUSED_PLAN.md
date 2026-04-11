# Telegram-Focused Test Plan
**Date:** 2026-04-09
**Driver:** Telethon (real Telegram client, not tmux)
**Why:** User uses NeoMind primarily through @neomindagent_bot for finance/research, NOT for coding inside Telegram. Coding is done in CLI / VS Code. This plan deliberately excludes scenarios that the user never actually runs in Telegram.

## What We Test (200 scenarios)

| Category | Count | Why |
|---|---|---|
| F. Finance commands | 50 | Primary use case |
| Q. Long Chinese Q&A | 30 | User's main interaction style |
| S. Search reliability | 35 | Quality of answers depends on it |
| M. Model + mode switching | 25 | Verify router refactor end-to-end |
| L. Long sessions (50-200 turns) | 15 | Auto-compact, recall, drift |
| U. UX details | 15 | Telegram-specific rendering |
| E. Error recovery | 15 | Real-world flake handling |
| K. Real-time data freshness | 15 | Stocks, news, today's data |

## What We Skip

- Coding tools in Telegram (`/run`, `/grep`, `/find`, file Edit) — user uses these in CLI
- Self-edit / evolution (covered by separate self-evolution test plan)
- Multi-file Edit operations
- Tmux real-keyboard scenarios (already covered for CLI)

---

## Category F — Finance Commands (50)

### F1 — `/stock` (15)
| ID | Input | Expectation |
|---|---|---|
| F101 | `/stock AAPL` | Latest price, market cap, day change |
| F102 | `/stock NVDA` | Same fields |
| F103 | `/stock TSLA` | Same fields |
| F104 | `/stock 700.HK` | Hong Kong stock format |
| F105 | `/stock 600519.SS` | China A-share format |
| F106 | `/stock NONEXISTENT_TICKER` | Graceful error |
| F107 | `/stock` (no arg) | Usage hint |
| F108 | `/stock AAPL fundamentals` | PE, P/B, EPS |
| F109 | `/stock NVDA news` | Latest headlines for ticker |
| F110 | `/stock SPY` | ETF works as ticker |
| F111 | `/stock BTC-USD` | Crypto via stock route |
| F112 | `/stock AAPL` then `/stock` (recall last) | Re-fetches AAPL |
| F113 | `/stock aapl` (lowercase) | Auto-uppercase |
| F114 | Two `/stock AAPL` in 5 sec | Cache or refetch (verify behavior) |
| F115 | `/stock GOOG` after `/mode chat` then `/mode fin` | Mode switch preserves command access |

### F2 — `/crypto` (10)
| ID | Input | Expectation |
|---|---|---|
| F201 | `/crypto BTC` | Price USD, 24h change, market cap |
| F202 | `/crypto ETH` | Same |
| F203 | `/crypto SOL` | Same |
| F204 | `/crypto DOGE` | Same |
| F205 | `/crypto NONEXISTENT_COIN` | Graceful error |
| F206 | `/crypto BTC ETH SOL` (multi) | Either supports or rejects cleanly |
| F207 | `/crypto btc` (lowercase) | Auto-normalize |
| F208 | `/crypto BTC` then "what's the trend?" | LLM uses last fetched data |
| F209 | `/crypto BTC` immediately after `/stock BTC-USD` | Both work, no state collision |
| F210 | `/crypto` (no arg) | Usage hint |

### F3 — `/news` (10)
| ID | Input | Expectation |
|---|---|---|
| F301 | `/news Fed rate` | Recent headlines, with sources |
| F302 | `/news AAPL` | Apple-specific news |
| F303 | `/news 中国 经济` | Chinese-language news works |
| F304 | `/news` (empty) | Top general finance news |
| F305 | `/news AI semiconductor` | Multi-word query |
| F306 | `/news bitcoin halving` | Crypto news |
| F307 | After `/news Fed rate`, ask "what's the most important one?" | LLM picks from prior result |
| F308 | `/news 关税` (tariffs) | Chinese topic |
| F309 | `/news` two times rapidly | Both succeed or rate-limit cleanly |
| F310 | `/news <very long query>` | Truncates or accepts |

### F4 — `/quant`, `/portfolio`, `/market`, `/digest` (15)
| ID | Input | Expectation |
|---|---|---|
| F401 | `/quant CAGR 100 200 5` | 14.87% |
| F402 | `/quant ROI 1000 1500` | 50% |
| F403 | `/quant SHARPE 0.12 0.20 0.04` | 0.4 |
| F404 | `/quant compound 10000 0.08 10` | 21589.25 |
| F405 | `/quant DCF AAPL` | DCF calculation (may be approximate) |
| F406 | `/portfolio` (empty) | "no holdings yet" or empty list |
| F407 | `/portfolio add AAPL 100 150` | Adds to portfolio |
| F408 | `/portfolio` after add | Shows AAPL position |
| F409 | `/portfolio remove AAPL` | Removes |
| F410 | `/market` | S&P, Nasdaq, Dow, VIX summary |
| F411 | `/market` followed by `/news 大盘` | Both work in sequence |
| F412 | `/digest` | Daily digest format |
| F413 | `/digest` after `/digest` (cached?) | Same content or refresh |
| F414 | `/watchlist add NVDA AAPL TSLA` | Multi-ticker add |
| F415 | `/watchlist` | Lists all 3 |

---

## Category Q — Long Chinese Q&A (30)

These mirror real user behavior: ask a question, get an answer, drill deeper, switch topic, recall earlier.

### Q1 — Knowledge questions (no real-time data) (10)
| ID | Input |
|---|---|
| Q101 | 什么是市盈率？用最简单的话解释 |
| Q102 | 什么是夏普比率？给个公式 |
| Q103 | 解释一下"美林时钟" |
| Q104 | 巴菲特的护城河理论是什么？ |
| Q105 | 什么是 DCA（定投）？跟一次性投入哪个更好？ |
| Q106 | 解释期权的 delta gamma theta vega |
| Q107 | 什么是流动性陷阱？ |
| Q108 | 什么是 Reverse Repo？美联储为什么用它？ |
| Q109 | 解释一下"美元微笑理论" |
| Q110 | 什么叫做 risk parity 策略？ |

### Q2 — Real-time + analysis (10)
| ID | Input |
|---|---|
| Q201 | 今天美股大盘怎么样？ |
| Q202 | NVDA 最近一周的走势如何？驱动因素是什么？ |
| Q203 | 美联储下次会议大概率会做什么？ |
| Q204 | 现在 30 年期美债收益率是多少？ |
| Q205 | 黄金价格今天多少？为什么涨/跌？ |
| Q206 | 油价最近怎么样？有什么催化剂？ |
| Q207 | 美元指数当前水平？影响因素？ |
| Q208 | 比特币这周表现如何？跟纳斯达克的相关性？ |
| Q209 | 中概股最近怎么样？ |
| Q210 | 半导体板块的最新动态？ |

### Q3 — Multi-turn drill-down (10)
Each is a 3-5 message thread with reference to previous answer.
| ID | Sequence |
|---|---|
| Q301 | (1) "推荐一个稳健的投资策略" → (2) "里面提到的债券具体怎么配置？" → (3) "用 ETF 实现要选哪些代码？" |
| Q302 | (1) "美国 AI 行业现在的格局" → (2) "里面哪几家最值得关注？" → (3) "选一家详细分析它的护城河" |
| Q303 | (1) "什么是 carry trade？" → (2) "现在哪些货币对适合？" → (3) "风险点在哪里？" |
| Q304 | (1) "解释一下为什么美债收益率涨股票就跌" → (2) "那如果反过来呢？" → (3) "现在我们处于哪个阶段？" |
| Q305 | (1) "中国新能源车产业链" → (2) "上游谁最强" → (3) "估值合理吗" |
| Q306 | (1) "我手上有 5 万美元想分散投资" → (2) "中美各占多少？" → (3) "具体到 ETF 名称" |
| Q307 | (1) "欧洲央行最近降息了吗" → (2) "对欧元什么影响" → (3) "对持有美元的我有什么影响" |
| Q308 | (1) "什么是 quality factor 投资" → (2) "怎么筛选 quality 股票" → (3) "举几个 A 股例子" |
| Q309 | (1) "现在 VIX 是多少" → (2) "历史均值在哪里" → (3) "高于均值意味什么" |
| Q310 | (1) "黄金为什么近几个月涨这么多" → (2) "央行购金影响多大" → (3) "现在追高安全吗" |

---

## Category S — Search reliability (35)

Test that search **respects** user intent:
- Doesn't search when user says "no search"
- Searches when query needs real-time data
- Returns sources, not just text

### S1 — Auto-search opt-out (10)
| ID | Input | Expected: search triggered? |
|---|---|---|
| S101 | "什么是 PE ratio? 不要搜索, 直接告诉我" | NO |
| S102 | "Define beta in finance, no web search please" | NO |
| S103 | "纯知识题: 什么是夏普比率" | NO |
| S104 | "Just from your knowledge: explain CAPM" | NO |
| S105 | "回答前不要搜索. 什么是 DCF?" | NO |
| S106 | "什么是 ETF" (no opt-out marker) | YES (current behavior) |
| S107 | "今天 AAPL 收盘价" (real-time) | YES |
| S108 | "1+1 等于几" | NO |
| S109 | "Without searching: name three Buffett quotes" | NO |
| S110 | "请直接回答 (no search)：什么是利率倒挂" | NO |

### S2 — Search quality (10)
| ID | Input | Verify |
|---|---|---|
| S201 | "今天 NVDA 收盘价" | A specific number, not "I don't have real-time data" |
| S202 | "今天 SPY 涨跌" | Specific % |
| S203 | "美联储最新一次会议结果" | Date-specific |
| S204 | "比特币当前价格" | USD price |
| S205 | "今天美元/人民币汇率" | Specific number |
| S206 | "AAPL 最近的财报" | Quarter, EPS, revenue |
| S207 | "今天 10Y 美债收益率" | % value |
| S208 | "TSLA 今天的成交量" | Numeric |
| S209 | "今天纳斯达克涨跌" | % change |
| S210 | "今天黄金价格" | USD/oz |

### S3 — Source citations (10)
| ID | Expected |
|---|---|
| S301 | After Q201, response should include source URLs or "据 ... 报道" |
| S302 | News-driven answer should not be hallucinated; cross-check at least one cited URL |
| S303 | Chinese sources used for Chinese queries (gnews_zh, ddg_zh) |
| S304 | Multiple sources combined, not single-source dependency |
| S305 | "search again with different terms" should re-run search |
| S306 | If 0 results, bot says so explicitly, doesn't fabricate |
| S307 | A blocked domain (e.g. unreachable site) doesn't break entire response |
| S308 | LLM-decided search query is different language than user input → search both languages |
| S309 | Recent (this week) results preferred over old (1 year ago) when both relevant |
| S310 | Bot doesn't say "as of my training data" — it has live search |

### S4 — Search edge cases (5)
| ID | Input |
|---|---|
| S401 | Empty search-triggering query: "今天" (just "today") |
| S402 | Query with special chars: "AAPL & MSFT comparison" |
| S403 | Query mixing 5 languages |
| S404 | Query that triggers 0 results |
| S405 | Query that triggers 500+ results |

---

## Category M — Model + Mode switching (25)

### M1 — `/model` switching (15)
For each: switch model → ask same question → verify response indicates that model is in use (or check `/status`).

| ID | Input |
|---|---|
| M101 | `/model deepseek-chat` then "hi" |
| M102 | `/model deepseek-reasoner` then "hi" (should show longer thinking) |
| M103 | `/model glm-5` then "hi" |
| M104 | `/model glm-4.7` then "hi" |
| M105 | `/model glm-4.7-flash` then "hi" |
| M106 | `/model glm-4.7-flashx` then "hi" |
| M107 | `/model kimi-k2.5` then "hi" |
| M108 | `/model qwen3:14b` (Ollama local) then "hi" |
| M109 | `/model gemma4:e4b` (Ollama small) then "hi" |
| M110 | `/model gemma4:31b` then "hi" |
| M111 | `/model gemma4:26b` then "hi" |
| M112 | `/model nonexistent-model` (error handling) |
| M113 | `/model` (no arg → list current + available) |
| M114 | `/model reset` (back to mode default) |
| M115 | Switch model → `/status` (verify model in status) |

### M2 — Cross-mode behavior (10)
| ID | Input |
|---|---|
| M201 | `/mode chat` then `/mode coding` then `/mode fin` (round trip) |
| M202 | Set fact in fin mode → switch to chat → ask same fact (should remember) |
| M203 | `/model kimi-k2.5` in fin → switch to chat → check model still kimi or reset to chat default |
| M204 | `/mode fin` → "什么是ETF" → `/mode chat` → "what's that?" (does it remember ETF context?) |
| M205 | Send 5 msgs in coding → `/mode fin` → "what was my first message?" |
| M206 | `/mode chat` → use a chat-only command (e.g., `/draft`) → check it works |
| M207 | `/mode fin` → use a fin-only command (e.g., `/stock`) → check it works |
| M208 | `/mode coding` → use a coding-only command (e.g., `/grep`) → check rejected or warning |
| M209 | Multiple chats in different modes simultaneously (per-chat mode tracking) |
| M210 | `/mode` (no arg) → show current |

---

## Category L — Long sessions (15)

Each is a single conversation thread. The Telethon driver runs all turns sequentially, captures every reply, then verifies a final assertion.

| ID | Length | Topic | Final assertion |
|---|---|---|---|
| L101 | 50 turns | Iterative AAPL deep-dive | At turn 50, can recall a fact set at turn 5 |
| L102 | 75 turns | Crypto market analysis loop | Auto-compact triggered at least once, fact survives |
| L103 | 100 turns | Multi-stock comparative analysis (5 stocks) | Bot still responsive, no degradation |
| L104 | 50 turns | Mixed Chinese + English questions | No language drift |
| L105 | 50 turns | All `/news` queries | Each query returns fresh, no duplicate articles |
| L106 | 50 turns | Drill-down from "what is value investing" → 50 levels of "tell me more" | Doesn't loop, doesn't repeat same content |
| L107 | 100 turns | Multi-topic: 10 unrelated finance topics × 10 messages each | Topic boundaries respected, no cross-contamination |
| L108 | 75 turns | Sustained `/quant` calls with varying inputs | All math correct |
| L109 | 50 turns | All in fin mode, mid-session `/model kimi-k2.5` switch | Style change observable post-switch |
| L110 | 200 turns | Endurance: mix of all command types | Bot survives, no crash, response quality stable |
| L111 | 50 turns | Each turn includes `/checkpoint` → eventually `/rewind` to first | Rewind works after long history |
| L112 | 50 turns | All in same chat thread, `/clear` mid-session | Pre-clear context gone, post-clear works |
| L113 | 50 turns | Sustained search-heavy queries | No rate limit hit, all return results |
| L114 | 50 turns | Reply to bot's questions (bot proactively asking back) | Multi-step Q&A flow |
| L115 | 100 turns | Real "research session": ask, refine, dig, summarize | Final summary covers content from turns 1-100 |

---

## Category U — UX details (15)

| ID | Test |
|---|---|
| U101 | Long response (>4096 chars) gets split into multiple Telegram messages |
| U102 | Markdown formatting (bold, code, lists) renders correctly |
| U103 | Code block in response renders with monospace |
| U104 | URLs in response are clickable |
| U105 | Reply contains emoji that displays correctly |
| U106 | Bot reaction (✅ ❌) on user message works |
| U107 | "typing..." indicator shows while bot is thinking |
| U108 | Bot edits message to show streaming progress (vs sending many small messages) |
| U109 | Reply to a specific message in a group works |
| U110 | Bot sends image/chart if appropriate (e.g., `/stock NVDA` with chart) |
| U111 | Response stays within Telegram's per-message 4096 char limit |
| U112 | Chinese characters in code blocks render correctly |
| U113 | Math/LaTeX rendering (if supported) |
| U114 | Tables render readably (Telegram has no table markup, so use ASCII or code block) |
| U115 | Bot responds within 60s for any query (timeout sanity) |

---

## Category E — Error recovery (15)

| ID | Test |
|---|---|
| E101 | Bot down → user sends message → bot back up → message processed (or queued) |
| E102 | LLM API timeout → user gets clear error, not silent fail |
| E103 | Router unreachable → user gets clear error |
| E104 | Search source down → degraded results, not error |
| E105 | Tool execution error → handled gracefully |
| E106 | Send `/stock AAPL` to bot at the moment of process restart → either processed or clear timeout |
| E107 | Send 10 messages in 5 seconds → all processed or rate-limited cleanly |
| E108 | Send extremely long message (10K chars) → truncated or rejected, not crash |
| E109 | Send empty message → ignored |
| E110 | Send only emoji → handled |
| E111 | Send a sticker → handled or ignored cleanly |
| E112 | Send a voice message → not supported but graceful |
| E113 | Send an image → not supported but graceful |
| E114 | Send a forwarded message from another chat → handled |
| E115 | Bot's own message is replied-to by user → context preserved |

---

## Category K — Real-time data freshness (15)

These are time-sensitive. Each test sends a query about TODAY's data and checks the response includes a date/timestamp from within the last 24 hours.

| ID | Query | Verify |
|---|---|---|
| K101 | "今天 SPY 收盘价" | Number + today's date |
| K102 | "今天 AAPL 涨跌幅" | % + today |
| K103 | "今天美元指数" | Number + today |
| K104 | "美联储最近一次会议结果" | Date within last 60 days |
| K105 | "上周非农数据" | Date within last 14 days |
| K106 | "今天最大新闻" | At least one news item dated today |
| K107 | "本周科技股表现" | This week's data |
| K108 | "今天油价" | Today's price |
| K109 | "今天黄金价格" | Today's price |
| K110 | "今天 BTC 价格" | Today's price |
| K111 | "今天美股开盘了吗" | Aware of US market hours + holidays |
| K112 | "本周经济日历有什么重要数据" | Week-specific events |
| K113 | "今天恒生指数" | Today's HSI |
| K114 | "今天 A 股大盘" | Today's CSI300 / SSE |
| K115 | "今天日经指数" | Today's Nikkei |

---

## Driver

All tests use `/tmp/neomind_telegram_tester.py` (Telethon-based). Add a new plan:

```python
TELEGRAM_FOCUSED_PLAN = [
    # F1 stocks
    {"send": "/stock AAPL", "wait": 30, "expect_any": ["AAPL", "Apple", "$"]},
    ...
]
```

## Pass criteria

| Tier | Pass if |
|---|---|
| Per-test | Reply received within timeout AND `expect_any` substring matches AND no error pattern (`PARSE FAILED`, `Traceback`, `parser returned None`) in raw capture |
| Per-category | ≥85% pass rate AND no P0 bugs |
| Overall | ≥85% pass rate AND all P0 bugs fixed before merging |

## Estimated runtime

| Category | Wall time |
|---|---|
| F (50) | ~25 min |
| Q (30) | ~20 min |
| S (35) | ~25 min |
| M (25) | ~15 min |
| L (15 × 50-200 turns) | ~3-4 hours |
| U (15) | ~10 min |
| E (15) | ~15 min |
| K (15) | ~10 min |
| **Total** | **~5-6 hours** |

LLM rate limit: 8s between calls per the existing tester convention. Most categories serial; L can run one session per LLM key per hour.
