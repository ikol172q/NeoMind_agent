# NeoMind 自我进化战略研究报告 v2 (完整版)

> 日期: 2026-03-28
> 版本: v2.0 — 经过 5 轮深度搜索后的完整版本
> 参考: 50+ 框架/论文/项目的深度分析
> 目标: 为 NeoMind 设计适合自身特点的自我进化体系

---

## 一、现状诊断：NeoMind 当前进化能力

### 1.1 已有模块

| 模块 | 文件 | 能力 | 局限性 |
|------|------|------|--------|
| AutoEvolve | `auto_evolve.py` (763行) | 启动健康检查、每日审计、每周回顾 | 仅统计+正则匹配，无深度学习 |
| Upgrade | `upgrade.py` (264行) | git pull + 回滚 | 只能拉取人工推送的更新，无自主代码生成 |
| Scheduler | `scheduler.py` (188行) | 会话生命周期调度 | 仅触发已有任务，无法调度新发现的任务 |
| Dashboard | `dashboard.py` (556行) | HTML可视化 | 仅展示，无分析结论生成 |
| SharedMemory | `shared_memory.py` (609行) | 跨模式记忆存储 | 无遗忘策略、无向量检索、无语义理解 |

### 1.2 关键差距 (6 层)

```
NeoMind 当前                          →    业界前沿 (2026)
─────────────────────────────────────────────────────────────
1. 正则模式匹配 (regex)              →    LLM驱动语义理解 + PRM评分
2. 静态偏好记录                      →    动态技能库 + Living Skills
3. 拉取式更新 (git pull)             →    自主代码生成 + 沙箱测试
4. 单层记忆 (SQLite flat)            →    三层认知记忆 + 遗忘曲线
5. 无自我反思                        →    Reflexion + LATS + 5-Why
6. 无多Agent协作                     →    Proposer-Solver 共进化
```

---

## 二、OpenClaw 自我进化机制 (深度拆解)

### 2.1 Self-Improve Skill 实现细节

**仓库:** https://github.com/peterskoett/self-improving-agent

**技术栈:** Shell (67.6%) + TypeScript (17.4%) + JavaScript (15%)

**LEARNINGS.md 条目格式 (精确):**
```markdown
## [LRN-YYYYMMDD-XXX] category

**Logged**: 2026-03-28T10:30:00Z
**Priority**: low | medium | high | critical
**Status**: pending | in_progress | resolved | won't_fix | promoted
**Area**: frontend | backend | infra | tests | docs | config

### Summary
一行描述学到了什么

### Details
完整上下文：发生了什么、哪里错了、正确做法是什么

### Suggested Action
具体的修复或改进动作

### Metadata
- Source: conversation | error | user_feedback
- Related Files: path/to/file.ext
- Tags: tag1, tag2
- Pattern-Key: simplify.dead_code | harden.input_validation
- Recurrence-Count: 1
- First-Seen: 2025-01-15
- Last-Seen: 2025-01-15
```

**学习晋升机制 (Promotion):**
- `Recurrence-Count ≥ 3` 且跨 `2+ tasks` 且在 `30天内` → 自动晋升
- 晋升目标: CLAUDE.md (项目事实) / AGENTS.md (工作流) / SOUL.md (行为准则)

**Hook 机制:**
- `UserPromptSubmit` — 用户提交消息前触发
- `PostToolUse (Bash)` — 工具执行后检测命令错误

### 2.2 Foundry ("Agent 构建 Agent")

**仓库:** https://github.com/lekt9/openclaw-foundry

**模式固化算法:**
```
对每个观察到的工作流:
1. 记录: Goal + Tool序列 + 成功/失败 + 耗时 + 关键词
2. 统计: 使用次数 和 成功率
3. 判断:
   - < 5次使用 → 继续观察
   - 5次+ 且 50-69% 成功率 → 监控改进
   - 5次+ 且 ≥ 70% 成功率 → 触发固化 (Crystallization)
4. 固化过程:
   a. 分析文档和模式
   b. 生成 AgentSkills 格式代码 (YAML前置 + 代码)
   c. 在隔离 Node.js 沙箱中验证
   d. 安全扫描 (禁止 shell执行/eval/凭证访问)
   e. 部署 (保持会话上下文)
```

### 2.3 OpenClaw 记忆系统

**文件结构:**
```
~/.openclaw/workspace/
├── MEMORY.md          # 长期持久知识 (决策、偏好、事实)
├── SOUL.md            # 人格、价值观、行为边界
├── AGENTS.md          # 工作流自动化规则
├── TOOLS.md           # 可用工具和使用说明
├── USER.md            # 用户偏好和上下文
├── IDENTITY.md        # Agent身份规范
├── HEARTBEAT.md       # 会话生命周期管理
├── memory/
│   ├── 2026-03-28.md  # 每日会话日志
│   └── ...
└── .learnings/
    ├── LEARNINGS.md
    ├── ERRORS.md
    └── FEATURE_REQUESTS.md
```

**记忆搜索:**
- **混合搜索**: 向量搜索 (语义匹配) + BM25 (精确关键词)
- **RRF (Reciprocal Rank Fusion)** 合并两种结果
- 推荐嵌入: ONNX bge-m3 int8 (本地，无需API)

**自动记忆刷新 (上下文窗口即将满时):**
1. 触发静默Agent轮次
2. 提示模型将重要信息写入 MEMORY.md
3. 然后执行上下文压缩

**Token 预算控制:**
- 每文件上限: `bootstrapMaxChars = 20000`
- 总上限: `bootstrapTotalMaxChars = 150000`
- 超大文件自动截断

### 2.4 Evolver (GEP — 基因组进化协议)

**仓库:** https://github.com/EvoMap/evolver

**核心资产:**
```
assets/gep/
├── genes.json      # 可复用基因定义 (含修复逻辑)
├── capsules.json   # 成功胶囊 (防止重复推理)
└── events.jsonl    # 追加式进化事件日志 (树状结构)
```

