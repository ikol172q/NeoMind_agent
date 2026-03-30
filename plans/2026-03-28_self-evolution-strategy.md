# NeoMind 自我进化战略研究报告

> 日期: 2026-03-28
> 参考: OpenClaw, VOYAGER, EvoAgentX, AgentEvolver, OpenSpace, Agent0 等框架
> 目标: 为 NeoMind 设计适合自身特点的自我进化体系

---

## 一、现状诊断：NeoMind 当前进化能力

### 1.1 已有的进化模块

| 模块 | 文件 | 能力 | 局限性 |
|------|------|------|--------|
| AutoEvolve | `auto_evolve.py` (763行) | 启动健康检查、每日审计、每周回顾 | 仅统计+正则匹配，无深度学习 |
| Upgrade | `upgrade.py` (264行) | git pull + 回滚 | 只能拉取人工推送的更新，无自主代码生成 |
| Scheduler | `scheduler.py` (188行) | 会话生命周期调度 | 仅触发已有任务，无法调度新发现的任务 |
| Dashboard | `dashboard.py` (556行) | HTML可视化 | 仅展示，无分析结论生成 |
| SharedMemory | `shared_memory.py` (609行) | 跨模式记忆存储 | 无遗忘策略、无向量检索、无语义理解 |

### 1.2 关键差距分析

```
NeoMind 当前                          vs    业界前沿
─────────────────────────────────────────────────────
正则模式匹配 (regex)                  →    LLM驱动的语义理解
静态偏好记录                          →    动态技能库 (Skill Library)
拉取式更新 (git pull)                 →    自主代码生成 + 自动测试
单层记忆 (SQLite flat)                →    分层记忆 (短期/长期/工作记忆)
无任务生成能力                        →    好奇心驱动的自主探索
无自我反思                            →    执行→评估→改进闭环
无多Agent协作                         →    Proposer-Solver 共进化
```

---

## 二、OpenClaw 自我进化机制深度分析

### 2.1 核心架构

OpenClaw (247K+ GitHub stars) 的自我进化通过 **Self-Improve Skill** 实现：

```
┌─────────────────────────────────────────────────┐
│                  OpenClaw Agent                   │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ 运行日志  │→│ 失败检测  │→│ 代码更新生成   │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
│                                    ↓              │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │LEARNINGS │←│ 记忆改进  │←│  测试验证      │  │
│  │ERRORS.md │  └──────────┘  └───────────────┘  │
│  │FEATURES  │                                    │
│  └──────────┘                                    │
└─────────────────────────────────────────────────┘
```

**三种运行模式：**
1. **One-command** — 单次执行自我改进
2. **Review Mode** — 人工审批每个改动 (Human-in-the-Loop)
3. **Mad Dog Mode** — 全自动持续进化

**OpenClaw 值得借鉴的设计：**
- 在运行日志中检测失败和低效模式
- 自动生成代码补丁和记忆更新
- 结构化输出: LEARNINGS.md / ERRORS.md / FEATURE_REQUESTS.md
- Foundry 子项目: "agent that builds agents" — 70%+ 成功率时将模式固化为专用工具

### 2.2 OpenClaw 生态中的进化相关项目

| 项目 | 核心思想 | NeoMind 可借鉴点 |
|------|---------|-----------------|
| **Evolver (GEP)** | 基因组进化协议 | 配置参数的自动调优 |
| **NemoClaw (NVIDIA)** | 安全参考栈 | 进化过程中的安全约束 |
| **Foundry** | Agent构建Agent | 将高频模式固化为新命令 |
| **OpenClaw-RL** | 强化学习权重更新 | 基于反馈的策略优化 |
| **Self-Evolve.club** | RL风格技能进化 | 低token RAG检索共享知识 |

---

## 三、全球自我进化Agent框架扫描

### 3.1 可直接借鉴的框架

