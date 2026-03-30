# NeoMind 自我进化系统 — 综合集成计划 v4.0

> 日期: 2026-03-29
> 前序: v3.0 (2026-03-28, 基于6轮早期研究 + 50论文)
> 本版新增: 5轮深度研究 (100+次搜索, 150+发现, 覆盖记忆/金融ML/安全/部署/中文NLP)
> 状态: v3.0的Phase 1-4已实现 + v4.0的7个高优先级模块已实现

---

## 0. 与 v3.0 的差异

v3.0 定义了17个进化模块的架构和4阶段路线图。v4.0 在此基础上:

1. **新增3个子系统** — `agent/data` (24/7数据采集), `agent/llm` (LLM抽象), `agent/utils` (通用工具)
2. **新增7个已实现模块** — sleep-cycle记忆整合、SQLite健康检查、宪法安全约束、OPRO prompt优化、语义缓存、结构化日志、断路器
3. **新增12个待实现项** — sqlite-vec、LLMLingua-2、FTS5、Gödel Agent monkey patching、Darwin进化变体池、漂移检测、state checkpointing等
4. **新增4个计划章节** — 评估框架、测试策略、生产部署、中文NLP优化
5. **更新风险矩阵** — 加入misevolution(自进化安全退化)这一核心风险

---

## 1. 模块全景图 (更新)

### 1.1 分层架构

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                      Layer 6: 数据层 (Data) [v4 新增]                      ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  ║
║  │ collector    │  │ rate_limiter │  │ compliance   │  │intelligence│  ║
║  │ 24/7数据采集  │  │ 速率控制      │  │ 法规合规      │  │ 跨模式智能  │  ║
║  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘  ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                      Layer 5: 元进化层 (Meta)                              ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐           ║
║  │ meta_evolve  │  │cost_optimizer│  │ dashboard            │           ║
║  │ 策略自调节    │  │ 预算/路由/缓存│  │ 可视化               │           ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘           ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                      Layer 4: 主动进化层 (Active Evolution)               ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐           ║
║  │ goal_tracker │  │ prompt_tuner │  │ self_edit             │           ║
║  │ 自主目标      │  │ OPRO自优化   │  │ 宪法安全+Git-gated    │           ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘           ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                      Layer 3: 认知层 (Cognition)                          ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐           ║
║  │ learnings    │  │ skill_forge  │  │ reflection            │           ║
║  │ sleep整合    │  │ 双库+信任分级 │  │ PreFlect前瞻反思      │           ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘           ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                      Layer 2: 生存层 (Survival)                           ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐           ║
║  │ self_unblock │  │ checkpoint   │  │ upgrade               │           ║
║  │ 自我解围      │  │ 状态存档      │  │ Git自升级             │           ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘           ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                      Layer 1: 基础设施层 (Infra)                          ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐           ║
║  │ auto_evolve  │  │health_monitor│  │ watchdog              │           ║
║  │ 健康检查/审计 │  │ SQLite健康   │  │ 最后手段重启           │           ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘           ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                      Layer 0.5: 通用工具层 (Utils) [v4 新增]              ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐           ║
║  │structured_log│  │circuit_breaker│ │ context_budget        │           ║
║  │ JSON结构日志  │  │ 断路器+退避   │  │ 上下文预算管理         │           ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘           ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                      Layer 0: 调度器 (Orchestration)                     ║
║  ┌────────────────────────────────────────────────────────────────┐     ║
║  │                         scheduler.py                            │     ║
║  │   on_session_start → on_turn_complete → on_session_end         │     ║
║  │   on_error → get_prompt_additions → get_evolution_status        │     ║
║  └────────────────────────────────────────────────────────────────┘     ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

### 1.2 模块清单 (v3: 17个 → v4: 25个)

