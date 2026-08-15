# Troubleshooting index

One-line index of every known anti-pattern. Each entry points at a file
in this directory with full context (WRONG, RIGHT, WHY).

**How to read**: before starting any complex engineering task, scan this
index for categories that match your task (terminal capture, docker
recreate, feature gating, etc.). Open the specific entries and apply.

**How to add**: when a session produces a new failure mode, create a file
`YYYYMMDD-slug.md` with full context and add one line here.

---

## 2026-04-12 — coding-cli comprehensive test session

- [2026-04-12-arbitrary-terminal-line-limits.md](2026-04-12-arbitrary-terminal-line-limits.md) — Never use `capture(lines=N)` for full-terminal reads; use `start_recording`/`stop_recording` for absolute-scrollback accumulation
- [2026-04-12-fidelity-shortcut-hunting.md](2026-04-12-fidelity-shortcut-hunting.md) — When user says "100% fidelity", don't substitute tmux/expect/small window/slow polling
- [2026-04-12-stale-wakeup-pids.md](2026-04-12-stale-wakeup-pids.md) — Wakeup prompts contain stale pids; always `pgrep -f <runner>` first
- [2026-04-12-llm-judges-dont-work-here.md](2026-04-12-llm-judges-dont-work-here.md) — kimi/glm/deepseek-chat all fail as judges for NeoMind tests; Claude reads dumps directly
- [2026-04-12-feature-gate-single-fix-site.md](2026-04-12-feature-gate-single-fix-site.md) — auto_search hijack existed in 4 separate code paths; grep for ALL call sites before declaring fixed
- [2026-04-12-trusting-fixer-reports.md](2026-04-12-trusting-fixer-reports.md) — Verify fixer edits via grep/Read BEFORE running the test
- [2026-04-12-api-key-leak-in-bash-output.md](2026-04-12-api-key-leak-in-bash-output.md) — Never print env secrets or unredacted HTTP logs; URLs (notably Telegram Bot API paths) can embed full credentials
- [2026-04-12-docker-recreate-without-env-check.md](2026-04-12-docker-recreate-without-env-check.md) — Before docker recreate, diff live container env vs disk .env to prevent production breakage
- [2026-04-12-iterm2-batch-close.md](2026-04-12-iterm2-batch-close.md) — Never iterate `app.windows` and call `async_close`; killed Claude Code's own session
- [2026-04-12-iteration-spiral.md](2026-04-12-iteration-spiral.md) — After 3 failed fix attempts, dispatch a diagnostic agent (not another fix); stop patch-spraying
- [2026-04-12-subagent-prompt-sizing.md](2026-04-12-subagent-prompt-sizing.md) — Fixer prompts must be self-contained, surgical, <200 word report target
- [2026-04-12-cross-mode-smoke-skipped.md](2026-04-12-cross-mode-smoke-skipped.md) — Changes to shared paths require cross-mode boot smoke (automated via pre-commit hook)

## 2026-04-19 — fin dashboard fusion session

- [2026-04-19-headless-browser-memory-leak.md](2026-04-19-headless-browser-memory-leak.md) — Always `trap`/`finally` to kill spawned Chrome + rm user-data-dir; check `memory_pressure` before spawning; one background poll at a time
- [2026-04-19-openbb-workspace-schema-gotchas.md](2026-04-19-openbb-workspace-schema-gotchas.md) — apps.json is an ARRAY; agents.json endpoints.query is RELATIVE; SSE must emit `event: copilotMessageChunk` + `{"delta": …}` — Workspace drops anything else silently
- [2026-04-19-launchd-service-stale-env-snapshot.md](2026-04-19-launchd-service-stale-env-snapshot.md) — Long-running services bake env at start; fixing .zshrc/config doesn't help. Always `ps eww <pid>` the running process, not just your shell.

## 2026-04-23 — Insight Lattice pan/zoom black-screen session