**GEP 协议输出 (严格5个JSON对象):**
```
Mutation → PersonalityState → EvolutionEvent → Capsule → FilePatches
```

**进化策略 (EVOLVE_STRATEGY):**
- `balanced` / `innovate` / `harden` / `repair-only` / `early-stabilize` / `steady-state` / `auto`

**安全机制:**
- 单进程逻辑防止无限递归
- `EVOLVE_ALLOW_SELF_MODIFY = false` (生产环境默认)
- 回滚模式: `hard` / `stash` / `none`

### 2.5 OpenClaw-RL (强化学习)

**核心创新:** 从自然对话中提取训练信号

**两类信号:**
1. **评价信号 (Evaluative):** PRM Judge 实时评分 → 标量奖励
2. **指导信号 (Directive):** Hindsight-Guided On-Policy Distillation (OPD) → token级优势监督

**OPD 过程:**
```
1. Judge 评估 response + next-state 的事后有用性
2. 多次 Judge 投票 (+1/-1 + 可选提示)
3. 保留最长有效提示
4. 将提示附加到 prompt 中查询教师对数概率
→ token级优势监督 (比标量奖励更丰富)
```

**成本:** 36次解题交互 + 24次教学交互即可见到明显改进

### 2.6 Self-Evolve.club

**核心数据格式:** Intent-Experience Triplet `(意图, 经验, 嵌入)`

**进化循环:**
1. 观察对话和反馈信号
2. 总结为可复用的 intent-experience 三元组
3. 使用 value-aware 排名存储/检索 (本地+远程)
4. 报告归因反馈 (贡献者获得改进)

**知识共享:** 匿名三元组共享，通过影响力指标识别顶级贡献者

---

## 三、全球自我进化Agent框架扫描 (50+ 项目)

### 3.1 反思与自我纠错

| 框架 | 核心机制 | 关键数据 | NeoMind 可用 |
|------|---------|---------|-------------|
| **Reflexion** | 语言强化学习: Actor+Evaluator+Self-Reflection → 情景记忆缓冲 | HumanEval 91% pass@1 (超GPT-4的80%) | 反思记忆存储 |
| **Self-Refine** | Generate→Feedback→Refine 循环 (同一LLM) | 7个任务上平均+20%绝对提升 | 无外部反馈的迭代优化 |
| **LATS** | Monte Carlo Tree Search + LLM价值函数 + 反思引导 | HumanEval 92.7% pass@1 | 树搜索决策 |
| **ExpeL** | 经验提取: 成功轨迹→Faiss向量存储→k-NN检索 | 跨任务经验迁移 | 经验库设计 |

**Reflexion 实现细节:**
```
循环:
1. Actor 生成动作/文本
2. Evaluator 评分
3. Self-Reflection 模型生成语言反馈 ("语义梯度信号")
4. 反馈存入情景记忆缓冲
5. 下次尝试时检索相似过去任务的反思
→ 无需LLM微调，轻量级实现
→ 通常 2-5 轮反思有效，之后收益递减
```

**Self-Refine 停止条件:**
- 固定迭代上限 (3-5轮)
- 质量平台检测 (改进幅度递减)
- 反馈模块的置信度评分
- 任务特定的完成标准

### 3.2 技能库系统

| 框架 | 核心机制 | 关键数据 | NeoMind 可用 |
|------|---------|---------|-------------|
| **VOYAGER** | JS代码+描述+向量索引→语义检索top-5 | 3重反馈循环 (环境+错误+自验证) | 技能存储格式 |
| **SkillRL** | 双层SkillBank (通用+专用) + 递归进化 | +15.3%基线, 10-20x token压缩 | 技能共进化 |
| **OpenSpace** | Living Skills: Select→Apply→Monitor→Evolve | 4.2×收入提升, 46% token减少 | 技能生命周期 |
| **CRADLE** | 从视频示范中提取技能 | 跨4游戏+5软件 | 技能提取 |
| **Anthropic Skills** | SKILL.md 开放标准 + 渐进式披露 | 17技能仅~1700 tokens | 标准格式 |

**VOYAGER 技能库存储格式:**
```
skill_library/
├── code/
│   ├── catchThreeFishWithCheck.js
│   └── collectBamboo.js
├── descriptions/
│   ├── catchThreeFishWithCheck.txt
│   └── collectBamboo.txt
├── skills.json            # 索引清单
└── vectordb/              # 嵌入索引
```

**VOYAGER 三重反馈循环:**
1. **环境反馈:** 进度报告 ("还需要7个铁锭")
2. **执行错误:** 语法/运行时错误
3. **自验证:** 另一个GPT-4实例评判任务是否成功
   → 移除自验证 = **73%性能下降** (最关键的反馈)

**Anthropic Skills 渐进式披露 (Token效率):**
```
Stage 1 (Advertise): 仅 name + description → ~100 tokens/skill
Stage 2 (Load): 完整 SKILL.md → ~5K tokens max
Stage 3 (Read): 按需加载补充文件
→ 17个技能总计仅 ~1,700 tokens (未使用的零开销)
```

**OpenSpace 三种进化模式:**
1. **FIX**: 分析录像，为相关技能建议改进
2. **DERIVED**: 从父技能创建增强变体
3. **CAPTURED**: 从成功执行中提取新模式作为新技能

**OpenSpace 健康指标触发器:**
- 应用率、完成率、回退率、执行成功率
- 三种独立进化触发: 执行后分析 / 工具退化检测 / 指标监控

**SkillsBench 基准测试 (重要发现):**
- 精选技能提升 pass rate +16.2个百分点
- 领域差异: +4.5pp (软件) 到 +51.9pp (医疗)
- **自生成技能无平均收益** (模型不能可靠地自己编写技能)
- 最佳公式: 2-3个聚焦模块 > 综合文档

### 3.3 记忆系统