| # | 模块 | 文件 | 行数 | 状态 | 职责 |
|---|------|------|------|------|------|
| 1 | scheduler | `evolution/scheduler.py` | 541 | v3 ✅ | 生命周期编排 |
| 2 | auto_evolve | `evolution/auto_evolve.py` | 763 | v3 ✅ | 启动检查、审计 |
| 3 | health_monitor | `evolution/health_monitor.py` | 598 | v4 增强 | 心跳+**SQLite健康** |
| 4 | watchdog | `evolution/watchdog.py` | 212 | v3 ✅ | 最后手段重启 |
| 5 | checkpoint | `evolution/checkpoint.py` | 186 | v3 ✅ | 状态保存/恢复 |
| 6 | self_unblock | `evolution/self_unblock.py` | 397 | v3 ✅ | 自诊断+修复 |
| 7 | self_edit | `evolution/self_edit.py` | 571 | v4 增强 | Git-gated + **宪法安全** |
| 8 | upgrade | `evolution/upgrade.py` | 264 | v3 ✅ | Git升级拉取 |
| 9 | learnings | `evolution/learnings.py` | 741 | v4 增强 | Ebbinghaus + **sleep整合** |
| 10 | skill_forge | `evolution/skill_forge.py` | 461+ | v3 增强 | 双库+信任分级 |
| 11 | reflection | `evolution/reflection.py` | 448+ | v3 增强 | PreFlect前瞻反思 |
| 12 | prompt_tuner | `evolution/prompt_tuner.py` | 574 | v4 增强 | YAML调优 + **OPRO** |
| 13 | goal_tracker | `evolution/goal_tracker.py` | 400 | v3 ✅ | 自主目标 |
| 14 | meta_evolve | `evolution/meta_evolve.py` | 301 | v3 ✅ | 策略自调节 |
| 15 | cost_optimizer | `evolution/cost_optimizer.py` | 594 | v4 增强 | 路由+缓存+**语义缓存** |
| 16 | dashboard | `evolution/dashboard.py` | 556 | v3 ✅ | HTML可视化 |
| 17 | collector | `data/collector.py` | ~450 | v3.2 新建 | 24/7金融数据采集 |
| 18 | rate_limiter | `data/rate_limiter.py` | ~130 | v3.2 新建 | 9源速率控制 |
| 19 | compliance | `data/compliance.py` | ~170 | v3.2 新建 | API法规合规 |
| 20 | intelligence | `data/intelligence.py` | ~300 | v3.2 新建 | 跨模式智能管道 |
| 21 | context_budget | `llm/context_budget.py` | ~180 | v3.2 新建 | 75%上下文分配 |
| 22 | tool_translator | `llm/tool_translator.py` | ~200 | v3.2 新建 | 工具Schema翻译 |
| 23 | structured_log | `utils/structured_log.py` | 215 | v4 新建 | JSON日志+追踪 |
| 24 | circuit_breaker | `utils/circuit_breaker.py` | 287 | v4 新建 | 三状态断路器 |
| — | tool_translator | `llm/tool_translator.py` | ~200 | v3.2 新建 | ToolCallFallback |

---

## 2. 研究增强层 (v4 新增/更新)

> v3.0 的研究增强内容保持不变（FOREVER衰减、SimpleMem、ReMe、SkillRL等）。
> 以下仅列出 v4.0 五轮研究的新增发现。

### 2.1 learnings — 新增: Sleep-Cycle + 知识图谱

| 研究 | 来源 | 状态 | 影响 |
|------|------|------|------|
| Sleep-cycle记忆整合 | Claude Auto Dream (Anthropic生产) | ✅ 已实现 | 合并冗余/提升/归档/交叉链接 |
| A-Mem Zettelkasten | NeurIPS 2025, arxiv 2502.12110 | ⏳ 待实现 | 扁平列表→互联知识图 |
| sqlite-vec向量搜索 (纯Python实现) | github.com/asg017/sqlite-vec | ✅ 已实现 | SQLite内语义检索 (cosine similarity) |
| Zep时间知识图 | arxiv 2501.13956 | 📋 规划中 | 时间感知金融推理 |
| MACLA层次化过程记忆 | arxiv 2512.18950 | 📋 规划中 | skill_forge层次化 |
| H-MEM多层语义抽象 | arxiv 2507.22925 | 📋 规划中 | 索引路由减少穷举 |

