# NeoMind Agent — Changelog & Fix Tracker

## Version 0.5.0 — 2026-03-29 (Integration Wiring)

### Overview

将 Phase 5-7 全部研究增强模块接入主循环。创建 `integration_hooks.py` 统一接入层，
在 4 个关键位置各加一个 hook 调用，实现全链路贯通。新增 5 个端到端集成测试场景。

### New Files

| # | File | Lines | Description |
|---|------|-------|-------------|
| I-024 | `agent/evolution/integration_hooks.py` | ~380 | 4 hooks: pre_llm_call, post_response, periodic_tasks, self_edit_gate |
| I-025 | `tests/test_integration_scenarios.py` | ~500 | 5 个真实场景集成测试 |

### Wiring Points (4 处接入)

| Location | Hook | Effect |
|----------|------|--------|
| `code_commands.py` payload 前 | `pre_llm_call()` | Degradation 降级 + Distillation 注入 + Token 限制 |
| `code_commands.py` history 后 | `post_response()` | Drift 记录 + 恢复 + Exemplar 存储 |
| `scheduler.py` 每 50 轮 | `periodic_tasks()` | PSI 检测 + KG 聚类 + Cleanup |
| `self_edit.py` Guard 6.6 | `self_edit_gate()` | AgentSpec + Debate 共识 |

### Test Results: 5/5 PASS

---

## Version 0.4.1 — 2026-03-29 (Phase 7 Selected Items)

### Overview

实现 v4.0 计划中 Phase 7 精选的 2 项高 ROI 任务：A-Mem Zettelkasten 知识图谱和模型蒸馏 fallback chain。
修复了两个模块的 `:memory:` 数据库兼容性问题和 standalone 运行时的 foreign key 依赖。

### New Files Created

| # | File | Lines | Description |
|---|------|-------|-------------|
| I-022 | `agent/evolution/knowledge_graph.py` | ~350 | A-Mem Zettelkasten 知识图谱 (8种边类型, BFS关联检索, 连通分量聚类) |
| I-023 | `agent/evolution/distillation.py` | ~400 | 模型蒸馏 fallback chain (7种任务类型, exemplar存储, 成本节约追踪) |

### Key Features

- **Knowledge Graph (7.1)**: 记忆从「能记住」到「能联想」的跃迁
  - 8 种语义边类型: causes, supports, contradicts, extends, similar_to 等
  - BFS 加权关联检索 + 最短路径发现
  - 连通分量聚类发现 (emergent themes)
  - LLM 连接建议 prompt 生成

- **Model Distillation (7.4)**: 直接影响运营成本的智能降级
  - expensive → cheap model 知识迁移 (exemplar as few-shot demos)
  - 7 种可蒸馏任务类型自动检测
  - 成功率追踪 + 自适应 fallback 决策
  - 预期: 80-90% quality at 10-30% cost

### Bug Fixes

- Fixed `__init__` in both modules: 增加 `str` 类型 db_path 兼容 + `:memory:` 跳过 mkdir
- Fixed `knowledge_graph._init_db`: 自动创建最小 learnings 表 (standalone 运行兼容)

### Test Results

- KnowledgeGraph: 7/7 测试通过 (add_edge, bidirectional, BFS, find_path, clusters, stats, neighborhood)
- DistillationEngine: 7/7 测试通过 (store, get, build_prompt, record, should_try, report, cleanup)

---

## Version 0.4.0 — 2026-03-29 (Phase 6 Deep Integration)

### Overview

实现 v4.0 计划中的 Phase 6 全部 9 项深度集成任务。新增 5 个模块，增强 4 个核心模块。
新增 2 个测试框架 (property-based + golden dataset)。所有代码编译通过 + 全部测试通过。

### New Files Created

| # | File | Lines | Description |
|---|------|-------|-------------|
| I-017 | `agent/evolution/agentspec.py` | ~300 | AgentSpec 声明式安全 DSL (9条内建规则) |
| I-018 | `agent/evolution/drift_detector.py` | ~280 | PSI 行为漂移检测 (7个监控指标) |
| I-019 | `agent/evolution/debate_consensus.py` | ~330 | 多视角辩论共识协议 (4个内建视角) |
| I-020 | `tests/test_properties.py` | ~265 | Property-based 测试框架 (7个属性测试) |
| I-021 | `tests/test_golden.py` | ~380 | Golden dataset 回归测试 (11个内建用例) |