- [2026-04-23-ui-bug-ship-without-browser-test.md](2026-04-23-ui-bug-ship-without-browser-test.md) — After 3 failed iterative fixes for a UI bug, STOP editing and write a Playwright repro first. State dump + screenshot surfaces the real fault model; code reasoning alone doesn't.
- [2026-04-23-svg-viewbox-transform-voodoo.md](2026-04-23-svg-viewbox-transform-voodoo.md) — For pan/zoom, CSS transform on a wrapper `<div>` beats SVG `viewBox` + inner `<g transform>` + `getScreenCTM()`; stays in CSS pixels, no letterbox math.
- [2026-04-23-pan-clamp-on-canvas-not-content.md](2026-04-23-pan-clamp-on-canvas-not-content.md) — Pan clamp on canvas extent lets the viewport park on empty gaps between structured nodes ("black screen" despite math being correct). Compute a tight node bbox during layout and clamp on that.
- [2026-04-23-drag-listener-useeffect-race.md](2026-04-23-drag-listener-useeffect-race.md) — Don't attach document mousemove/mouseup via useEffect keyed on isPanning. The mousedown→useEffect commit gap (1–16ms) drops mouseup; next mousemove pans from stale state. Attach listeners synchronously in mousedown; teardown via ref.
- [2026-04-23-validate-then-ship-llm-pattern.md](2026-04-23-validate-then-ship-llm-pattern.md) — LLM output MUST pass a deterministic validator before anything downstream reads it. Never `reply["field"]` raw. Drop with a bounded drop_reason; fall back to deterministic output. Unlocks cheap self-check over stored output.

## 2026-04-24 — Research-tab cleanup (lattice as single focus)

- [2026-04-24-dashboard-features-that-compete-with-public-products.md](2026-04-24-dashboard-features-that-compete-with-public-products.md) — A tile that exists because "every dashboard has one" (chart / quote / heatmap / earnings calendar) competes with TradingView/Yahoo/Finviz/雪球 on their home turf and loses. Make L0 a backend tagging+snapshot pipeline (no viewing UI) and link out from each L0 node. Legacy via `?legacy=1` for reversibility.
- [2026-04-24-useeffect-ref-race-with-early-returns.md](2026-04-24-useeffect-ref-race-with-early-returns.md) — `useEffect(() => { ref.current... }, [])` never fires if the ref-bearing div lives past an early-return (loading/error skeleton). First render returns the skeleton → ref never attached → effect reads null → `[]` deps prevent re-run. Mirror the node into state via a callback ref and put that state in the dep array.

## 2026-04-24 — DeepSeek v4 migration session

- [2026-04-24-router-auto-discover-strips-deprecated-names.md](2026-04-24-router-auto-discover-strips-deprecated-names.md) — Vendor `/v1/models` drops deprecated id → router auto_discover strips it from valid set → 404 even though the direct vendor API still aliases it. Always test through the router; add a migration map for persisted refs.
- [2026-04-24-personality-model-override.md](2026-04-24-personality-model-override.md) — Per-personality `routing.primary_model:` defeats router's single-source-of-truth. Personality should own prompt + tools, NOT model selection. One `provider-state.json :: direct_model` rules them all.
- [2026-04-24-vendor-context-window-decimal-not-binary.md](2026-04-24-vendor-context-window-decimal-not-binary.md) — Vendor docs say "1M / 384K" — that's decimal (1,000,000 / 384,000), not 2^20 / 384×1024. Wrong-by-default: matches binary, overshoots actual API cap by ~5%.

## 2026-04-25 — Anti-hallucination tuning session

- [2026-04-25-tool-use-detector-blind-to-toolresult-messages.md](2026-04-25-tool-use-detector-blind-to-toolresult-messages.md) — Reply-text-only "did the agent call a tool?" detector misses `finance_get_stock` etc. because their results are persisted as `role=user <tool_result>` messages in chat_history.db, NOT prefixed with `✅ **ToolName**` in the visible reply. Wasted 6 rounds of prompt engineering on a non-existent "model-level hallucination" before realizing the bot was always calling the tool correctly. Detect tool use from chat_history.db, not reply formatting.

## 2026-04-27 — Strategies catalog hallucination audit