| 系统 | 核心架构 | 关键创新 | NeoMind 可用 |
|------|---------|---------|-------------|
| **ReMe** | 文件+向量双存储 + 混合检索 | 70%阈值触发压缩, 效用剪枝 | 压缩策略 |
| **A-MEM** | Zettelkasten知识网络 | 自主记忆创建+动态链接 (NeurIPS 2025) | 知识图谱 |
| **Letta/MemGPT** | In-Context/Archival/Recall 三层 | Agent自编辑记忆 | 虚拟上下文管理 |
| **Zep/Graphiti** | 时序知识图谱 | 双时间模型 (事件时间+摄入时间) | 时序记忆 |
| **Mem0** | 通用记忆层 | 2阶段提取+更新, 91%延迟降低 | 记忆衰减 |
| **MIRIX** | 6组件 (Core/Episodic/Semantic/Procedural/Resource/Vault) | 多模态, ScreenshotVQA +35% | 模块化记忆 |
| **GitHub Copilot Memory** | 代码感知引用存储 | JIT验证: 访问时实时验证引用 | 验证机制 |

**ReMe 压缩触发条件:**
```python
# 当上下文超过最大输入长度的70%时触发
if context_tokens > max_input_length * 0.7:  # compact_ratio
    # 效用剪枝:
    # f(E) = 检索频率
    # u(E) = 历史效用
    if f(E) > threshold_α and u(E)/f(E) < threshold_β:
        compress_or_remove(E)
```

**Letta/MemGPT 三层记忆 API:**
```python
archival_memory_insert(data)       # 写入长期存档
archival_memory_search(query)      # 语义检索存档
recall_memory_search(query, date)  # 搜索对话历史
```

**Zep 三层知识图谱:**
1. **Episode Subgraph**: 原始输入 (消息/文本/JSON) — 无损数据存储
2. **Semantic Entity Subgraph**: 提取的实体和关系
3. **Community Subgraph**: 强连接实体的高级摘要

**MIRIX 六组件架构:**
```
Core Memory     → 持久Agent/用户信息 (人格、偏好)
Episodic Memory → 时间戳事件 (event_type, summary, actors)
Semantic Memory → 抽象概念和知识图谱
Procedural Memory → 技能和程序
Resource Memory → 工具/API访问信息
Knowledge Vault → 通用知识存储
+ Meta Memory Manager → 路由和协调
```

**记忆遗忘公式 (Ebbinghaus):**
```python
strength = importance * math.exp(-λ_eff * days_since) * (1 + recall_count * 0.2)
# 67% 的内容在24小时内遗忘 (无复习)
# recall_count 增加 → 衰减更慢
```

**混合检索最佳实践:**
```python
# 向量搜索 (语义) + BM25 (精确) + 交叉编码器重排
final_score = 0.6 * cross_encoder_score + 0.4 * hybrid_fusion_score
# 其中 hybrid_fusion = 0.7 * vector_score + 0.3 * bm25_score
# 推荐重排器: Jina Reranker v3
```

### 3.4 根因分析与故障归因

| 框架 | 方法 | 核心创新 |
|------|------|---------|
| **CHIEF** | 因果DAG + 层次回溯 | 扁平日志→有向无环图, 区分根因vs传播症状 |
| **RCAgent** | 语言推理 + 工具调用 | 观察键值存储, 专家Agent调用 |
| **FVDebug** | 形式验证 + 因果图 | 批量LLM分析 + 正反论证 |
| **AgentEvolver Self-Attributing** | 差异化奖励归因 | 步骤级因果贡献 → 加速收敛50%+ |

**CHIEF 实现流程:**
```
1. 收集执行轨迹 (所有决策/状态)
2. 从轨迹提取因果关系
3. 构建组件交互DAG
4. Oracle引导回溯定位失败源
5. 通过反事实场景验证归因
6. 生成人类可读的失败解释
```

### 3.5 共进化与自我对弈

| 框架 | 机制 | 效果 |
|------|------|------|
| **Agent0** | 课程Agent ⇄ 执行Agent (共生竞争) | 数学推理+18%, 通用推理+24%, 零外部数据 |
| **MAE** | Proposer→Solver→Judge 对抗反馈 | 多角色共进化 |
| **SAGE** | Challenger+Planner+Solver+Critic 四Agent | 协作+对抗动态 |
| **MAD** | 多Agent辩论 (解决"思维退化") | 迫使重新评估初始立场 |

**Agent0 共生竞争循环:**
```
1. 课程Agent 根据执行者当前能力生成任务
2. 执行者尝试任务 (使用代码解释器等工具)
3. 执行者的不确定性 (多答案采样方差) 信号化难度
4. 工具使用频率指示问题复杂度
5. 两个信号训练课程Agent生成适当难度的任务
6. 执行者从解决的任务中学习
7. 改进的执行者迫使课程提出更难的任务
→ 正反馈飞轮: 零外部数据实现持续进化
```

### 3.6 安全与治理

| 框架 | 核心机制 |
|------|---------|
| **NemoClaw (NVIDIA)** | Landlock + seccomp + 网络命名空间隔离; /sandbox和/tmp限制; 出站过滤 |
| **SafeAgents (Microsoft)** | ARIA风险评估 + DHARMA漏洞检测; AgentHarm基准 (110行为,11伤害类) |
| **AGENTSAFE** | MIT AI风险仓库 → 技术/组织保障映射; plan→act→observe→reflect 循环分析 |
| **Constitutional AI** | 自我批评+修订 → RLAIF (AI反馈的RL); 无需人工标注有害输出 |

**NemoClaw 沙箱层:**
```
Layer 1: Landlock — 文件系统访问控制 (仅 /sandbox, /tmp)
Layer 2: seccomp — 系统调用过滤
Layer 3: Network Namespacing — 出站连接过滤
Layer 4: Skill Verification — Agent学到的工具使用前验证
```

### 3.7 可观测性与度量

| 工具 | 特点 |
|------|------|
| **LangSmith** | 托管SaaS, 深度LangChain集成, ~0%开销, 自定义仪表板 |
| **Langfuse** | 开源MIT, OpenTelemetry原生, ~15%开销, 支持自托管 |
| **W&B Weave** | 接受OTLP数据, 追踪推理步骤/工具选择/决策树 |
| **OpenTelemetry GenAI SIG** | 标准化属性: ai.agent.id, ai.agent.tool, ai.model.name |