#### VOYAGER (MineDojo / NVIDIA)
**核心机制:** 终身学习型具身Agent
```
自动课程生成 → 技能代码编写 → 环境执行 → 自我反思 → 技能库存储
```
**关键创新:**
- **Skill Library**: 将成功的技能存为可复用的 JavaScript 函数
- **Iterative Prompting**: 失败后自动调试，最多4轮
- **Automatic Curriculum**: 基于当前能力渐进式提出新挑战
- **防遗忘**: 组合式技能，新技能基于旧技能构建

**NeoMind 可借鉴:**
- 将成功的命令序列保存为"技能"
- 失败时自动重试+反思
- 渐进式能力拓展

#### EvoAgentX
**核心机制:** 自进化Agent生态系统
```
目标定义 → Workflow进化 → 短期/长期记忆 → 人工检查点 → 迭代优化
```
**关键创新:**
- 自动化 workflow 进化算法
- 双层记忆: 短期(会话内) + 长期(跨会话)
- Dataset-driven 和 Goal-driven 两种优化模式
- Human-in-the-Loop 检查点

**NeoMind 可借鉴:**
- 将 workflow 本身作为可进化的对象
- 引入目标驱动的优化

#### AgentEvolver (ModelScope/阿里)
**核心机制:** 三阶段高效自进化
```
Self-Questioning → Self-Navigating → Self-Attributing
(好奇心驱动)    (经验复用探索)    (差异化奖励)
```
**关键创新:**
- **Self-Questioning**: 自动生成任务来锻炼自己
- **Self-Navigating**: 通过历史经验提高探索效率
- **Self-Attributing**: 区分不同样本的贡献度

**NeoMind 可借鉴:**
- Agent 主动给自己出题 → 发现能力边界
- 根据历史成功经验引导未来行为

#### OpenSpace (港大)
**核心机制:** "活技能" (Living Skills)
```
技能自动选择 → 自动应用 → 自动监控 → 自动进化
```
**关键创新:**
- 技能拥有自己的生命周期
- 无需人工干预的全自动技能管理
- 技能间的自动组合与分解

**NeoMind 可借鉴:**
- 赋予技能"生命"，让它们自我优化
- 技能使用频率低时自动退化，高时自动增强

#### Agent0
**核心机制:** 零数据共进化
```
课程Agent ⇄ 执行Agent (共生竞争)
```
**关键创新:**
- 不需要外部数据即可自我进化
- 课程生成器和执行器同步进化
- 无缝工具集成

#### SEAgent (自进化计算机使用Agent)
**核心机制:** 自主探索学习
```
探索陌生软件 → 试错迭代 → 自动生成任务(简→难) → 能力积累
```

#### JiuwenClaw (OpenJiuwen)
**核心机制:** 执行到学习闭环
```
任务执行 → 结果分析 → 知识提炼 → 意图对齐 → 能力更新
```

### 3.2 记忆系统专项

| 项目 | 特点 | GitHub |
|------|------|--------|
| **ReMe** | 文件+向量双存储，自动压缩 | agentscope-ai/ReMe |
| **MemOS** | 跨任务持久技能记忆 | MemTensor/MemOS |
| **A-MEM** | Agent式动态记忆组织 | agiresearch/A-mem |
| **GitHub Copilot Memory** | 代码感知记忆+验证 | GitHub官方 |

### 3.3 技能系统专项

| 项目 | 特点 |
|------|------|
| **Anthropic Skills** | 模块化Agent能力的开放格式 |
| **SkillRL** | 递归技能增强，技能库与策略共进化 |

---

## 四、NeoMind 自我进化战略设计

### 4.1 设计原则 (继承 NeoMind 第一性原理)

1. **Zero-Dependency 进化** — 进化引擎不增加外部依赖 (保持 stdlib-only 核心)
2. **LLM-Augmented, Not LLM-Dependent** — 用 LLM 增强但不依赖，降级时仍可运行
3. **First Principles Thinking** — 每次进化必须追溯到根因
4. **Safety First** — 所有自修改必须可逆、可审计
5. **Cross-Mode Synergy** — 三个人格共享进化成果