### Modules Enhanced

| # | File | Enhancement | Plan Item |
|---|------|-------------|-----------|
| E-015 | `llm/context_budget.py` | LLMLingua-2 压缩: TextCompressor (filler去除+冗余检测+重要性过滤) | 6.1 |
| E-016 | `evolution/prompt_tuner.py` | DSPy Signature: 4个内建签名 (learnings/reflection/briefing/OPRO) | 6.6 |
| E-017 | `evolution/checkpoint.py` | DecisionCheckpoint: 决策边界状态保存 + context manager | 6.3 |
| E-018 | `data/intelligence.py` | DK-CoT: 3类金融领域知识模板 (情感/风险/市场体制) | 6.5 |

### Test Results

- 9/9 文件编译通过
- AgentSpec: 9条规则, 安全文件修改→BLOCK ✅
- LLMLingua-2: 825→197字符 (ratio 0.239) ✅
- DriftDetector: PSI漂移检查正常 ✅
- DebateConsensus: 低风险→approve, 安全文件→block ✅
- Property tests: 7/7通过 (620 iterations) ✅
- Golden dataset: cost 100%, token_limits 100% ✅

---

## Version 0.3.4 — 2026-03-29 (Phase 5 Quick Wins Implementation)

### Overview

实现 v4.0 计划中的 Phase 5 全部 7 项快速胜利任务。新增 2 个工具模块，增强 3 个核心模块。
所有代码编译通过 + 逻辑验证通过。

### New Files Created

| # | File | Lines | Description |
|---|------|-------|-------------|
| I-015 | `agent/utils/cgroup_memory.py` | ~120 | Docker cgroup v1/v2 内存限制检测，防OOM |
| I-016 | `agent/utils/degradation.py` | ~200 | 三层优雅降级 (LIVE→CACHE→STATIC)，自动恢复 |

### Modules Enhanced

| # | File | Enhancement | Plan Item |
|---|------|-------------|-----------|
| E-012 | `evolution/learnings.py` | 向量搜索: store_embedding, vector_search (cosine), pack/unpack binary | 5.1 sqlite-vec |
| E-013 | `data/collector.py` | FTS5 全文搜索: news_fts 虚拟表 + 同步触发器 + search_news + rebuild_fts_index | 5.2 FTS5 |
| E-014 | `evolution/cost_optimizer.py` | Output token 约束 + Batch API (50% 折扣) + Prompt Caching (90% 折扣) + 综合节省报告 | 5.3/5.6/5.7 |

### Verification Results

- 5/5 modified .py files compile clean (py_compile)
- Logic tests: vector search (cosine sim=1.0), batch API lifecycle, prompt cache stats, cgroup detection, degradation state machine
- All tests passed

### Phase 5 Completion Status

| # | Task | Status |
|---|------|--------|
| 5.1 | sqlite-vec 向量搜索 → learnings | ✅ |
| 5.2 | FTS5 全文搜索 → collector | ✅ |
| 5.3 | Output token 约束 | ✅ |
| 5.4 | Python cgroup 感知 | ✅ |
| 5.5 | Graceful degradation tiers | ✅ |
| 5.6 | Batch API 支持 | ✅ |
| 5.7 | Prompt Caching 集成 | ✅ |

---

## Version 0.3.3 — 2026-03-28 (Research Rounds 2-5 + Advanced Implementation)

### Overview

完成5轮深度研究 (100+次搜索, 150+个发现)，涵盖:记忆架构、金融ML、Docker优化、
Prompt自动化、多Agent协调、成本优化、安全约束、评估框架、生产部署、中文NLP等。
基于研究结果实现8个新增/增强模块，所有代码编译通过，逻辑验证通过。

### Research Rounds (5 rounds, 100+ searches)