### 3.8 成本优化

| 策略 | 节省 |
|------|------|
| **Batch API** | 50% vs 实时调用 |
| **缓存** | 75-90%输入成本 + 90%延迟降低 |
| **动态轮次限制** | 24%成本削减 (5步CoT ≈ 10x直接回答的tokens) |
| **批量反思** | 30-50% (合并相似反思请求) |
| **模型路由** | 80%轻量模型 + 20%高级模型 |
| **EvoPrompt 自动优化** | 36.9% token减少 |

**Q1 2026 API定价:**
- 输入 tokens: ~$3/1M (自GPT-4发布以来下降85%)
- 输出 tokens: 3-5x更贵 (Agent系统的主要成本驱动)
- 启示: 最小化输出密集型模式, 优先输入缓存

---

## 四、NeoMind 五层进化架构 (详细设计)

### 架构总览

```
╔══════════════════════════════════════════════════════════════════╗
║                  NeoMind Evolution Stack v2                      ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  L5  Meta-Evolution (进化的进化)                                 ║
║      • A/B测试进化策略 • 进化效率度量 • 自动调参                   ║
║      ↑ 灵感: Agent0共进化 + EvoPrompt种群优化                     ║
║                                                                  ║
║  L4  Skill Forge (技能锻造)                                      ║
║      • 高频模式→新技能 • 技能生命周期 • 技能组合/退化             ║
║      ↑ 灵感: VOYAGER + Foundry + OpenSpace Living Skills          ║
║                                                                  ║
║  L3  Reflection Engine (反思引擎)                                 ║
║      • 即时反思 • 会话反思 • 周度深度反思 • 5-Why根因分析          ║
║      ↑ 灵感: Reflexion + Self-Refine + CHIEF因果DAG               ║
║                                                                  ║
║  L2  Adaptive Memory (自适应记忆)                                 ║
║      • 工作/情景/语义三层 • Ebbinghaus遗忘 • 混合检索              ║
║      ↑ 灵感: Letta三层 + Zep时序图谱 + MIRIX六组件                ║
║                                                                  ║
║  L1  Observation Layer (观测层) [增强]                             ║
║      • 工具调用追踪 • 满意度信号 • 性能异常检测                    ║
║      ↑ 灵感: OpenClaw Hooks + OpenTelemetry标准                   ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

### L1: Observation Layer (观测层) — 增强

**新增文件:** `agent/evolution/observer.py`

```python
class ExecutionObserver:
    """增强版观测器

    灵感: OpenClaw PostToolUse Hook + OpenTelemetry GenAI SIG
    """

    def observe_tool_call(self, tool_name, input_args, output,
                          duration_ms, success, error_msg=None):
        """记录每次工具调用 (类似 OpenTelemetry span)"""
        entry = {
            "ts": now_iso(),
            "tool": tool_name,
            "input_hash": sha256(input_args)[:16],  # 隐私保护
            "output_preview": output[:200],
            "duration_ms": duration_ms,
            "success": success,
            "error": error_msg,
            "mode": current_mode(),
            "turn": current_turn(),
            # OpenTelemetry 标准属性
            "ai.agent.id": agent_id(),
            "ai.model.name": model_name(),
        }
        self._append_to_trail(entry)

        # 实时异常检测
        if not success:
            self._record_failure_pattern(tool_name, error_msg)
        if duration_ms > self._get_tool_p95(tool_name):
            self._record_slow_execution(tool_name, duration_ms)

    def observe_user_satisfaction(self, user_msg, bot_response, next_user_msg):
        """检测满意度信号 (灵感: OpenClaw-RL 的 next-state signal)"""
        signals = self._classify_signals(next_user_msg)
        # positive / negative / retry / clarification / topic_change
        if signals["negative"]:
            self._trigger_immediate_reflection(user_msg, bot_response, signals)

    def observe_session_lifecycle(self, event_type):
        """会话生命周期事件 (灵感: OpenClaw HEARTBEAT.md)"""
        # session_start / turn_complete / session_end / context_approaching_limit
        pass
```

**与现有系统集成:**
- Hook 到 `core.py` 的工具调用循环
- 数据写入 evidence trail (已有) + 新的 observation_log.jsonl
- 零性能影响: 异步写入，不阻塞主循环

---

### L2: Adaptive Memory (自适应记忆) — 重构

**新增文件:** `agent/memory/adaptive_memory.py`

```python
class AdaptiveMemory:
    """三层自适应记忆

    灵感:
    - Letta/MemGPT: In-Context + Archival + Recall 三层
    - MIRIX: 六组件模块化 (我们简化为三层+路由)
    - ReMe: 效用剪枝 (f(E) > α AND u(E)/f(E) < β)
    - Zep/Graphiti: 双时间模型
    - Ebbinghaus: 遗忘曲线 + 间隔重复
    """

    def __init__(self):
        self.working = WorkingMemory(capacity=20)
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        self.router = MemoryRouter()  # 灵感: MIRIX Meta Memory Manager

    class WorkingMemory:
        """当前会话活跃上下文 (灵感: Letta in-context memory)

        - LRU淘汰, 容量上限
        - Agent可自编辑 (灵感: Letta self-edit)
        - 会话结束时: 重要项→Episodic, 其余丢弃
        """
        pass

    class EpisodicMemory:
        """事件记忆 (灵感: MIRIX Episodic + Zep Episode Subgraph)

        存储格式: {
            event_type, summary, details, actors,
            timestamp_event,      # 事件时间 (Zep Timeline T)
            timestamp_ingestion,  # 摄入时间 (Zep Timeline T')
            source_mode,
            strength,  # Ebbinghaus 衰减值
            recall_count,
        }

        衰减: strength = importance * e^(-λ * days) * (1 + recall_count * 0.2)
        压缩触发: context_tokens > max_input * 0.7 (ReMe compact_ratio)
        效用剪枝: f(E) > α AND u(E)/f(E) < β → 压缩或删除
        """
        pass

    class SemanticMemory:
        """语义记忆 (灵感: A-MEM Zettelkasten + MIRIX Semantic)

        从情景记忆提炼的稳定知识:
        - 同类事件 3次+ → 自动提炼
        - 用户确认 → 直接写入
        - 矛盾知识 → 保留最新, 标记冲突

        检索: 混合搜索 (BM25 + 向量) + RRF融合
        链接: A-MEM 式动态双向链接
        """
        pass

    class MemoryRouter:
        """记忆路由器 (灵感: MIRIX Meta Memory Manager)

        - 根据查询类型路由到最合适的记忆层
        - 精确查询 (名字, 错误码) → BM25 优先
        - 语义查询 (概念, 主题) → 向量优先
        - 时间查询 (最近, 昨天) → 时间索引优先
        """
        pass