### 4.2 五层进化架构

```
╔══════════════════════════════════════════════════════════════╗
║                    NeoMind Evolution Stack                    ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  L5  ┌─────────────────────────────────────────────────┐    ║
║      │         Meta-Evolution (自我进化的进化)           │    ║
║      │  • 进化策略本身的A/B测试和优化                     │    ║
║      │  • 进化效率的度量和改进                            │    ║
║      └─────────────────────────────────────────────────┘    ║
║                              ↑                               ║
║  L4  ┌─────────────────────────────────────────────────┐    ║
║      │         Skill Forge (技能锻造)                    │    ║
║      │  • 高频模式 → 新技能自动生成                       │    ║
║      │  • 技能组合、分解、退化                            │    ║
║      │  • Foundry模式: Agent构建Agent                    │    ║
║      └─────────────────────────────────────────────────┘    ║
║                              ↑                               ║
║  L3  ┌─────────────────────────────────────────────────┐    ║
║      │         Reflection Engine (反思引擎)              │    ║
║      │  • 执行后自动评估: 成功/失败/部分成功              │    ║
║      │  • 失败根因分析 (5-Why)                           │    ║
║      │  • 改进建议生成 (LLM-Augmented)                   │    ║
║      └─────────────────────────────────────────────────┘    ║
║                              ↑                               ║
║  L2  ┌─────────────────────────────────────────────────┐    ║
║      │         Adaptive Memory (自适应记忆)              │    ║
║      │  • 三层记忆: 工作记忆/情景记忆/语义记忆            │    ║
║      │  • 自动压缩与遗忘                                 │    ║
║      │  • 跨模式知识迁移                                 │    ║
║      └─────────────────────────────────────────────────┘    ║
║                              ↑                               ║
║  L1  ┌─────────────────────────────────────────────────┐    ║
║      │         Observation Layer (观测层) [已有,增强]     │    ║
║      │  • 行为日志 + 证据链                              │    ║
║      │  • 模式检测 (regex → regex+LLM)                   │    ║
║      │  • 性能指标采集                                   │    ║
║      └─────────────────────────────────────────────────┘    ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

### 4.3 各层详细设计

---

#### L1: Observation Layer (观测层) — 增强现有

**现状:** `auto_evolve.py` 的 `learn_from_feedback` + `learn_from_conversation`

**增强方案:**

```python
# 新增: agent/evolution/observer.py

class ExecutionObserver:
    """增强版观测器 — 捕获每次工具调用的完整上下文"""

    def observe_tool_call(self, tool_name, input_args, output,
                          duration_ms, success, error_msg=None):
        """记录工具调用的完整轨迹"""
        entry = {
            "ts": now_iso(),
            "tool": tool_name,
            "input_hash": hash_content(input_args),  # 隐私保护
            "output_preview": output[:200],
            "duration_ms": duration_ms,
            "success": success,
            "error": error_msg,
            "mode": current_mode(),
            "turn": current_turn(),
        }
        self._append_to_trail(entry)

        # 实时异常检测
        if not success:
            self._record_failure_pattern(tool_name, error_msg)
        if duration_ms > self._get_tool_p95(tool_name):
            self._record_slow_execution(tool_name, duration_ms)

    def observe_user_satisfaction(self, user_msg, bot_response):
        """检测用户满意度信号"""
        signals = {
            "positive": ["谢谢", "很好", "perfect", "great", "thanks"],
            "negative": ["不对", "错了", "wrong", "no", "太长", "太短"],
            "retry": ["再试", "重新", "try again", "redo"],
        }
        # ... 信号检测和记录
```

**借鉴来源:** OpenClaw 运行日志检测 + VOYAGER 环境反馈

---

#### L2: Adaptive Memory (自适应记忆) — 重构 SharedMemory

**现状:** 单层 SQLite，4 张表，无遗忘策略

**增强方案: 三层记忆架构**

```python
# 新增: agent/memory/adaptive_memory.py