| Round | Focus | Searches | Key Findings |
|-------|-------|----------|--------------|
| 1 | Self-evolution papers & tools | 37 | Gödel Agent, Darwin Gödel Machine, A-Mem, AgentSpec, sqlite-vec, LLMLingua-2 |
| 2 | Memory architectures, Financial ML, Docker | 24 | Sleep-cycle consolidation, Zep temporal KG, PHANTOM hallucination detection, SQLite PRAGMA optimize |
| 3 | Prompt automation, Multi-agent, Cost optimization | 20+ | OPRO, DSPy, AutoPDL, A2A protocol, semantic caching (65x latency), model distillation |
| 4 | Safety, Evaluation, Testing | 24+ | Misevolution risk, constitutional constraints, SWE-bench, property-based testing, chaos engineering |
| 5 | Deployment, Monitoring, Chinese NLP, Resilience | 25+ | Drift detection, structured logging, circuit breaker, SQLite corruption recovery, Chinese tokenization |

### Research Documents Created

| # | Document | Content |
|---|----------|---------|
| R-002 | `2026-03-28_research-round-2.md` | Memory architectures, financial ML, Docker optimization |
| R-003 | `2026-03-28_research-round-3.md` | Prompt engineering, multi-agent, cost optimization |
| R-004 | `2026-03-28_research-round-4.md` | Safety, evaluation, testing frameworks |
| R-005 | `2026-03-28_research-round-5.md` | Production deployment, monitoring, Chinese NLP, resilience |

### New Files Created

| # | File | Lines | Description |
|---|------|-------|-------------|
| I-012 | `agent/utils/__init__.py` | ~10 | Utils package init |
| I-013 | `agent/utils/structured_log.py` | ~215 | Structured JSON logging (dual output: console + JSON file) |
| I-014 | `agent/utils/circuit_breaker.py` | ~288 | Circuit breaker pattern (CLOSED→OPEN→HALF_OPEN) + registry |

### Modules Enhanced

| # | File | Enhancement | Research Basis |
|---|------|-------------|----------------|
| E-007 | `evolution/learnings.py` | Sleep-cycle memory consolidation: merge, promote, archive, cross-link | Claude Auto Dream, A-Mem Zettelkasten |
| E-008 | `evolution/health_monitor.py` | SQLite health checks: PRAGMA integrity_check, optimize, WAL monitoring | Round 5 resilience research |
| E-009 | `evolution/self_edit.py` | Constitutional safety: 7 principles, AST regression detection, network allowlist | Misevolution, AgentSpec, NIST AI RMF |
| E-010 | `evolution/prompt_tuner.py` | OPRO-style LLM-driven prompt optimization with history tracking | OPRO (ICLR 2024), DSPy |
| E-011 | `evolution/cost_optimizer.py` | Semantic caching: n-gram fingerprints, fuzzy matching, similarity threshold | Semantic caching (65x latency) |

### Verification Results

- 8/8 new/modified .py files compile clean (py_compile)
- CircuitBreaker: 3-state machine (CLOSED→OPEN→HALF_OPEN) verified
- LearningsEngine.consolidate(): merge + promote + archive + cross_link verified
- CostOptimizer: exact cache hit + semantic fingerprinting verified
- SelfEditor: 7 constitutional principles + 4 allowlisted domains + AST regression detection
- PromptTuner: OPRO prompt generation + suggestion parsing + optimization history

---

## Version 0.3.2 — 2026-03-28 (Implementation: Evolution Subsystems)

### Overview

实施进化计划：新建 3 个子系统 (agent/data, agent/llm)，增强 5 个进化模块，
更新 supervisord 配置。所有代码编译通过，逻辑验证通过。

### New Files Created