```

**结构化学习输出 (借鉴 OpenClaw):**
```
~/.neomind/evolution/
├── LEARNINGS.md        # 结构化学习记录 (OpenClaw LRN格式)
├── ERRORS.md           # 错误模式追踪
├── FEATURE_REQUESTS.md # 用户暗示的能力需求
├── evolution_state.json
├── feedback.db
├── learning.jsonl
└── retro-*.md
```

**向后兼容:** SharedMemory → SemanticMemory 适配器

---

### L3: Reflection Engine (反思引擎) — 全新

**新增文件:** `agent/evolution/reflection.py`

```python
class ReflectionEngine:
    """三模式反思引擎

    灵感:
    - Reflexion: 语言强化学习 (情景记忆缓冲)
    - Self-Refine: Generate→Feedback→Refine (同一LLM)
    - CHIEF: 因果DAG + 层次回溯
    - AgentEvolver: 差异化奖励归因
    """

    # ── 模式1: 即时反思 (不调LLM, <10ms) ──
    def reflect_instant(self, tool_call, result, user_reaction):
        """规则引擎快速反思

        检测:
        - 工具失败 → 记录错误模式
        - 超时 (>p95) → 记录慢模式
        - 用户重试 → 记录不满信号
        - 用户纠正 → 直接学习
        """
        pass

    # ── 模式2: 会话反思 (调用LLM, 会话结束时) ──
    def reflect_session(self, session_log):
        """会话级反思 (灵感: Reflexion verbal reinforcement)

        流程:
        1. 收集会话中所有工具调用和用户反馈
        2. 调用便宜模型 (deepseek-chat) 生成反思
        3. 提取: successes / failures / root_causes / improvements
        4. 存入情景记忆缓冲 (Reflexion episodic buffer)
        5. 写入 LEARNINGS.md / ERRORS.md

        成本控制:
        - 使用最便宜模型
        - 每天最多 5 次
        - 输入摘要 (非完整会话) 以节省 tokens
        """
        pass

    # ── 模式3: 深度反思 (每周, 调用LLM) ──
    def reflect_deep(self, week_data):
        """周级因果分析 (灵感: CHIEF因果DAG)

        步骤:
        1. 收集一周所有失败事件
        2. 构建因果DAG (扁平日志→有向无环图)
        3. Oracle引导回溯定位根因
        4. 5-Why分析 (递归追问)
        5. 反事实验证 (如果当初做X会怎样)
        6. 生成改进目标 (含可测量指标)

        输出: LEARNINGS.md + ERRORS.md + FEATURE_REQUESTS.md
        """
        pass

    # ── Self-Refine 循环 ──
    def self_refine(self, output, max_rounds=3):
        """迭代自我改进 (灵感: Self-Refine)

        Generate → Feedback → Refine
        停止条件: 改进幅度 < threshold 或达到 max_rounds
        """
        for round in range(max_rounds):
            feedback = self._generate_feedback(output)
            if feedback["improvement_magnitude"] < 0.1:
                break  # 收益递减, 停止
            output = self._refine(output, feedback)
        return output

    # ── 5-Why 根因分析 ──
    def five_why(self, failure_event):
        """递归5-Why (灵感: CHIEF + AgentEvolver Self-Attributing)

        Example:
        Why1: 搜索返回空结果
        Why2: 关键词过于宽泛
        Why3: 用户意图理解不准确
        Why4: 缺少领域知识上下文
        Why5: 没有利用历史搜索记录
        → Root Cause: 搜索前未注入历史成功搜索模式
        → Action: 搜索前自动注入 top-3 历史成功搜索词
        → Metric: 搜索空结果率从 X% 降至 Y%
        """
        pass

    # ── 元认知评估 ──
    def assess_confidence(self, task, proposed_action):
        """元认知: 评估自身能力和信心 (灵感: Meta-Cognition研究)

        5维状态向量:
        1. correctness_estimate: 正确性自评
        2. confidence_level: 置信度
        3. anomaly_detected: 是否检测到异常
        4. reasoning_quality: 推理质量自评
        5. knowledge_boundary: 是否触及知识边界

        低置信度 → 请求帮助或降级处理
        """
        pass