**已实现 `consolidate()` 方法:** 运行于离峰时段，执行4步操作:
1. 按(mode, category)分组，合并相似度>50%的学习 (强化最强者，删除冗余)
2. 促进高召回率学习 (recall_rate > 1.0/天 → importance +0.2)
3. 归档90天以上但strength>0.6的学习到 `consolidated_learnings` 表
4. 交叉链接同类别/同模式的相关学习 (`related_ids` JSON数组)

### 2.2 self_edit — 新增: 宪法安全约束

| 研究 | 来源 | 状态 | 影响 |
|------|------|------|------|
| Constitutional AI约束 | Anthropic理念 + ISACA研究 | ✅ 已实现 | 7条不可覆盖原则 |
| AST安全回归检测 | Misevolution研究 (Round 4) | ✅ 已实现 | try/except/log/assert不可减少 |
| 网络调用白名单 | NIST AI RMF, OWASP GenAI | ✅ 已实现 | 4个允许域名 |
| AgentSpec声明式DSL | ICSE 2026, arxiv 2503.18666 | ✅ 已实现 | 9条规则, trigger/predicate/enforcement |
| Gödel Agent monkey patch | ACL 2025, arxiv 2410.04444 | ⏳ 待实现 | 运行时即时生效 |
| E2B/Modal沙箱隔离 | 企业实践 (Round 4) | 📋 规划中 | Firecracker microVM |

**已实现的宪法原则 (Guard 6.5):**
1. 永不修改安全关键文件 (self_edit.py, health_monitor.py, watchdog.py)
2. 永不引入禁用安全检查或日志的代码
3. 永不削弱现有安全约束
4. 永不添加白名单外的网络访问
5. 每次自编辑必须可通过git revert撤销
6. 自编辑代码不得增加>10MB内存使用
7. 永不修改compliance/rate_limiter使之更宽松

**`_detect_safety_regression()` 方法:** 对比新旧AST，确保以下计数不减少: try/except块、logging调用、assert语句、if guard条件。

### 2.3 prompt_tuner — 新增: OPRO自优化

| 研究 | 来源 | 状态 | 影响 |
|------|------|------|------|
| OPRO LLM-as-Optimizer | Google DeepMind, ICLR 2024 | ✅ 已实现 | LLM自主优化prompt参数 |
| DSPy声明式编程 | Stanford, dspy.ai | ✅ 已实现 | SignatureOptimizer + 4内建签名 |
| AutoPDL自动搜索 | Salesforce, arxiv 2504.04365 | 📋 规划中 | AutoML思路搜索prompt空间 |
| EvoPrompt遗传算法 | 2024 | 📋 规划中 | 交叉+变异+选择 |

**已实现:** `generate_variant(mode, use_opro=True)` 返回OPRO优化prompt，包含当前参数、历史信号、搜索空间边界和过去优化尝试。调用方将prompt发给LLM，用 `parse_opro_suggestion()` 解析建议并验证bounds。

### 2.4 cost_optimizer — 新增: 语义缓存

| 研究 | 来源 | 状态 | 影响 |
|------|------|------|------|
| 语义缓存 (65x延迟改进) | 多源 (Round 3) | ✅ 已实现 | N-gram指纹+模糊匹配 |
| Batch API 50%折扣 | Anthropic/DeepSeek | ✅ 已实现 | 非实时任务批处理 |
| Prompt Caching 90%折扣 | Anthropic/DeepSeek | ✅ 已实现 | 重复前缀缓存 |
| 模型蒸馏 | Round 3 研究 | 📋 规划中 | 80-90%质量, 10-30%成本 |
| Output token约束 | Round 3 研究 | ✅ 已实现 | 每personality设上限 |

