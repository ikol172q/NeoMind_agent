# NeoMind 五轮研究 — Plan Diff 记录

> 本文档记录每轮研究后对主计划 (`self-evolution-integration-plan.md`) 应做的增量更新。
> 注意: 这些 diff 是事后补写的（本应在每轮完成后立即更新主计划）。

---

## Plan Diff #1 — Round 1 完成后

**时间:** 2026-03-28 ~20:00 UTC (Session 1)
**研究:** 37次搜索, 38个发现

### 主计划应新增/修改的内容:

```diff
## 2. 研究增强层

### 2.3 learnings (认知层)
- 现有: Ebbinghaus FOREVER 自适应衰减
+ 新增: A-Mem Zettelkasten 互联知识图 (NeurIPS 2025)
+   - learnings 从扁平列表升级为互联知识网络
+   - 自动生成笔记元数据 + 关联链接
+ 新增: sqlite-vec 向量搜索扩展
+   - 语义相似度检索, 不需外部向量数据库
+   - K-NN 查询 + SIMD 加速
+ 新增: Mem-α RL记忆管理策略
+   - 用RL训练agent决定存什么/怎么组织/何时更新

### 2.5 self_edit (主动进化层)
- 现有: Git-gated + AST safety + 10/day limit
+ 新增: Gödel Agent monkey patching (ACL 2025)
+   - 从"编辑文件→重载"升级为"运行时monkey patch→即时生效"
+ 新增: AgentSpec 声明式安全约束 (ICSE 2026)
+   - DSL 定义 trigger/predicate/enforcement, 毫秒级开销

### 2.6 meta_evolve (元进化层)
- 现有: 单一策略自调节
+ 新增: Darwin Gödel Machine 进化变体池 (Sakana AI)
+   - 维护多个策略变体, SWE-bench 20%→50%

### 2.8 context_budget (LLM抽象层)
- 现有: 75% input, section-based allocation
+ 新增: LLMLingua-2 压缩层 (Microsoft, ACL 2024)
+   - 20x prompt 压缩, 直接降低 API 成本

## 4. 分阶段路线图
### Phase 5 (新增):
+ [ ] sqlite-vec 集成到 learnings + skill_forge
+ [ ] LLMLingua-2 集成到 context_budget
+ [ ] AgentSpec 声明式约束替换硬编码 AST 检查
+ [ ] Gödel Agent monkey patching 实验
```

---

## Plan Diff #2 — Round 2 完成后

**时间:** 2026-03-28 ~23:27 UTC (Session 2)
**研究:** 24次搜索, 重点: 记忆架构 + 金融ML + Docker优化

### 主计划应新增/修改的内容:

```diff
## 2. 研究增强层

### 2.3 learnings (认知层)
+ 新增: Sleep-cycle 记忆整合 (Claude Auto Dream)
+   - 离峰时段合并冗余、提升高召回、归档旧知识
+   - 生产级模式, Anthropic 已在 Claude Code 中使用
+ 新增: Zep 时间知识图架构 (arxiv 2501.13956)
+   - 超越 MemGPT 的深度记忆检索
+   - 时间感知对金融时序数据至关重要
+ 新增: MAGMA 多图记忆 (语义+时间+因果)

### 2.9 data/collector (数据层) — 新增子节
+ 新增: PHANTOM 金融幻觉检测 (OpenReview)
+   - 评估 fin 模式的幻觉风险, 年损失 $250M+
+ 新增: MM-iTransformer 多模态融合
+   - 情感分析 + 时序预测 融合提升准确率
+ 新增: TradingAgents 多Agent组合风险评估
+ 新增: FinKario 金融事件知识图模板

### 2.10 health_monitor (安全层) — 修改
+ 新增: SQLite PRAGMA integrity_check + optimize (4小时周期)
+ 新增: WAL 文件监控 + 自动 checkpoint (>10MB)
+ 新增: Python cgroup 感知 (防止 Docker OOM)

## 3. 集成架构
### 3.3 Docker 部署拓扑 — 修改
+ 新增: SIGTERM graceful shutdown handler
+   - flush buffers, close DB, finalize WAL
+ 新增: 考虑 s6-overlay 替代 supervisord (内存更低, 但待验证)
+ 新增: staggered startup 避免内存峰值
```