class AdaptiveMemory:
    """三层自适应记忆系统

    灵感来源:
    - ReMe (agentscope-ai): 文件+向量双存储
    - A-MEM (agiresearch): Agent式动态组织
    - 人类认知科学: 工作记忆/情景记忆/语义记忆
    """

    def __init__(self):
        self.working = WorkingMemory(capacity=20)    # 当前会话上下文
        self.episodic = EpisodicMemory()             # 具体事件记录
        self.semantic = SemanticMemory()             # 提炼的知识

    # ── 工作记忆 (会话级，容量有限) ──
    class WorkingMemory:
        """当前会话的活跃上下文，LRU淘汰"""
        def add(self, item): ...
        def get_context(self, max_items=10): ...

    # ── 情景记忆 (事件级，自动衰减) ──
    class EpisodicMemory:
        """具体交互事件，带时间衰减

        衰减公式: relevance = base_score * decay^(days_since)
        高访问频率 → 衰减更慢 (Ebbinghaus 遗忘曲线)
        """
        def remember_episode(self, event_type, context, outcome): ...
        def recall_similar(self, query, top_k=5): ...  # 语义相似检索
        def forget_stale(self, threshold=0.1): ...      # 自动遗忘

    # ── 语义记忆 (知识级，持久) ──
    class SemanticMemory:
        """从情景记忆中提炼的稳定知识

        提炼规则:
        - 同类事件出现3次+ → 提炼为语义知识
        - 用户确认的事实 → 直接写入
        - 矛盾知识 → 保留最新，标记冲突
        """
        def distill_from_episodes(self): ...
        def query(self, topic): ...
```

**遗忘策略 (Forgetting Policy):**
```
热度 = 访问次数 × 时间衰减因子 × 重要性权重

if 热度 < 0.1:
    归档到冷存储 (gzip压缩的JSONL)
if 热度 < 0.01:
    永久删除 (保留统计摘要)
```

**借鉴来源:** ReMe 自动压缩 + A-MEM 动态组织 + MemOS 跨任务持久化

---

#### L3: Reflection Engine (反思引擎) — 全新模块

**这是 NeoMind 与 OpenClaw 最大的差距所在。**

```python
# 新增: agent/evolution/reflection.py

class ReflectionEngine:
    """执行后反思引擎

    灵感来源:
    - VOYAGER: 失败后自动调试 (最多4轮)
    - OpenClaw Self-Improve: 日志分析 → 代码更新
    - AgentEvolver: Self-Attributing (差异化归因)
    """

    # ── 模式1: 即时反思 (每次工具调用后) ──
    def reflect_on_execution(self, tool_call, result):
        """快速反思: 这次执行可以改进吗?

        不调用LLM，纯规则:
        - 超时 → 记录慢模式
        - 失败 → 记录错误模式
        - 用户重试 → 记录不满信号
        """
        pass

    # ── 模式2: 会话反思 (会话结束时) ──
    def reflect_on_session(self, session_log):
        """会话级反思: 调用LLM分析整个会话

        输入: 会话中所有工具调用和用户反馈
        输出: SessionReflection {
            successes: [...],
            failures: [...],
            root_causes: [...],
            improvement_actions: [...]
        }

        成本控制: 使用最便宜的模型 (deepseek-chat)
        频率控制: 每天最多5次会话反思
        """
        pass

    # ── 模式3: 深度反思 (每周) ──
    def deep_reflection(self, week_data):
        """周级深度反思: 发现系统性问题

        分析维度:
        1. 重复出现的失败模式 → 需要新技能
        2. 用户频繁切换模式 → 模式边界不清
        3. 某类任务成功率下降 → 能力退化
        4. 新出现的使用模式 → 新需求信号

        输出: LEARNINGS.md + ERRORS.md + FEATURE_REQUESTS.md
        (借鉴 OpenClaw 的结构化输出格式)
        """
        pass

    # ── 5-Why 根因分析 ──
    def five_why_analysis(self, failure_event):
        """对重复失败进行5-Why分析

        Example:
        Why1: 搜索返回空结果
        Why2: 关键词过于宽泛
        Why3: 用户意图理解不准确
        Why4: 缺少领域知识上下文
        Why5: 没有利用历史搜索记录
        → Action: 搜索前注入历史成功搜索的关键词模式
        """
        pass