**已实现:** `semantic_cache_check(prompt, threshold=0.85)` 和 `cache_with_semantic_key()` — 为每个prompt创建normalized hash + N-gram fingerprint，存储在 `semantic_fingerprints` 表中。查询时先精确匹配（快路径），再模糊匹配（Jaccard相似度）。

### 2.5 health_monitor — 新增: SQLite健康检查

| 研究 | 来源 | 状态 | 影响 |
|------|------|------|------|
| PRAGMA integrity_check | Round 5 韧性研究 | ✅ 已实现 | 4小时周期检测损坏 |
| PRAGMA optimize | SQLite最佳实践 | ✅ 已实现 | 维持查询性能 |
| WAL自动checkpoint | Round 2 Docker研究 | ✅ 已实现 | >10MB时被动checkpoint |
| 行为漂移检测 (PSI) | Round 5 监控研究 | ✅ 已实现 | DriftDetector + 7指标 |
| Python cgroup感知 | Round 2 Docker研究 | ✅ 已实现 | 防OOM kill |

**已实现:** `check_sqlite_health()` 遍历5个数据库(learnings, cost_tracking, market_data, news_data, briefings)，执行integrity_check + optimize + WAL监控。集成到watchdog_loop，每480次迭代(4小时)执行一次。损坏时通过Telegram告警。

### 2.6 新工具模块

| 模块 | 来源 | 状态 | 核心功能 |
|------|------|------|----------|
| structured_log | Round 5 可观测性 | ✅ 已实现 | 双输出(console+JSON), LogContext, LLM调用记录 |
| circuit_breaker | Round 5 韧性研究 | ✅ 已实现 | CLOSED→OPEN→HALF_OPEN, 指数退避, 全局注册表 |
| context_budget | v3.2 LLM抽象 | ✅ 已实现 | 75%分配, section优先级 |
| tool_translator | v3.2 LLM抽象 | ✅ 已实现 | OpenAI格式统一, ToolCallFallback |

---

## 3. 新增计划章节 (v4)

### 3.1 评估框架 (Round 4 发现)

**核心问题:** 自进化agent如何知道自己变好了还是变差了？

**三层评估:**

| 层级 | 方法 | 频率 | 来源 |
|------|------|------|------|
| 静态基准 | SWE-bench (1865问题), AgentBench (8环境) | 月度 | Round 4 |
| 持续评估 | Golden dataset回归测试, 变异退化检测 | 每次self_edit | Round 4 |
| 安全评估 | Metamorphic testing, 对抗性测试, misevolution监控 | 周度 | Round 4 |

**多维指标体系 (CLASSic):**

| 维度 | 指标 | 数据源 |
|------|------|--------|
| Cost | 日API开销, token/请求比 | cost_optimizer |
| Latency | P50/P95响应延迟 | structured_log |
| Accuracy | 任务成功率, 用户满意度 | prompt_tuner signals |
| Stability | 不间断运行时间, 崩溃频率 | health_monitor |
| Security | 宪法违规次数, 安全回归检测数 | self_edit |

### 3.2 测试策略 (Round 4 发现)

| 测试类型 | 工具/方法 | 覆盖目标 |
|----------|----------|----------|
| 单元测试 | Mock LLM (llmock), DeepEval | 各模块独立逻辑 |
| Property-based | LLM生成属性, 无需oracle | self_edit变异一致性 |
| Metamorphic | 输入扰动→输出关系验证 | 行为稳定性 |
| Chaos engineering | agent-chaos: 注入工具故障/截断推理/损坏记忆 | 韧性 |
| 回归测试 | Golden dataset, >80%覆盖 | self_edit前后对比 |

### 3.3 生产部署 (Round 5 发现)

**当前部署:** Docker on Mac Studio, 2GB内存, supervisord管理4进程

**关键改进方向:**