| # | File | Lines | Description |
|---|------|-------|-------------|
| I-001 | `agent/data/__init__.py` | 13 | Data subsystem package init |
| I-002 | `agent/data/collector.py` | ~450 | 24/7 background data collection (Finnhub, CoinGecko, FRED, news) |
| I-003 | `agent/data/rate_limiter.py` | ~130 | Per-source API rate limit (token bucket, 9 sources configured) |
| I-004 | `agent/data/compliance.py` | ~170 | Legal compliance layer (pre/post request checks, backoff, disable) |
| I-005 | `agent/data/intelligence.py` | ~300 | Cross-mode intelligence pipeline (briefings, decisions, market snapshots) |
| I-006 | `agent/llm/__init__.py` | 18 | LLM abstraction package init |
| I-007 | `agent/llm/context_budget.py` | ~180 | Context Budget Manager (75% input, section-based allocation) |
| I-008 | `agent/llm/tool_translator.py` | ~200 | Tool schema translator + function calling fallback for non-OpenAI models |
| I-009 | `scripts/hooks/pre-commit` | ~130 | Git pre-commit hook (sensitive data detection) |
| I-010 | `scripts/install-hooks.sh` | 20 | Portable hook installer |
| I-011 | `.gitleaks.toml` | 65 | Secrets scanning config (gitleaks) |

### Modules Enhanced

| # | File | Enhancement | Research Basis |
|---|------|-------------|----------------|
| E-001 | `evolution/learnings.py` | FOREVER adaptive decay: λ(n)=λ₀×(1-β×tanh(γ×n)) | FOREVER (2026) |
| E-002 | `evolution/reflection.py` | PreFlect: prospective pre-task reflection from error history | PreFlect (2026) |
| E-003 | `evolution/skill_forge.py` | SkillRL dual bank (general/task_specific) + recipe compression + trust tiers | SkillRL (2025) |
| E-004 | `evolution/scheduler.py` | Cross-mode intelligence integration (data-collector → fin → chat) | — |
| E-005 | `evolution/cost_optimizer.py` | RouteLLM adaptive routing (success rate-based model selection) | RouteLLM (2024) |
| E-006 | `evolution/__init__.py` | Registered new subsystems (intelligence, context_budget, tool_translator) | — |

### Infrastructure Changes

| # | File | Change |
|---|------|--------|
| F-001 | `supervisord.conf` | Added data-collector process (4th process) |
| F-002 | `.gitignore` | Added *.db, .env.*, private/, personal/, SSH keys, OS credentials |
| F-003 | `agent/config/base.yaml` | Added compliance.data_protection section (retention, pre-commit) |

### Verification Results

- 13/13 new/modified .py files compile clean (py_compile)
- RateLimiter: 9 sources, token bucket, daily caps
- ContextBudgetManager: 98304 token input budget (75% of 131072)
- ToolCallFallback: JSON prompt injection + response parsing verified
- FOREVER decay: λ(0)=0.0500, λ(3)=0.0138, λ(10)=0.0100 ✓

---

## Version 0.3.1 — 2026-03-28 (Self-Evolution + 数据驱动的个人能力延伸系统)

### Overview

NeoMind 重新定义为 **数据驱动的个人能力延伸系统 (Data-Driven Personal Capability Extension System)**。
设计了完整的自我进化体系 (17个模块)、24/7 数据采集子系统、跨人格智能共享管线、
LLM无关抽象层，以及法律合规框架。所有设计基于50+论文深度研究。

### Config Changes (agent/config/)

| # | File | Change | Details |
|---|------|--------|---------|
| C-001 | `base.yaml` | 新增 `identity` 段 | name/tagline/version/philosophy, 写入"数据驱动的个人能力延伸系统" |
| C-002 | `base.yaml` | 新增 `evolution` 段 | self_modify 权限, safety 约束, forbidden_self_edit_files |
| C-003 | `base.yaml` | 新增 `language` 段 | user_communication: "zh", processing_languages: ["en","zh"], multilingual_search |
| C-004 | `base.yaml` | 新增 `cost` 段 | daily_evolution_budget: $0.06, monthly_cap: $5.00, model_pricing, optimization 策略 |
| C-005 | `base.yaml` | 新增 `llm` 段 | tool_format: "openai", context_budget_ratio: 0.75, prefer_structured_calls |
| C-006 | `base.yaml` | 新增 `host` 段 | Mac Studio, docker_memory_limit_gb: 2, internal_memory_budget_mb: 1800 |
| C-007 | `base.yaml` | 新增 `compliance` 段 | official_apis_only, rate_limits, forbidden actions, disclaimer |
| C-008 | `chat.yaml` | 完全重写 | 从 "Explorer" 升级为 "Command Center (指挥中心)", 新增 cross_mode_intelligence, evolution_awareness |
| C-009 | `fin.yaml` | system_prompt 更新 | 新增 SELF-EVOLUTION AWARENESS, identity 改为 "FINANCIAL COGNITIVE EXTENSION" |
| C-010 | `coding.yaml` | system_prompt 更新 | 新增 SELF-EVOLUTION AWARENESS, identity 改为 "TECHNICAL COGNITIVE EXTENSION" |