```

**反思的输出格式 (借鉴 OpenClaw):**

```markdown
# ~/.neomind/evolution/LEARNINGS.md
## 2026-03-28
- [搜索] 用户搜索中文内容时，先翻译为英文再搜索效果更好
- [代码] 用户偏好 Python type hints，应默认添加
- [金融] 用户关注的股票: AAPL, TSLA, NVDA — 自动加入watchlist

# ~/.neomind/evolution/ERRORS.md
## 2026-03-28
- [E001] Web搜索超时(>10s)频率增加 — 考虑增加缓存层
- [E002] fin模式数据源偶尔返回空 — 需要备用数据源

# ~/.neomind/evolution/FEATURE_REQUESTS.md
## 2026-03-28
- [F001] 用户多次询问PDF解析 → 需要PDF工具集成
- [F002] 用户尝试同时处理多文件 → 需要批处理能力
```

---

#### L4: Skill Forge (技能锻造) — 全新模块

**灵感来源:** VOYAGER Skill Library + OpenClaw Foundry + OpenSpace Living Skills

```python
# 新增: agent/evolution/skill_forge.py

class SkillForge:
    """技能锻造引擎 — NeoMind 的核心进化能力

    将高频成功模式固化为可复用的技能。

    技能生命周期:
    Prototype → Testing → Active → Mature → Deprecated

    灵感:
    - VOYAGER: 技能库存储可执行代码
    - Foundry: 70%+ 成功率时固化
    - OpenSpace: 技能自动选择和进化
    - SkillRL: 技能库与策略共进化
    """

    def detect_skill_candidates(self, recent_sessions):
        """从最近的会话中发现技能候选

        触发条件:
        1. 相同命令序列出现 3+ 次
        2. 用户对某个复杂操作的结果一直满意
        3. 某个模式的成功率 > 80%
        """
        pass

    def forge_skill(self, pattern, examples):
        """将模式锻造为技能

        过程:
        1. 提取模式的核心步骤
        2. 参数化可变部分
        3. 生成技能代码 (Python函数)
        4. 生成测试用例
        5. 沙箱执行测试
        6. 成功 → 注册到技能库

        安全约束:
        - 生成的代码必须通过静态分析
        - 不允许: 网络请求、文件删除、系统命令
        - 新技能初始状态为 Prototype
        - 需要5次成功使用后升级为 Active
        """
        pass

    def evolve_skill(self, skill_name, feedback):
        """根据反馈进化已有技能

        进化方向:
        - 增加新参数
        - 修复edge case
        - 优化性能
        - 组合其他技能
        """
        pass

    def deprecate_skill(self, skill_name):
        """技能退化/下线

        触发条件:
        - 30天未使用
        - 成功率降至 <50%
        - 被更好的技能替代
        """
        pass

# 技能存储格式
SKILL_TEMPLATE = {
    "name": "smart_search",
    "version": "1.0.0",
    "status": "active",  # prototype/testing/active/mature/deprecated
    "description": "基于历史搜索模式的智能搜索",
    "trigger_patterns": ["搜索", "search", "查找"],
    "code": "def smart_search(query, mode='web'): ...",
    "tests": ["test_smart_search_basic", "test_smart_search_chinese"],
    "stats": {
        "total_calls": 42,
        "success_rate": 0.88,
        "avg_duration_ms": 350,
        "last_used": "2026-03-28T10:00:00Z",
        "created_at": "2026-03-15T10:00:00Z",
    },
    "lineage": {  # 技能进化谱系
        "parent": None,
        "children": ["smart_search_v2"],
        "evolved_from_pattern": "user_search_retry_pattern",
    }
}
```

**技能库目录结构:**
```
~/.neomind/skills/
├── registry.json           # 技能注册表
├── active/
│   ├── smart_search.py     # 活跃技能
│   ├── smart_search_test.py
│   └── code_template.py
├── prototype/              # 试验中的技能
├── deprecated/             # 已废弃的技能
└── lineage.json            # 技能进化谱系图
```

---

#### L5: Meta-Evolution (元进化) — 长期目标

```python
# 未来: agent/evolution/meta.py