| 改进 | 理由 | 优先级 |
|------|------|--------|
| Graceful degradation tiers (live→cache→static) | 单一故障点不应导致完全不可用 | P1 |
| State checkpointing at decision boundaries | 崩溃后可恢复到最近决策点 | P1 |
| 零停机部署 (health check + rolling restart) | 升级不中断24/7数据采集 | P2 |
| 内存峰值监控 (tool call导致15.4x spike) | 防OOM, 需per-tool限制 | P2 |
| Docker Compose models元素 | 声明DeepSeek为基础设施 | P3 |

### 3.4 中文NLP优化 (Round 5 发现)

**核心问题:** CJK tokenization比English贵4-5x

| 发现 | 影响 | 对策 |
|------|------|------|
| 中文token效率低 | 同内容API成本翻4-5倍 | DeepSeek原生中文优化是优势 |
| 通用LLM有60%+ English bias | 中文prompt质量下降 | system prompt用英文, user context用中文 |
| DK-CoT领域知识链式思考 | 提升金融情感分析准确率 | 在fin模式中注入领域知识 |
| MSumBench中文摘要评估 | 需要基准衡量质量 | 用于评估briefing生成质量 |

---

## 4. 分阶段路线图 (v4 更新)

> Phase 1-4 (v3.0) 已在2026-03-28完成实现。
> 以下为 v4.0 新增阶段。

### Phase 5: 研究成果集成 — 快速胜利 (Week 1-2)

| # | 任务 | 模块 | 优先级 | 估时 | 来源 |
|---|------|------|--------|------|------|
| 5.1 | sqlite-vec集成到learnings + skill_forge | learnings, skill_forge | P1 | 3天 | Round 1 | ✅ |
| 5.2 | FTS5全文搜索集成到news_data.db | collector | P1 | 1天 | Round 1 | ✅ |
| 5.3 | Output token约束 (每personality上限) | cost_optimizer | P1 | 1天 | Round 3 | ✅ |
| 5.4 | Python cgroup感知 (Docker内存) | utils/cgroup_memory | P1 | 0.5天 | Round 2 | ✅ |
| 5.5 | Graceful degradation tiers | utils/degradation | P1 | 2天 | Round 5 | ✅ |
| 5.6 | Batch API支持 (非实时任务) | cost_optimizer | P2 | 1天 | Round 3 | ✅ |
| 5.7 | Prompt Caching集成 | cost_optimizer | P2 | 1天 | Round 3 | ✅ |

### Phase 6: 深度集成 (Week 3-6)

| # | 任务 | 模块 | 优先级 | 估时 | 来源 |
|---|------|------|--------|------|------|
| 6.1 | LLMLingua-2压缩层 | context_budget | P1 | 1周 | Round 1 | ✅ |
| 6.2 | AgentSpec声明式安全DSL | agentspec (新) | P1 | 1周 | Round 1 | ✅ |
| 6.3 | State checkpointing at decisions | checkpoint | P1 | 3天 | Round 5 | ✅ |
| 6.4 | 行为漂移检测 (PSI监控) | drift_detector (新) | P1 | 3天 | Round 5 | ✅ |
| 6.5 | DK-CoT领域知识注入 (fin模式) | intelligence | P2 | 3天 | Round 5 | ✅ |
| 6.6 | DSPy签名优化 | prompt_tuner | P2 | 1周 | Round 3 | ✅ |
| 6.7 | Property-based testing框架 | tests/ | P2 | 3天 | Round 4 | ✅ |
| 6.8 | Debate-based consensus协议 | debate_consensus (新) | P2 | 1周 | Round 3 | ✅ |
| 6.9 | Golden dataset回归测试 | tests/ | P2 | 3天 | Round 4 | ✅ |

### Phase 7: 高级进化 (Week 7-12)