### Plan Documents Created

| # | Document | Lines | Content |
|---|----------|-------|---------|
| P-001 | `2026-03-28_self-evolution-strategy.md` | ~740 | 初版自进化战略研究 (OpenClaw/VOYAGER/EvoAgentX 对比) |
| P-002 | `2026-03-28_self-evolution-strategy-v2.md` | ~1100 | V2: 深度研究融入 (SkillRL/OPRO/MAE/PreFlect等) + 18个 #TAG |
| P-003 | `2026-03-28_self-evolution-implementation.md` | ~1050 | 工程实施方案 (Git-Gated自编辑, Prompt调优, 技能锻造) |
| P-004 | `2026-03-28_self-evolution-integration-plan.md` | ~1060 | 17模块集成计划 + 5层架构 + 依赖矩阵 + 8周路线图 |
| P-005 | `2026-03-28_enhanced-evolution-plan.md` | ~1300 | 核心文档: 数据采集子系统, 跨人格智能, 赚钱路线图, 自检协议 |
| P-006 | `2026-03-28_evolution-addendum-v4.1.md` | ~690 | 补充: 资源管理, 法律合规矩阵, 零停机重启, LLM无关抽象层, 监控 |

### Research Corrections Applied

| # | Error | Original | Corrected | Files |
|---|-------|----------|-----------|-------|
| R-001 | SkillRL token compression | "10-20% compression" | "10-20x compression" (数量级) | strategy-v2, integration-plan |
| R-002 | PreFlect improvement range | "10-15%" | "11-17% (实测11.68-17.14%)" | integration-plan (2处) |
| R-003 | s6-overlay memory claim | "<1MB内存" | "极低内存占用(具体数值未验证)" | integration-plan (2处) |

### Key Architecture Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D-001 | 数据采集采用方案B (独立后台进程) | 24/7运行, 进程隔离, ~150MB内存, supervisord管理 |
| D-002 | SQLite WAL 模式做跨进程数据共享 | 单写多读, Docker Named Volume, busy_timeout=5000ms |
| D-003 | LLM无关抽象层 (OpenAI兼容格式) | 统一tool schema, Context Budget Manager, smart routing |
| D-004 | 4级零停机重启 | importlib.reload → YAML reload → supervisord → docker restart |
| D-005 | 中文交流 + 语言无关处理 | user_communication: "zh", 内部搜索/分析不限语言 |

---

## Version 0.3.0 — 2026-03-21 (Finance + Telegram + gstack Integration)

### Features Added