- [2026-04-27-strategies-yaml-hallucination.md](2026-04-27-strategies-yaml-hallucination.md) — Phase 3 research subagent fabricated 108 source URLs across 36 strategies in `docs/strategies/strategies.yaml`. Plausible but ungrounded. Free-text fields (typical_win_rate, max_loss, key_risks) generated by same subagent equally suspect. Fix: 4-layer guardrail (provenance schema → anti-hallucination skill → compute filter → UI ⚠ chip) + Layer 0 auditor that runs LLM as extractor over RawStore bytes with mechanical post-validation (cited phrase must exist literally). Never ask an LLM to generate fact-heavy structured data; only let it extract from real bytes.

## 2026-06-02 — Fin Harness Evolution Loop (Phase 1)

- [2026-06-02-tool-dispatch-crashes-on-hallucinated-kwargs.md](2026-06-02-tool-dispatch-crashes-on-hallucinated-kwargs.md) — `dispatch()` did `fn(**args)` unguarded; LLM hallucinated `get_recent_signals(ticker=)` → uncaught TypeError killed the whole turn. Any `fn(**llm_args)` boundary must filter unknown kwargs + catch TypeError → return `{"error":...}` so the agent loop self-corrects. LLMs passing wrong args is the expected case, not an edge case.
- [2026-06-02-reward-verifier-false-positives.md](2026-06-02-reward-verifier-false-positives.md) — Reward floored at 0.2 from validator "Rule 3" — but the verifier was reading "$40" out of "$40T"/"$150B"/"$100k-$250k" (TAM/spend/disclosure ranges) and ignored the agent's `[ev:]`/`[fact:]` citations. The agent was right; the reward function lied. Validate the verifier before letting reward drive a self-improvement loop, or it optimizes toward the metric's bugs.
- [2026-06-03-eval-noise-exceeds-effect.md](2026-06-03-eval-noise-exceeds-effect.md) — Reward-delta gate gave opposite verdicts on the same change across runs; the baseline alone swung +0.05→−0.125. At n=2 over a bimodal reward, noise ≫ effect → the gate decides on noise. Measure a metric's noise floor + use temp=0 / paired / more samples before letting it gate self-modification. Mechanical correctness of a change ≠ measured improvement.

## 2026-06-21 — Fin coverage engine: SEC 10-K extraction starvation

- [2026-06-21-sec-edgar-ixbrl-soup-buries-item1.md](2026-06-21-sec-edgar-ixbrl-soup-buries-item1.md) — Modern iXBRL 10-Ks: `<ix:header>`/`<ix:resources>` soup (~60K) buries Item 1 past the slice window; and "Table of Contents**ITEM 1A**" page-header glue breaks `\bitem` anchors → extractor fed garbage/empty, emits 0 **silently**. Fix: decompose `ix:` metadata + drop leading `\b` + `_body_anchors()` TOC filter. Verified AMD/META/NVDA/GOOGL/AAPL no-regression (AMD 0→10 competitors). Assert extractor INPUT is non-trivial, not just "no exception".

## 2026-07-12 — fin 解耦 open-core

- [20260712-verify-surfaces-and-venvs.md](20260712-verify-surfaces-and-venvs.md) — 交付只有 curl+import=假完成；烟测在 fin_venv 全 SKIP 差点当证据（SKIP≠PASS，boot 烟测必须 .venv）；editable 包只装一个 venv → fin_provider 静默回退。完成前三表面真验：8001 重启+browser 真点 / 容器重启+Telethon 真收 / CLI 真 boot。
- [20260712-reverse-deps-before-delete.md](20260712-reverse-deps-before-delete.md) — 按"内容重复"删 8 个 untracked 模块断了 tracked 代码；删前必 git grep 反向依赖；审计禁止按首 hit 定性整文件；批量改写后全仓残留扫描清零；高风险删除先备份。

## 2026-08-07 — Phase 0 收尾：日志泄露 + 误导性 readiness