| # | 任务 | 模块 | 优先级 | 估时 | 来源 |
|---|------|------|--------|------|------|
| 7.1 | ✅ A-Mem Zettelkasten知识图 | learnings | P2 | 2周 | Round 1 |
| 7.2 | Darwin Gödel Machine进化变体池 | meta_evolve | P2 | 2周 | Round 1 |
| 7.3 | Gödel Agent monkey patching | self_edit | P2 | 2周 | Round 1 |
| 7.4 | ✅ 模型蒸馏 fallback chain | cost_optimizer | P3 | 2周 | Round 3 |
| 7.5 | Prometheus+Grafana可观测性栈 | 基础设施 | P3 | 1周 | Round 5 |
| 7.6 | Chaos engineering测试 | tests/ | P3 | 1周 | Round 4 |
| 7.7 | TDAG动态子Agent生成 | scheduler | P3 | 2周 | Round 3 |
| 7.8 | 形式化验证 (PSV框架) | self_edit | P3 | 3周 | Round 4 |

---

## 5. 风险矩阵 (v4 更新)

| 风险 | 可能性 | 影响 | 缓解措施 | 来源 |
|------|--------|------|---------|------|
| **Misevolution — 自进化安全退化** | 中 | 极高 | 宪法约束 ✅ + AST回归检测 ✅ + 分层防御 | Round 4 核心发现 |
| Self-edit 引入bug | 中 | 高 | AST安全 + pytest沙箱 + git回滚 + 10次/天 + 宪法审查 ✅ | v3 + v4 |
| SQLite WAL Docker损坏 | 低 | 高 | integrity_check ✅ + WAL checkpoint ✅ + volume不bind mount | v3 + Round 5 |
| 行为漂移 (6月内20-30%退化) | 高 | 中 | 漂移检测 ⏳ + 回归测试 ⏳ + 多维指标 | Round 5 新发现 |
| API级联故障 | 中 | 中 | 断路器 ✅ + 指数退避 + graceful degradation ⏳ | Round 5 |
| 中文token成本过高 | 高 | 低 | DeepSeek原生优化 + 双语prompt策略 ⏳ | Round 5 |
| 进化overhead超预算 | 中 | 低 | cost_optimizer $0.06/day + 语义缓存 ✅ + output约束 ⏳ | v3 + Round 3 |
| 技能库prompt injection | 低 | 高 | 信任分级 ✅ + 内容审查 | v3 |
| Boot loop | 低 | 高 | 3次/5分钟检测 → safe mode + Telegram | v3 |
| 记忆膨胀 | 中 | 中 | Ebbinghaus ✅ + sleep整合 ✅ + ReMe效用剪枝 | v3 + Round 2 |

---

## 6. 成功指标 (v4 更新)

| 指标 | v3基线 | v4当前 | Phase 5目标 | Phase 7目标 |
|------|--------|--------|-------------|-------------|
| 模块总数 | 17 | 27 | 25 | 25+ |
| 已实现研究增强 | 0 | 25 ✅ Phase 5+6+7 | 14 | 19 |
| 宪法安全原则 | 0 | 7 | 7 | 10+ (AgentSpec) |
| 缓存命中率 (精确+语义) | 0% | 精确 ✅ | 30%+ | 50%+ |
| 24/7运行稳定性 | 未测试 | SQLite健康 ✅ | 7天+ | 30天+ |
| 进化日开销 | $0.06上限 | $0.06上限 | <$0.04 | <$0.03 |
| 错误重复率 | 无数据 | 有learnings | <30% | <15% |
| 记忆整合效率 | 无 | 合并+归档 ✅ | 冗余<20% | 冗余<10% |

---

## 7. 研究参考文献总表 (v4 新增)

### Round 1: 自进化核心