---

## Plan Diff #3 — Round 3 完成后

**时间:** 2026-03-28 ~23:27 UTC (Session 2, 与Round 2并行)
**研究:** 20+次搜索, 重点: Prompt自动化 + 多Agent + 成本优化

### 主计划应新增/修改的内容:

```diff
## 2. 研究增强层

### 2.4 prompt_tuner (主动进化层) — 重大升级
- 现有: 规则化 YAML 参数调优 (signal → variant → adopt)
+ 新增: OPRO LLM自驱动优化 (Google DeepMind, ICLR 2024)
+   - LLM 自身作为 optimizer, 迭代优化 prompt
+   - 比人写 prompt 提升 8% (GSM8K), 50% (Big-Bench Hard)
+ 新增: DSPy 声明式 prompt 编程 (Stanford)
+   - "Programming, not prompting" — 签名定义接口, 自动发现最优 prompt
+   - 换模型只需重新优化, 不需重写 prompt
+ 新增: AutoPDL 自动 prompt 搜索 (Salesforce)
+   - AutoML 思路搜索 prompt 空间, 9-69pp 准确率提升

### 2.6 cost_optimizer (元进化层) — 重大升级
- 现有: RouteLLM adaptive routing + response cache
+ 新增: 语义缓存层 (65x 延迟改进)
+   - N-gram 指纹 + 模糊匹配, 不仅精确匹配
+ 新增: Batch API 50% 折扣 (非实时任务)
+ 新增: Prompt Caching 90% 折扣 (重复前缀)
+ 新增: 模型蒸馏 — 80-90% 质量, 10-30% 成本
+ 新增: Output token 约束 — 每 personality 设上限
+ 修改: 路由分布优化 → 70% cheap, 20% mid, 10% premium

### 2.11 多Agent协调 (新增子节)
+ 新增: Debate-based consensus 多轮辩论协议
+   - chat/fin/coding 意见不一致时通过辩论达成共识
+ 新增: A2A 协议 (Linux Foundation, 2025.6)
+   - JSON-RPC + HTTP task model, 未来生态互操作
+ 新增: TDAG 动态子Agent生成
+   - 复杂任务自动分解为 personality-aligned 子任务
```

---

## Plan Diff #4 — Round 4 完成后

**时间:** 2026-03-28 ~23:30 UTC (Session 2)
**研究:** 24+次搜索, 重点: 安全 + 评估 + 测试

### 主计划应新增/修改的内容:

```diff
## 2. 研究增强层

### 2.5 self_edit (主动进化层) — 安全层重大升级
- 现有: AST safety check + forbidden calls/imports/paths
+ 新增: Constitutional AI 宪法约束 (7条不可覆盖原则)
+   - 运行时强制执行, 在 LLM 推理循环之外
+   - AST 安全回归检测 (try/except, logging, assert 不可减少)
+   - 网络调用白名单验证
+ 新增: Misevolution 风险缓解
+   - 核心发现: 自进化 agent 会自发安全退化
+   - 对策: 分层防御 (宪法→沙箱→回滚→监控)
+ 新增: 形式化验证路线图
+   - PSV 框架: 形式化验证信号作为进化奖励
+   - Saarthi: AI 驱动的形式化验证工程师

### 2.12 评估框架 (新增章节)
+ 新增: SWE-bench (1865 问题) 代码生成评估
+ 新增: AgentBench (8 环境) 多任务评估
+ 新增: 多维指标: Cost, Latency, Accuracy, Stability, Security
+ 新增: 持续评估 CI/CD 模式
+   - golden dataset 回归测试
+   - mutation 退化 >threshold → 自动阻断

### 2.13 测试策略 (新增章节)
+ 新增: Property-based testing (无需oracle)
+ 新增: Metamorphic testing (变异输入验证一致性)
+ 新增: Chaos engineering (agent-chaos 工具注入故障)
+ 新增: Mock LLM 单元测试 (llmock, DeepEval)
+ 新增: 自动测试生成 (Qodo 模式)

## 4. 分阶段路线图
### Phase 5 追加:
+ [ ] Constitutional constraints 集成到 self_edit ✅ (已实现)
+ [ ] 回归测试 golden dataset 建设
+ [ ] Property-based testing 框架搭建
+ [ ] Misevolution 监控指标定义
```

