# NeoMind Research Round 1 — 自我进化最新研究综述

> 日期: 2026-03-28
> 搜索范围: 2024-2026 论文、GitHub repos、工具
> 搜索次数: 37次 (2个并行研究代理)
> 发现: 38个独立发现

---

## 高优先级发现 (直接影响NeoMind架构)

### 1. Gödel Agent — 递归自我改进框架
- **来源:** [arxiv 2410.04444](https://arxiv.org/abs/2410.04444) | ACL 2025
- **核心:** LLM通过monkey patching动态修改自身代码和运行时内存，无需预定义routine
- **对NeoMind:** 可以增强self_edit模块，从"编辑文件→重载"升级为"运行时monkey patch→即时生效"
- **可信度:** ★★★★★ (ACL 2025收录，有GitHub实现)

### 2. Darwin Gödel Machine — 开放式进化
- **来源:** [arxiv 2505.22954](https://arxiv.org/abs/2505.22954) | Sakana AI
- **核心:** 达尔文进化 + 自修改，维护变体档案库，SWE-bench从20%→50%
- **对NeoMind:** 可以在meta_evolve中实现"进化变体池"——同时维护多个策略变体，择优选择
- **可信度:** ★★★★★ (Sakana AI支持，2025年5月)

### 3. A-Mem — Zettelkasten式智能记忆
- **来源:** [arxiv 2502.12110](https://arxiv.org/abs/2502.12110) | NeurIPS 2025
- **核心:** 动态互联知识网络，自动生成笔记+元数据+关联链接，记忆随体验持续进化
- **对NeoMind:** learnings模块可以从"扁平列表"升级为"互联知识图"——学习之间自动建立关联
- **可信度:** ★★★★★ (NeurIPS 2025收录)

### 4. AgentSpec — 安全运行时约束
- **来源:** [arxiv 2503.18666](https://arxiv.org/abs/2503.18666) | ICSE 2026
- **核心:** 轻量DSL定义运行时约束(trigger/predicate/enforcement)，90%+安全覆盖率
- **对NeoMind:** self_edit的AST安全检查可以升级为声明式约束系统
- **可信度:** ★★★★★ (ICSE 2026收录，毫秒级开销)

### 5. Mem-α — RL学习记忆管理策略
- **来源:** [arxiv 2509.25911](https://arxiv.org/abs/2509.25911)
- **核心:** 用RL训练agent自主决定存什么、怎么组织、何时更新，30K→400K+ token泛化
- **对NeoMind:** meta_evolve可以学习最优的记忆管理策略，而非手工规则
- **可信度:** ★★★★☆ (2025年9月，新颖但尚无大规模验证)

### 6. LLMLingua-2 — 20x Prompt压缩
- **来源:** [github.com/microsoft/LLMLingua](https://github.com/microsoft/LLMLingua) | ACL 2024
- **核心:** 通过蒸馏实现20x prompt压缩，3-6x比LLMLingua-1快
- **对NeoMind:** 在Context Budget Manager中加入压缩层，大幅降低API成本
- **可信度:** ★★★★★ (Microsoft，ACL收录，已有生产使用)

### 7. sqlite-vec — SQLite向量搜索
- **来源:** [github.com/asg017/sqlite-vec](https://github.com/asg017/sqlite-vec)
- **核心:** 无依赖的SQLite向量搜索扩展，K-NN查询，SIMD加速
- **对NeoMind:** 在learnings和skill_forge中加入语义搜索，不需要外部向量数据库
- **可信度:** ★★★★★ (生产就绪，活跃维护)

---

## 中优先级发现 (增强已有模块)

### 8. G-Memory — 三层图式记忆
- **来源:** [arxiv 2506.07398](https://arxiv.org/abs/2506.07398)
- **核心:** insight图/query图/interaction图三层层次结构，双向遍历
- **对NeoMind:** 可以给briefings.db增加图式结构，连接市场事件→分析→决策

### 9. Agent Behavioral Contracts — 形式化行为合约
- **来源:** [arxiv 2602.22302](https://arxiv.org/abs/2602.22302) | 2026年2月
- **核心:** Design-by-Contract (P,I,G,R) + 概率满足度，检测软约束违反
- **对NeoMind:** compliance模块可以从硬编码规则升级为形式化合约

### 10. LifelongAgentBench — 终身学习基准
- **来源:** [arxiv 2505.11942](https://arxiv.org/abs/2505.11942)
- **核心:** 发现经验回放对LLM无效；提出群体自一致性机制
- **对NeoMind:** learnings的经验回放需要改进，避免简单重复

### 11. Intrinsic Metacognitive Learning
- **来源:** [arxiv 2506.05109](https://arxiv.org/abs/2506.05109)
- **核心:** 真正的自改进需要内在元认知：自评估+策略选择+反思驱动改进
- **对NeoMind:** meta_evolve的三阶段（观察→分析→调整）与此高度吻合

### 12. ACON — 无梯度上下文压缩
- **来源:** Zylos AI, 2026年2月
- **核心:** 26-54% token减少，无需微调，梯度无关优化
- **对NeoMind:** Context Budget Manager可以集成ACON实现动态压缩

### 13. Dexter — 开源金融研究Agent
- **来源:** [github.com/virattt/dexter](https://github.com/virattt/dexter)
- **核心:** 任务规划+自反思+实时市场数据+LangSmith评估
- **对NeoMind:** fin模式可以参考其scratchpad设计和评估框架

---

## 工具/库发现 (可直接集成)

### 14. Turso — 分布式SQLite + 嵌入式副本
- **来源:** [turso.tech](https://turso.tech/)
- **核心:** 本地0.02ms读取+云同步
- **可用性:** 生产就绪，有免费层

### 15. Sqlean — SQLite标准扩展库
- **来源:** [github.com/nalgeon/sqlean](https://github.com/nalgeon/sqlean)
- **核心:** math, string, uuid, crypto, hash, json, stats, regexp扩展
- **可用性:** 生产就绪

### 16. SQLite FTS5 — 全文搜索
- **核心:** 内置，BM25排序，短语查询，可与sqlite-vec混合搜索
- **可用性:** 生产就绪（内置）

### 17. s6-overlay — 轻量进程管理
- **来源:** [github.com/just-containers/s6-overlay](https://github.com/just-containers/s6-overlay)
- **核心:** 容器原生PID 1，优雅关闭，进程依赖
- **可用性:** 生产就绪（计划中已有迁移方案）

### 18. Claude Batch API + Prompt Caching
- **核心:** Batch=50%折扣，Prompt Caching=90%折扣，可叠加95%节省
- **对NeoMind:** evolution任务使用batch API，system prompt使用缓存

---

## 对NeoMind计划的建议更新

### 立即可用 (无需额外研究)
1. **sqlite-vec** → 在learnings.db和skills.db中加入向量搜索列
2. **FTS5** → 在news_data.db中启用全文搜索
3. **LLMLingua-2** → 在Context Budget Manager中加入可选压缩层
4. **Batch API pricing** → cost_optimizer考虑batch模式

### 短期 (1-2周研究+实现)
5. **A-Mem Zettelkasten** → learnings模块升级为互联知识图
6. **AgentSpec** → self_edit安全检查升级为声明式约束
7. **Gödel Agent monkey patching** → self_edit增加运行时热修复选项

### 中期 (1-2月)
8. **Darwin Gödel Machine** → meta_evolve增加变体池+择优进化
9. **Mem-α RL** → 学习最优记忆管理策略
10. **s6-overlay迁移** → 替换supervisord

---

## 待下一轮验证的问题
1. Gödel Agent的monkey patching在Docker Python进程中的稳定性？
2. sqlite-vec的内存占用在大量向量(10万+)下的表现？
3. LLMLingua-2在中文文本上的压缩效果？
4. A-Mem的Zettelkasten结构与现有SQLite schema的兼容性？