- [20260807-dependency-logs-leak-secrets.md](20260807-dependency-logs-leak-secrets.md) — `httpx` INFO 打完整 URL + Telegram token 在 URL path 里 → agent.log 24.8 万行明文（NeoMind 自己一行没记过，查自家代码永远查不到）。修复=降级 httpx + filter 挂 **handler**（挂 logger 对 propagate 的 record 无效）+ 改 msg 必须清 `record.args`。`PIISanitizer.PATTERNS` **顺序敏感**：`ssn` 会吃掉 token 数字段留下后半段。扫描两个假阴性：`grep -I` 跳过 CJK 文件、**docker 命名卷不在 host 路径下**（先 inspect 挂载表）。
- [20260809-suite-never-finished.md](20260809-suite-never-finished.md) — 「偶发 FD 告警」实为**整套测试从来没跑完过**：54% 处 mock 了 `get` 而代码调 `get_nowait` → `_drain_queue` 的 `while True` 100% CPU 空转（已修，40/40 通过）；71% 处 asyncio 无限等待（未修 debt）。追挂死必须用 `-v`（`-q` 问不出名字）+ **同时看 CPU**（高=死循环 / 近 0=阻塞，修法完全不同）；`sample` 免 root，py-spy 要 root；**别用进度百分比反推序号**（本次推错）。顺带：115 个泄漏的 heartbeat 线程。
- [20260807-health-ok-while-everything-401.md](20260807-health-ok-while-everything-401.md) — Router `/health` 报 ok 且列 10 个模型，而所有云模型 401 五天：poller 吞掉发现失败并"keeping prior list"。修 readiness 前先查**谁在消费它**——`repair.sh` 用 `curl -sf /health` 决定重启，让 /health 失败会打成重启循环。正解=/health 保持 200 但 body 说 degraded + 独立 /ready 返回 503。且必须用真坏 key 起第二实例验证 degraded 分支真会触发。

## 2026-08-13 — 套件挂死点 2 定位 + 收口

- [20260813-stopiteration-into-future-hangs-forever.md](20260813-stopiteration-into-future-hangs-forever.md) — 定位到 20260809 遗留的挂死点 2（**在 28% 不是 71%**，百分比随 collection 变，别当路标）：`mock_fetch.side_effect` 只给 3 个而代码 `[:limit*2]` 调 5 次 → 用尽后抛 `StopIteration` → `TypeError: StopIteration interacts badly with generators and cannot be raised into a Future` 在 callback 里被吞 → future 永久 pending，`gather` 无限等。**`sample` 里的 `_queue` 叶子是无辜的空闲 worker，会把人追歪**，要 faulthandler 拿主线程 Python 栈。修法=定长 side_effect 改按 id 查表的 callable + 断言 call_count。系统防线=`timeout=300 / timeout_method=signal`（`thread` 会杀整个进程，达不到「只坏一个测试」）。顺带：3 个 collection error 清零（**62 个测试从来没被收集过**，`--continue-on-collection-errors` 让它静默）；心跳线程泄漏 115→0，且**第一版修复的 `if not self._running: return` 守卫自己就是新洞**——守卫要挂线程不挂标志位。

## 2026-08-15 — 推理模型的 max_tokens 是「推理+答案」合并预算

- [20260815-reasoning-model-max-tokens-starves-the-answer.md](20260815-reasoning-model-max-tokens-starves-the-answer.md) — lattice 叙事永远是英文的真因：`DEFAULT_MODEL`(deepseek-v4-flash) 是**推理模型**，reasoning tokens **计入 max_tokens**，而 200 是照「答案 50-80 token」定的 → 推理先把额度吃光，答案根本没开始 → `finish_reason=length` → `json.loads` 报 `Unterminated string ... (char 14)` → 被宽 except 兜住**静默回落英文模板**（生产里零告警，只有一个断言中文的测试抓到）。实测同 prompt 6 采样：**200 下 5/6 截断**（完全间歇，手动重试一次会"证明"代码没问题）；800 下 6/6 完整、reasoning 峰值 **408**（拍脑袋选 500 就正好卡在悬崖边）。**别从解析错误反推截断**——直接问 API：`finish_reason=="length"` + `usage.completion_tokens_details.reasoning_tokens ≈ max_tokens` 就是签名，且必须采样 5-6 次，单次调用说明不了间歇性上限。调用点一旦指向推理模型，max_tokens 要按实测 reasoning 峰值定，且有 fallback 分支时日志必须响到截断无法伪装成正常结果。