class MetaEvolution:
    """进化策略本身的进化

    灵感: Agent0 的课程-执行共进化

    核心问题: 我们的进化策略是否有效?

    度量:
    - 新技能的采纳率 (被用户实际使用的比例)
    - 反思建议的落地率
    - 整体用户满意度趋势
    - 进化消耗的资源 vs 带来的价值

    自动A/B测试:
    - 不同反思频率的效果对比
    - 不同遗忘策略的记忆效率
    - 不同技能固化阈值的最优值
    """
    pass
```

---

## 五、实施路线图

### Phase 5A: 反思闭环 (2周)

**优先级: 最高 — 这是 NeoMind 与 OpenClaw 最大的差距**

```
Week 1:
├── 增强 ExecutionObserver (观测层升级)
├── 实现即时反思 (规则引擎，不调LLM)
└── 实现 LEARNINGS.md / ERRORS.md 结构化输出

Week 2:
├── 实现会话级反思 (调用 deepseek-chat)
├── 实现 5-Why 根因分析
└── 将反思结果注入 system prompt
```

**预期效果:**
- 自动发现并记录失败模式
- 同类错误不再重复出现
- 用户可以查看 `/evolve learnings`

### Phase 5B: 自适应记忆 (2周)

```
Week 3:
├── 实现三层记忆架构
├── 迁移 SharedMemory 数据到新架构
└── 实现时间衰减遗忘策略

Week 4:
├── 实现情景→语义的知识提炼
├── 实现跨模式知识迁移优化
└── 记忆容量监控和自动清理
```

**预期效果:**
- 记忆不再无限膨胀
- 重要知识持久保留，琐碎信息自动遗忘
- 三个人格共享更智能的上下文

### Phase 5C: 技能锻造 (3周)

```
Week 5:
├── 实现技能候选检测
├── 实现技能存储格式和注册表
└── 实现技能生命周期管理

Week 6:
├── 实现 LLM-Augmented 技能代码生成
├── 实现沙箱测试执行
└── 实现技能触发和调度