```

---

### L4: Skill Forge (技能锻造) — 全新

**新增文件:** `agent/evolution/skill_forge.py`

```python
class SkillForge:
    """技能锻造引擎

    灵感:
    - VOYAGER: 技能库 (JS代码 + 描述 + 向量索引)
    - Foundry: 70%+成功率固化 + 安全扫描
    - OpenSpace: Living Skills (Select→Apply→Monitor→Evolve)
    - Anthropic Skills: SKILL.md 渐进式披露
    - SkillRL: 技能与策略共进化
    - SkillsBench: 精选2-3模块 > 综合文档

    关键发现 (SkillsBench):
    - 精选技能 → +16.2pp pass rate
    - 自生成技能 → 无平均收益
    - 因此我们采用 "人工验证 + 模式提取" 而非纯自动生成
    """

    CRYSTALLIZATION_THRESHOLD = {
        "min_uses": 5,        # 灵感: Foundry
        "min_success_rate": 0.70,  # 灵感: Foundry 70%
    }

    # ── 技能发现 ──
    def detect_candidates(self, recent_sessions):
        """从最近会话中发现技能候选

        触发条件 (灵感: Foundry pattern detection):
        1. 相同命令序列出现 3+ 次
        2. 某模式成功率 > 80%
        3. 用户对复杂操作结果持续满意
        """
        pass

    # ── 技能锻造 ──
    def forge(self, pattern, examples):
        """锻造技能 (灵感: Foundry code generation)

        过程:
        1. 提取模式核心步骤
        2. 参数化可变部分
        3. 生成 SKILL.md (Anthropic格式) + Python代码
        4. 生成测试用例
        5. 沙箱执行测试 (灵感: NemoClaw Landlock隔离)
        6. 安全扫描 (禁止: shell执行/eval/凭证访问)
        7. 成功 → 注册为 Prototype 状态

        安全约束 (灵感: NemoClaw + Foundry):
        - Landlock风格文件系统限制
        - 不允许网络请求 (除白名单)
        - 不允许文件删除
        - 不允许修改 .env 或进化引擎自身代码
        """
        pass

    # ── 技能进化 ──
    def evolve(self, skill_name, feedback):
        """进化已有技能 (灵感: OpenSpace三种进化模式)

        FIX: 分析失败, 建议改进
        DERIVED: 创建增强变体
        CAPTURED: 从新的成功执行中提取模式
        """
        pass

    # ── 技能退化 ──
    def deprecate(self, skill_name):
        """退化/下线 (灵感: OpenSpace health metrics)

        触发:
        - 30天未使用
        - 成功率 < 50%
        - 被更好技能替代
        """
        pass

    # ── 技能检索 ──
    def retrieve(self, task_description, top_k=5):
        """语义检索最相关技能 (灵感: VOYAGER vectordb)

        Anthropic渐进式披露:
        1. 匹配技能名+描述 (快速, ~100 tokens)
        2. 命中 → 加载完整 SKILL.md (~5K tokens)
        3. 需要 → 加载补充文件
        """
        pass
```

**技能存储格式 (融合 Anthropic + VOYAGER + OpenClaw):**
```yaml
# ~/.neomind/skills/active/smart_search/SKILL.md
---
name: smart_search
version: "1.2.0"
status: active  # prototype/testing/active/mature/deprecated
description: "基于历史搜索模式的智能搜索"
trigger_patterns: ["搜索", "search", "查找"]
metadata:
  created_at: "2026-03-15"
  last_used: "2026-03-28"
  total_calls: 42
  success_rate: 0.88
  avg_duration_ms: 350
  lineage:
    parent: null
    evolved_from_pattern: "user_search_retry_pattern"
---

## 使用步骤
1. 分析用户搜索意图
2. 注入历史成功搜索词 (top-3)
3. 执行多轮搜索 (中文→英文→混合)
4. 合并去重结果

## 约束
- 单次搜索超时: 10s
- 最多重试: 3次
```

**技能目录:**
```
~/.neomind/skills/
├── registry.json        # 所有技能索引
├── active/              # 活跃技能
│   └── smart_search/
│       ├── SKILL.md
│       ├── code.py
│       └── test.py
├── prototype/           # 试验中
├── deprecated/          # 已废弃
├── vectordb/            # 技能嵌入索引 (灵感: VOYAGER)
└── lineage.json         # 进化谱系图
```

---

### L5: Meta-Evolution (元进化) — 长期目标

**新增文件:** `agent/evolution/meta.py`

```python
class MetaEvolution:
    """进化策略本身的进化

    灵感:
    - Agent0: 课程-执行共进化
    - EvoPrompt: 种群进化 (GA + DE)
    - OpenClaw-RL: 从交互中提取训练信号
    - A/B Testing: Bayesian hierarchical model
    """

    def evaluate_evolution_effectiveness(self):
        """度量进化是否真的有帮助

        指标:
        - 新技能采纳率 (被用户实际使用的%)
        - 反思建议落地率
        - 同类错误复发率 (应下降)
        - 用户满意度趋势
        - 进化消耗的 tokens vs 节省的 tokens
        """
        pass

    def ab_test_strategy(self, strategy_a, strategy_b, metric):
        """A/B测试两种进化策略

        方法: 分层Bayesian模型
        (灵感: Parloa agent A/B testing)

        考虑:
        - 确定性指标 (完成率, 延迟)
        - LLM-judge 评分
        - 跨任务类型和用户群体的差异
        """
        pass

    def self_questioning(self):
        """好奇心驱动的自主探索 (灵感: AgentEvolver)

        Agent主动给自己出题:
        1. 识别当前能力边界
        2. 生成边界附近的挑战任务
        3. 尝试解决 → 成功则拓展能力边界
        4. 失败则记录为学习机会

        内在动机公式:
        intrinsic_reward = |expected_outcome - actual_outcome|
        高预测误差 → 高好奇心 → 优先探索
        """
        pass
```

---

## 五、实施路线图 (修订版)

### Phase 5A: 反思闭环 (2周) — 最高优先级

```
Week 1:
├── 实现 ExecutionObserver (L1增强)
│   ├── 工具调用追踪 (tool_call span格式)
│   ├── 满意度信号检测
│   └── 性能异常检测 (p95阈值)
├── 实现即时反思 (规则引擎, 不调LLM)
└── 实现 LEARNINGS.md / ERRORS.md 结构化输出 (OpenClaw格式)

Week 2:
├── 实现会话级反思 (Reflexion verbal reinforcement)
│   ├── 调用 deepseek-chat 生成反思
│   ├── 情景记忆缓冲存储
│   └── 每天5次限制
├── 实现 5-Why 根因分析
├── 实现 Self-Refine 循环 (3轮, 收益递减停止)
└── 将反思结果注入 system prompt
```

**验收标准:**
- 同类错误复发率下降 30%+
- `/evolve learnings` 命令可查看结构化学习
- 反思消耗 < $0.10/天

### Phase 5B: 自适应记忆 (2周)

```
Week 3:
├── 实现三层记忆架构 (Working/Episodic/Semantic)
├── 实现 MemoryRouter (精确/语义/时间查询路由)
├── 迁移 SharedMemory 数据到新架构
└── 实现 Ebbinghaus 遗忘曲线