---

## Plan Diff #5 — Round 5 完成后

**时间:** 2026-03-28 ~23:30 UTC (Session 2, 与Round 4并行)
**研究:** 25+次搜索, 重点: 生产部署 + 监控 + 中文NLP + 韧性

### 主计划应新增/修改的内容:

```diff
## 2. 研究增强层

### 2.10 health_monitor (安全层) — 生产加固
+ 新增: 行为漂移检测 (PSI 监控)
+   - 6个月无监控 → 20-30% 性能退化风险
+   - 跟踪 LLM 输出分布 + 金融数据分布
+ 新增: 结构化日志 (JSON 格式) ✅ (已实现 structured_log.py)
+   - 双输出: 控制台可读 + JSON 文件机器解析
+   - LogContext 上下文追踪
+ 新增: 断路器模式 ✅ (已实现 circuit_breaker.py)
+   - CLOSED→OPEN→HALF_OPEN 三状态机
+   - 指数退避重试 (base=1s, max_retries=5)

### 2.14 生产部署 (新增章节)
+ 新增: Docker Compose production-ready 模式
+   - top-level `models` element for AI model declarations
+   - 不用 shared volume 做 IPC, 用 message broker
+ 新增: 零停机部署 — health check endpoint (已有 /health)
+ 新增: Graceful degradation tiers
+   - live → cache → static fallback

### 2.15 中文NLP优化 (新增章节)
+ 新增: Chinese tokenization 成本问题
+   - CJK 比 English 贵 4-5x (token 效率低)
+   - DeepSeek 原生中文优化是优势
+ 新增: 双语 prompt engineering
+   - 通用 LLM 对中文有 60%+ English bias
+   - 关键: system prompt 用英文, user context 用中文
+ 新增: DK-CoT 领域知识链式思考
+   - 提升金融情感分析准确率

### 2.16 韧性与恢复 (新增章节)
+ 新增: LLM API 1-5% 失败率应对
+   - 指数退避 1-2s base, 5-7 retries
+ 新增: SQLite 损坏恢复流程
+   - PRAGMA integrity_check ✅ (已实现)
+   - 备份自动化 + 恢复脚本
+ 新增: State checkpointing (LangGraph 模式)
+   - 决策边界保存状态, 崩溃后可恢复
+ 新增: 内存瓶颈管理
+   - tool call 导致 15.4x 内存峰值
+   - 需要 per-tool 内存监控

## 3. 集成架构
### 3.4 可观测性栈 (新增)
+   Prometheus + Grafana + Langfuse (self-hosted)
+   关键指标: 内存峰值, API延迟, 漂移指标, checkpoint频率
```

---

## 实施状态汇总

| Diff | 来自 | 高优先级项目 | 已实现 | 待实现 |
|------|------|-------------|--------|--------|
| #1 | Round 1 | sqlite-vec, LLMLingua-2, AgentSpec, Gödel Agent | 0 | 4 |
| #2 | Round 2 | Sleep-cycle, SQLite health, SIGTERM, cgroup | 2 ✅ | 2 |
| #3 | Round 3 | OPRO, 语义缓存, output约束, DSPy | 2 ✅ | 2 |
| #4 | Round 4 | Constitutional safety, 回归测试, property testing | 1 ✅ | 2 |
| #5 | Round 5 | 结构化日志, 断路器, 漂移检测, checkpointing | 2 ✅ | 2 |
| **总计** | | | **7 ✅** | **12 待实现** |