Week 7:
├── 实现技能进化 (版本迭代)
├── 实现技能退化机制
├── 实现技能进化谱系追踪
└── 集成到 /evolve 命令体系
```

**预期效果:**
- NeoMind 自动从使用模式中"学会"新能力
- 高频操作变为一键执行
- 技能可追溯、可回滚

### Phase 5D: 元进化 (持续)

```
Week 8+:
├── 进化效果度量体系
├── 自动A/B测试框架
└── 进化策略自动调参
```

---

## 六、与现有架构的集成点

```
agent/
├── evolution/
│   ├── auto_evolve.py        # [修改] 接入反思引擎
│   ├── observer.py            # [新增] 增强版观测器
│   ├── reflection.py          # [新增] 反思引擎
│   ├── skill_forge.py         # [新增] 技能锻造
│   ├── meta.py                # [新增] 元进化 (Phase 5D)
│   ├── upgrade.py             # [保留] 仍需git-based升级
│   ├── scheduler.py           # [修改] 调度新任务
│   └── dashboard.py           # [修改] 展示新指标
├── memory/
│   ├── shared_memory.py       # [保留] 向后兼容层
│   ├── adaptive_memory.py     # [新增] 三层记忆
│   ├── working_memory.py      # [新增] 会话级记忆
│   └── forgetting.py          # [新增] 遗忘策略
├── core.py                    # [修改] 接入观测器和反思
└── ...
```

**向后兼容:**
- SharedMemory 作为 SemanticMemory 的适配器保留
- 现有 /evolve 命令全部保留，增加新子命令
- 现有 SQLite 数据自动迁移

---

## 七、安全约束

参照 NemoClaw (NVIDIA) 的安全参考栈:

1. **沙箱执行**: 所有自动生成的代码在隔离环境中运行
2. **变更审计**: 每次自动修改记录完整diff到 `.safety_audit.log`
3. **人工审批门**: 技能从 Prototype → Active 需要人工确认 (可关闭)
4. **回滚能力**: 任何进化操作可在5分钟内回滚
5. **资源限制**:
   - 每日 LLM 调用预算: 反思最多 5 次/天
   - 技能生成最多 3 次/天
   - 总token消耗上限可配置
6. **禁止列表**: 自动生成的代码不允许:
   - 修改 `.env` 或凭证文件
   - 执行 `rm -rf` 等危险命令
   - 访问非白名单的网络地址
   - 修改 evolution 引擎自身的代码

---

## 八、NeoMind 独特优势 (区别于 OpenClaw)

| 维度 | OpenClaw | NeoMind 的差异化 |
|------|---------|-----------------|
| **多人格** | 单一Agent | 三人格(Chat/Coding/Fin)共享进化 |
| **记忆** | 简单日志 | 三层认知记忆 + 遗忘曲线 |
| **技能来源** | 社区市场 | 自我锻造 + 社区 (双轨) |
| **进化驱动** | 失败驱动 | 失败驱动 + 好奇心驱动 (Self-Questioning) |
| **第一性原理** | 无 | 进化前必须追溯根因 |
| **金融特化** | 通用 | 金融模式有专属进化路径 |
| **安全模型** | 基础 | NemoClaw级安全约束 |

---

## 九、核心参考资源

| 项目 | 链接 | 核心价值 |
|------|------|---------|
| OpenClaw | github.com/openclaw/openclaw | Self-Improve Skill, Foundry |
| VOYAGER | voyager.minedojo.org | Skill Library, Iterative Prompting |
| EvoAgentX | github.com/EvoAgentX/EvoAgentX | Workflow进化, 双层记忆 |
| AgentEvolver | github.com/modelscope/AgentEvolver | Self-Questioning, Self-Navigating |
| OpenSpace | github.com/HKUDS/OpenSpace | Living Skills 生命周期 |
| Agent0 | arxiv.org/abs/2511.16043 | 零数据共进化 |
| SEAgent | arxiv.org/abs/2508.04700 | 自主探索学习 |
| JiuwenClaw | openjiuwen.com | 执行到学习闭环 |
| ReMe | github.com/agentscope-ai/ReMe | 自动压缩记忆 |
| A-MEM | github.com/agiresearch/A-mem | Agent式记忆组织 |
| SkillRL | github.com/aiming-lab/SkillRL | 技能与策略共进化 |
| Self-Evolve.club | self-evolve.club | RL风格技能进化 |
| NemoClaw | github.com/NVIDIA/NemoClaw | 安全参考栈 |
| Awesome Self-Evolving Agents | github.com/EvoAgentX/Awesome-Self-Evolving-Agents | 综述 |

---

## 十、总结

NeoMind 当前的进化系统 (Phase 4) 建立了良好的基础——健康检查、审计、回顾、共享记忆。但与 OpenClaw 及业界前沿相比，缺少三个关键能力:

1. **反思闭环** — 从"记录"到"理解"的跃迁
2. **技能锻造** — 从"记忆模式"到"生成能力"的跃迁
3. **认知记忆** — 从"扁平存储"到"分层认知"的跃迁

Phase 5 的战略是: **不抄袭 OpenClaw，而是结合 NeoMind 的多人格架构和第一性原理哲学，打造"三人格共享进化 + 好奇心驱动 + 第一性原理根因分析"的独特进化体系。**

这是 NeoMind 从"会学习的工具"进化为"会成长的智能体"的关键一步。