| 论文/项目 | 关键贡献 | 目标模块 | 状态 |
|-----------|---------|----------|------|
| Gödel Agent (ACL 2025) | 运行时monkey patching | self_edit | ⏳ |
| Darwin Gödel Machine (Sakana AI) | 进化变体池, SWE-bench 20→50% | meta_evolve | ⏳ |
| A-Mem (NeurIPS 2025) | Zettelkasten互联知识图 | learnings | ⏳ |
| AgentSpec (ICSE 2026) | 声明式安全DSL | self_edit | ⏳ |
| sqlite-vec | SQLite内向量搜索 | learnings, skill_forge | ⏳ |
| LLMLingua-2 (ACL 2024) | 20x prompt压缩 | context_budget | ⏳ |

### Round 2: 记忆+金融+Docker

| 论文/项目 | 关键贡献 | 目标模块 | 状态 |
|-----------|---------|----------|------|
| Claude Auto Dream | Sleep-cycle记忆整合 | learnings | ✅ |
| Zep TKG (2025) | 时间感知知识图 | intelligence | 📋 |
| PHANTOM | 金融幻觉检测基准 | fin mode eval | ⏳ |
| MM-iTransformer | 多模态融合(情感+价格) | collector | 📋 |
| SQLite PRAGMA optimize | 4小时周期优化 | health_monitor | ✅ |

### Round 3: Prompt+多Agent+成本

| 论文/项目 | 关键贡献 | 目标模块 | 状态 |
|-----------|---------|----------|------|
| OPRO (ICLR 2024) | LLM自驱动prompt优化 | prompt_tuner | ✅ |
| DSPy (Stanford) | 声明式prompt编程 | prompt_tuner | ⏳ |
| A2A Protocol (Linux Foundation) | Agent间标准协议 | scheduler | 📋 |
| Semantic caching | 65x延迟改进 | cost_optimizer | ✅ |
| Debate-based consensus | 多轮辩论协议 | scheduler | ⏳ |

### Round 4: 安全+评估+测试

| 论文/项目 | 关键贡献 | 目标模块 | 状态 |
|-----------|---------|----------|------|
| Misevolution研究 | 自进化安全退化核心风险 | self_edit | ✅ (宪法) |
| SWE-bench | 1865问题代码生成评估 | tests/ | ⏳ |
| PSV Framework | 形式化验证作进化奖励 | self_edit | 📋 |
| Chaos engineering | 故障注入韧性测试 | tests/ | ⏳ |
| Property-based testing | 无需oracle的行为验证 | tests/ | ⏳ |

### Round 5: 部署+监控+中文+韧性

| 论文/项目 | 关键贡献 | 目标模块 | 状态 |
|-----------|---------|----------|------|
| 结构化JSON日志 | 可观测性基础 | structured_log | ✅ |
| 断路器模式 | 防级联故障 | circuit_breaker | ✅ |
| SQLite integrity_check | 数据库损坏检测 | health_monitor | ✅ |
| 行为漂移检测 | 20-30% 6月退化风险 | health_monitor | ⏳ |
| DK-CoT | 领域知识链式思考 | intelligence | ⏳ |

---

## 8. 文档索引

| 文档 | 内容 | 权威性 |
|------|------|--------|
| `2026-03-29_evolution-plan-v4.md` | **本文档** — 当前权威计划 | 最高 |
| `2026-03-28_self-evolution-integration-plan.md` | v3.0 旧计划 (仍含有效的模块细节) | 模块实现细节参考 |
| `2026-03-28_research-round-{1-5}.md` | 五轮研究原始报告 | 研究细节参考 |
| `2026-03-28_research-consolidated.md` | 五轮研究综合摘要 | 快速参考 |
| `2026-03-28_plan-diffs.md` | 每轮研究后的计划增量 | 变更追踪 |
| `2026-03-28_PLAN-INDEX.md` | 文档关系图 + 查找表 | 导航 |
| `CHANGELOG.md` | 版本变更日志 (v0.3.1 → v0.3.3) | 实施记录 |

---

> **图例:** ✅ 已实现 | ⏳ 待实现(高优先级) | 📋 规划中(中低优先级)
>
> 本文档是 NeoMind 自我进化系统的活文档。下次更新时间: Phase 5 完成后。