Week 4:
├── 实现情景→语义知识提炼 (3次+自动提炼)
├── 实现 ReMe 效用剪枝 (f(E) > α AND u(E)/f(E) < β)
├── 实现混合检索 (BM25 + 向量 + RRF融合)
│   └── 默认使用 ONNX bge-m3 int8 (本地, 无API)
└── 记忆容量监控和自动清理
```

**验收标准:**
- 记忆使用量稳定在合理范围 (不无限增长)
- 跨模式知识检索延迟 < 100ms
- 旧记忆自然衰减, 重要记忆保持

### Phase 5C: 技能锻造 (3周)

```
Week 5:
├── 实现技能存储格式 (SKILL.md Anthropic标准)
├── 实现技能注册表和目录结构
├── 实现技能候选检测 (Foundry模式: 5次+, 70%+)
└── 实现渐进式披露 (Advertise→Load→Read)

Week 6:
├── 实现技能代码生成 (Python函数)
├── 实现沙箱测试执行 (受限环境)
├── 实现安全扫描 (禁止危险操作)
└── 实现技能触发和语义检索 (向量索引)

Week 7:
├── 实现 OpenSpace 三种进化模式 (FIX/DERIVED/CAPTURED)
├── 实现技能退化机制 (30天未用/成功率<50%)
├── 实现技能进化谱系追踪
├── 集成到 /evolve 命令体系
└── 端到端测试: 模式发现→锻造→使用→进化
```

**验收标准:**
- 至少自动发现并锻造 3 个技能
- 技能命中率 (用户实际使用) > 50%
- 技能进化谱系可追溯

### Phase 5D: 元进化 (持续)

```
Week 8+:
├── 进化效果度量体系
├── 好奇心驱动自我探索 (Self-Questioning)
├── A/B测试框架 (Bayesian)
└── 进化策略自动调参 (EvoPrompt风格)
```

---

## 六、安全约束 (NemoClaw级)

```
╔════════════════════════════════════════════╗
║           NeoMind Safety Stack             ║
╠════════════════════════════════════════════╣
║                                            ║
║  Layer 4: Audit Trail (审计)              ║
║  • 每次自动修改记录完整diff               ║
║  • .safety_audit.log                      ║
║  • 不可篡改的追加日志                     ║
║                                            ║
║  Layer 3: Policy Enforcement (策略)       ║
║  • 人工审批门 (Prototype→Active)          ║
║  • 资源限制 (LLM调用/天, token预算)       ║
║  • 禁止列表 (rm -rf, .env修改等)          ║
║                                            ║
║  Layer 2: Sandbox (沙箱)                  ║
║  • 文件系统限制 (/sandbox, /tmp)          ║
║  • 网络限制 (仅白名单)                    ║
║  • 系统调用过滤                           ║
║                                            ║
║  Layer 1: Rollback (回滚)                 ║
║  • Git tag 备份 (已有)                    ║
║  • 任何操作可 5分钟内回滚                 ║
║  • 技能版本控制                           ║
║                                            ║
╚════════════════════════════════════════════╝
```

**每日资源预算:**
```yaml
evolution_budget:
  reflection:
    session_reflections_per_day: 5
    deep_reflection_per_week: 1
    max_tokens_per_reflection: 2000
  skill_forge:
    skill_generations_per_day: 3
    max_tokens_per_generation: 3000
  total_daily_token_budget: 20000  # ~$0.06/day at current pricing
  model_preference: deepseek-chat  # 最便宜的选项