| # | Feature | Files | Tests |
|---|---------|-------|-------|
| F-001 | Finance personality (fin mode) — 16 commands | `agent/config/fin.yaml`, `agent/finance/*` (17 files) | config switching tests |
| F-002 | Hybrid search v2 — query expansion, TF-IDF, temporal ranking, Google News RSS | `agent/finance/hybrid_search.py` | TF-IDF + expansion tests |
| F-003 | HTML dashboard generator (Chart.js) | `agent/finance/dashboard.py` | render tests |
| F-004 | Telegram bot — independent bot identity | `agent/finance/telegram_bot.py` | 48 tests |
| F-005 | OpenClaw integration — gateway + skill + memory bridge | `agent/finance/openclaw_*.py`, `memory_bridge.py` | protocol + handoff tests |
| F-006 | Docker deployment (CLI + Telegram daemon) | `Dockerfile`, `docker-compose*.yml`, `docker-entrypoint.sh` | build validation |
| F-007 | Per-chat mode (SQLite) | `agent/finance/chat_store.py` | 5 per-chat mode tests |
| F-008 | Streaming thinking with expandable blockquote | `telegram_bot.py` `_ask_llm_streaming` | manual Telegram test |
| F-009 | Auto-compact (90% trigger, 30% target) | `telegram_bot.py` `_auto_compact_if_needed_db` | compact tests |
| F-010 | Provider fallback (DeepSeek → z.ai) | `telegram_bot.py` `_get_provider_chain` | provider chain tests |
| F-011 | Hacker News integration + /subscribe auto-push | `agent/finance/hackernews.py` | fetch + format tests |
| F-012 | Skill system (SKILL.md loader + 10 skills) | `agent/skills/` | 17 skill tests |
| F-013 | Browser daemon (Playwright persistent Chromium) | `agent/browser/daemon.py` | import tests |
| F-014 | Safety guards (/careful /freeze /guard) | `agent/workflow/guards.py` | 12 guard tests |
| F-015 | Sprint framework (Think→Plan→Build→Review→Test→Ship) | `agent/workflow/sprint.py` | 7 sprint tests |
| F-016 | Evidence trail (JSONL audit log) | `agent/workflow/evidence.py` | 8 evidence tests |
| F-017 | Review dispatcher (mode-aware) | `agent/workflow/review.py` | 4 review tests |
| F-018 | LiteLLM + Ollama optional provider | `core.py`, `telegram_bot.py` | 6 provider tests |
| F-019 | /provider command (runtime switch) | `telegram_bot.py` | manual test |

### Bugs Found & Fixed

| # | Bug | Root Cause | Fix | Found By |
|---|-----|-----------|-----|----------|
| B-001 | `Page` type undefined without Playwright | Type annotation at class-definition time | Stub types in except block | import test |
| B-002 | Sprint `_save()` TypeError str/str | `SPRINTS_DIR` can be str not Path | `Path(self.SPRINTS_DIR)` | simulation test |
| B-003 | Thinking content not distinct in Telegram | `<i>` tag insufficient | `<blockquote expandable>` | manual test |
| B-004 | Auto-compact 291→291 (no reduction) | Summary as long as originals | Remove summaries, just drop old messages | manual test |
| B-005 | "哈咯" not recognized | Hardcoded greeting list | Removed all hardcoded rules, route through LLM | manual test |
| B-006 | Mode global not per-chat | Single `_current_mode` variable | SQLite `chats.mode` column per chat_id | design review |
| B-007 | DeepSeek timeout kills bot | No fallback provider | Provider chain: DeepSeek → z.ai | production timeout |
| B-008 | `.dockerignore` excluded entrypoint | Listed in ignore but Dockerfile COPY needs it | Removed from `.dockerignore` | Docker build fail |
| B-009 | `pip install -e .[finance]` fails in Docker | deps stage missing source files | Single-stage build with direct pip install | Docker build fail |
| B-010 | README had fake-looking real token format | `7123456789:AAF4x9...` too realistic | Changed to `<placeholder>` | security audit |
| B-011 | `/history` missing from Telegram | No command for active messages | Added as `/admin history` alias | feature gap review |
| B-012 | Bot not responding in group | Telegram Privacy Mode on by default | Document: disable via BotFather /setprivacy | production test |
| B-013 | `/model` typo not caught | No unknown command handler | Added typo suggestion handler | manual test |
| B-014 | Compact doesn't re-trigger after LLM response | Only pre-check, not post-check | Added post-response compact check | manual test |

### Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `tests/test_telegram_bot.py` | 48 | ChatStore, MessageRouter, AutoCompact, AgentCollaborator, Persistence |
| `tests/test_skills.py` | 17 | Skill loading, parsing, per-mode filtering, singleton |
| `tests/test_workflow.py` | 30 | Guards, Sprint, Evidence, Review |
| **Total** | **95** | |

### Module Count

29 Python modules, 10 SKILL.md files, 4 YAML configs, all import clean.