```

---

## 七、NeoMind 独特竞争力 (vs OpenClaw)

| 维度 | OpenClaw | NeoMind 差异化 |
|------|---------|---------------|
| **多人格** | 单一Agent | 三人格(Chat/Coding/Fin)共享进化成果 |
| **记忆** | MEMORY.md + 每日日志 | 三层认知记忆 + Ebbinghaus遗忘 + 混合检索 |
| **技能来源** | ClawHub社区 (5400+) | 自我锻造 + 社区双轨; 人工验证 > 纯自动 |
| **进化驱动** | 失败驱动 | 失败驱动 + 好奇心驱动 (Self-Questioning) |
| **反思深度** | 日志检测 → 代码补丁 | 三模式反思 (即时/会话/深度) + 5-Why因果DAG |
| **第一性原理** | 无 | 每次进化必须追溯根因 |
| **金融特化** | 通用 | Fin模式专属进化路径 (市场模式、风险模型) |
| **安全模型** | 基础 | NemoClaw级四层安全栈 |
| **成本控制** | 无特别优化 | 模型路由 + 缓存 + 批量反思 + token预算 |
| **元认知** | 无 | 5维置信度自评 + 能力边界感知 |

---

## 八、完整参考资源 (50+ 项目)

### 核心框架

| # | 项目 | 链接 | 核心价值 |
|---|------|------|---------|
| 1 | OpenClaw | github.com/openclaw/openclaw | Self-Improve, Foundry, Memory |
| 2 | Self-Improve Skill | github.com/peterskoett/self-improving-agent | LEARNINGS.md格式, Hook机制 |
| 3 | OpenClaw Foundry | github.com/lekt9/openclaw-foundry | 70%固化阈值, 安全扫描 |
| 4 | Evolver (GEP) | github.com/EvoMap/evolver | 基因组进化协议, 5-JSON输出 |
| 5 | OpenClaw-RL | github.com/Gen-Verse/OpenClaw-RL | PRM Judge + OPD |
| 6 | Self-Evolve.club | self-evolve.club | Intent-Experience Triplets |

### 反思与自我纠错

| # | 项目 | 链接 | 核心价值 |
|---|------|------|---------|
| 7 | Reflexion | github.com/noahshinn/reflexion | 语言强化学习, 情景记忆缓冲 |
| 8 | Self-Refine | selfrefine.info | Generate→Feedback→Refine循环 |
| 9 | LATS | github.com/lapisrocks/LanguageAgentTreeSearch | MCTS + LLM价值函数 |
| 10 | ExpeL | github.com/LeapLabTHU/ExpeL | 经验提取 + Faiss检索 |
| 11 | CHIEF | arxiv.org/abs/2602.23701 | 因果DAG + 层次回溯 |

### 技能库系统

| # | 项目 | 链接 | 核心价值 |
|---|------|------|---------|
| 12 | VOYAGER | voyager.minedojo.org | 技能库 + 三重反馈 + 自动课程 |
| 13 | SkillRL | github.com/aiming-lab/SkillRL | 递归技能增强 + 共进化 |
| 14 | OpenSpace | github.com/HKUDS/OpenSpace | Living Skills + 三种进化模式 |
| 15 | Anthropic Skills | agentskills.io/specification | SKILL.md标准 + 渐进披露 |
| 16 | CRADLE | github.com/BAAI-Agents/Cradle | 视频→技能提取 |
| 17 | SkillsBench | arxiv.org/abs/2602.12670 | 技能效果基准测试 |

### 记忆系统

| # | 项目 | 链接 | 核心价值 |
|---|------|------|---------|
| 18 | ReMe | github.com/agentscope-ai/ReMe | 效用剪枝 + 混合检索 |
| 19 | A-MEM | github.com/agiresearch/A-mem | Zettelkasten动态链接 |
| 20 | Letta/MemGPT | docs.letta.com | 三层记忆 + Agent自编辑 |
| 21 | Zep/Graphiti | github.com/getzep/graphiti | 时序知识图谱 + 双时间模型 |
| 22 | Mem0 | github.com/mem0ai/mem0 | 通用记忆层 + 衰减过滤 |
| 23 | MIRIX | github.com/Mirix-AI/MIRIX | 六组件模块化 + 多模态 |
| 24 | GitHub Copilot Memory | github.blog | JIT引用验证 |
| 25 | Memsearch | github.com/zilliztech/memsearch | Markdown-first + ONNX本地嵌入 |
| 26 | Memory-LanceDB-Pro | github.com/CortexReach/memory-lancedb-pro | 交叉编码器重排 + 三层晋升 |

### 共进化与自我对弈

| # | 项目 | 链接 | 核心价值 |
|---|------|------|---------|
| 27 | Agent0 | arxiv.org/abs/2511.16043 | 零数据课程-执行共进化 |
| 28 | AgentEvolver | github.com/modelscope/AgentEvolver | Self-Questioning/Navigating/Attributing |
| 29 | EvoAgentX | github.com/EvoAgentX/EvoAgentX | Workflow进化 + 双层记忆 |
| 30 | JiuwenClaw | openjiuwen.com | 执行到学习闭环 |
| 31 | SEAgent | arxiv.org/abs/2508.04700 | 自主探索学习 |
| 32 | MAE | arxiv.org/abs/2510.23595 | 多Agent共进化 |
| 33 | SAGE | arxiv.org/abs/2509.11035 | 四Agent协作+对抗 |

### 安全与治理

| # | 项目 | 链接 | 核心价值 |
|---|------|------|---------|
| 34 | NemoClaw | nvidia.com/en-us/ai/nemoclaw | 四层沙箱隔离 |
| 35 | SafeAgents | github.com/microsoft/SafeAgents | ARIA+DHARMA评估 |
| 36 | AGENTSAFE | arxiv.org/abs/2512.03180 | MIT风险仓库→技术控制映射 |
| 37 | Constitutional AI | anthropic.com/research | 自我批评+RLAIF |

### 优化与进化算法

| # | 项目 | 链接 | 核心价值 |
|---|------|------|---------|
| 38 | EvoPrompt | github.com/beeevita/EvoPrompt | GA+DE种群进化 (+25%) |
| 39 | LangSmith | smith.langchain.com | Agent可观测性 |
| 40 | Langfuse | langfuse.com | 开源可观测性 |

### 综述论文

| # | 论文 | 链接 |
|---|------|------|
| 41 | "Comprehensive Survey of Self-Evolving AI Agents" | arxiv.org/abs/2508.07407 |
| 42 | "Survey of Self-Evolving Agents" | arxiv.org/abs/2507.21046 |
| 43 | "Awesome Self-Evolving Agents" | github.com/EvoAgentX/Awesome-Self-Evolving-Agents |
| 44 | "Memory Mechanism of LLM Agents" | arxiv.org/abs/2404.13501 |
| 45 | "Cognitive Architectures for AI Agents" | arxiv.org/abs/2309.02427 |

---

## 九、总结

经过 5 轮深度搜索和 50+ 项目的分析，NeoMind 的自我进化战略已从 v1 的概念设计升级为 v2 的实现级设计:

**v1 → v2 的关键补充:**

1. **OpenClaw 精确实现细节**: LEARNINGS.md 完整格式、Foundry 固化算法、GEP 协议 5-JSON 输出、Memory 混合搜索架构
2. **反思引擎深化**: Reflexion 情景记忆缓冲 → Self-Refine 迭代循环 → CHIEF 因果 DAG → 具体停止条件和成本控制
3. **记忆系统细化**: Ebbinghaus 遗忘公式、ReMe 效用剪枝阈值、混合检索评分公式 (0.6×cross-encoder + 0.4×hybrid)、MIRIX 六组件简化为三层+路由
4. **技能锻造落地**: Anthropic SKILL.md 标准格式、渐进式披露 token 节省、SkillsBench 发现("精选>自生成")、OpenSpace 三种进化模式
5. **安全治理升级**: NemoClaw 四层沙箱细节、SafeAgents 评估基准、资源预算控制 (~$0.06/天)
6. **成本优化策略**: 模型路由 (80/20)、批量反思 (30-50%节省)、缓存 (75-90%节省)

**NeoMind 的独特定位:**

> "三人格共享进化 × 好奇心驱动 × 第一性原理根因分析 × NemoClaw级安全"

这不是 OpenClaw 的复制品，而是为 NeoMind 的多人格架构和金融特化场景量身定制的进化体系。
