# NeoMind 自我进化系统 — 综合集成计划 (研究增强版)

> 日期: 2026-03-28
> 版本: v3.0 — 基于6轮深度研究、50+论文/框架分析后的完整集成方案
> 目标: 确保17个模块无缝协作，并融入最新研究成果

---

## 0. 文档导航

本计划分为四大部分:

1. **模块全景图** — 17个模块的角色、数据流、生命周期集成点
2. **研究增强层** — 每个模块可吸收的前沿论文/技术，以及具体改造方案
3. **集成架构** — 模块间交互、数据流管道、Docker部署拓扑
4. **分阶段实施路线图** — 从当前代码到完整自进化系统的4阶段计划

---

## 1. 模块全景图

### 1.1 模块分层架构

```
╔══════════════════════════════════════════════════════════════════╗
║                    Layer 5: 元进化层 (Meta)                       ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  ║
║  │ meta_evolve  │  │ cost_optimizer│  │ dashboard            │  ║
║  │ 策略自调节     │  │ 预算/路由      │  │ 可视化               │  ║
║  └──────┬───────┘  └──────┬───────┘  └──────────────────────┘  ║
╠═════════╪══════════════════╪═════════════════════════════════════╣
║         │    Layer 4: 主动进化层 (Active Evolution)               ║
║  ┌──────┴───────┐  ┌──────┴───────┐  ┌──────────────────────┐  ║
║  │ goal_tracker │  │ prompt_tuner │  │ self_edit             │  ║
║  │ 自主目标       │  │ 提示词调优     │  │ 代码自修改            │  ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘  ║
╠══════════════════════════════════════════════════════════════════╣
║                Layer 3: 认知层 (Cognition)                        ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  ║
║  │ learnings    │  │ skill_forge  │  │ reflection            │  ║
║  │ 结构化学习     │  │ 技能结晶       │  │ 自我反思              │  ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘  ║
╠══════════════════════════════════════════════════════════════════╣
║                Layer 2: 生存层 (Survival)                         ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  ║
║  │ self_unblock │  │ checkpoint   │  │ upgrade               │  ║
║  │ 自我解围       │  │ 状态存档       │  │ Git自升级             │  ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘  ║
╠══════════════════════════════════════════════════════════════════╣
║                Layer 1: 基础设施层 (Infra)                        ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  ║
║  │ auto_evolve  │  │ health_monitor│ │ watchdog              │  ║
║  │ 健康检查/审计  │  │ 心跳/告警      │  │ 最后手段重启           │  ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘  ║
╠══════════════════════════════════════════════════════════════════╣
║                Layer 0: 调度器 (Orchestration)                    ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │                    scheduler.py                           │   ║
║  │  on_session_start → on_turn_complete → on_session_end    │   ║
║  │  on_error → get_prompt_additions → get_evolution_status   │   ║
║  └──────────────────────────────────────────────────────────┘   ║
╚══════════════════════════════════════════════════════════════════╝
```

### 1.2 模块清单 (17个)

| # | 模块 | 文件 | 行数 | 职责 | 依赖 |
|---|------|------|------|------|------|
| 1 | **scheduler** | `scheduler.py` | 541 | 生命周期编排，所有引擎的入口 | 所有其他模块 (lazy) |
| 2 | **auto_evolve** | `auto_evolve.py` | 763 | 启动检查、日审计、周回顾 | 无 |
| 3 | **health_monitor** | `health_monitor.py` | 468 | 心跳检测、启动循环保护、Telegram告警 | 无 (独立进程) |
| 4 | **watchdog** | `watchdog.py` | 212 | 最后手段挂起检测+强制重启 | supervisord |
| 5 | **checkpoint** | `checkpoint.py` | 186 | 原子状态保存/恢复 | 无 |
| 6 | **self_unblock** | `self_unblock.py` | 397 | 运行时障碍自诊断+修复 | LLM (adhoc脚本) |
| 7 | **self_edit** | `self_edit.py` | 382 | Git-Gated 代码自修改 | git, ast, pytest |
| 8 | **upgrade** | `upgrade.py` | 264 | Git-based 外部升级拉取 | git |
| 9 | **learnings** | `learnings.py` | 460 | 结构化学习提取+Ebbinghaus衰减 | SQLite |
| 10 | **skill_forge** | `skill_forge.py` | 461 | 成功方案结晶为可复用技能 | SQLite |
| 11 | **reflection** | `reflection.py` | 448 | 多层次自我反思+改进假说 | SQLite, LLM (deep) |
| 12 | **prompt_tuner** | `prompt_tuner.py` | 359 | 指标驱动的YAML系统提示调优 | YAML config |
| 13 | **goal_tracker** | `goal_tracker.py` | 400 | 自主改进目标设定+跟踪 | SQLite |
| 14 | **meta_evolve** | `meta_evolve.py` | 301 | 进化系统自身的调参 | JSON state |
| 15 | **cost_optimizer** | `cost_optimizer.py` | 358 | token/成本追踪+模型路由 | SQLite |
| 16 | **dashboard** | `dashboard.py` | 556 | HTML进化指标可视化 | 所有引擎的get_stats() |
| 17 | **auto_evolve (审计)** | `auto_evolve.py` | (同上) | 日/周审计报告生成 | 日志文件 |

### 1.3 生命周期集成点

```
Agent启动
  │
  ├── tini (PID 1) → supervisord
  │     ├── neomind-agent (主进程)
  │     ├── health-monitor (独立进程)
  │     └── watchdog (独立进程)
  │
  ▼
scheduler.on_session_start()
  ├── heartbeat.start()              [health_monitor]
  ├── checkpoint.load()              [checkpoint]
  ├── auto_evolve.run_startup_check() [auto_evolve]
  ├── _run_daily_cycle() (if 24h+)   [auto_evolve, learnings, prompt_tuner, cost_optimizer]
  ├── _run_weekly_cycle() (if 7d+)   [auto_evolve, prompt_tuner, meta_evolve, goal_tracker]
  └── goal_tracker.expire_stale()    [goal_tracker]
  │
  ▼
每轮对话后: scheduler.on_turn_complete(turn_n, ...)
  ├── heartbeat.beat()               [health_monitor]
  ├── reflection.reflect_quick()     [reflection]
  ├── prompt_tuner.record_signal()   [prompt_tuner]
  ├── checkpoint.save()              [checkpoint]
  └── 每50轮: check daily cycle      [scheduler]
  │
  ▼
遇到错误时: scheduler.on_error(...)
  ├── reflection.reflect_on_error()  [reflection]
  ├── learnings.add_error_learning() [learnings]
  └── meta_evolve.record_outcome()   [meta_evolve]
  │
  ▼
系统提示注入: scheduler.get_prompt_additions(mode)
  ├── learnings.get_prompt_injection() [learnings] — 前5条高权重学习
  └── goal_tracker.get_goal_summary()  [goal_tracker] — 活跃目标
  │
  ▼
会话结束: scheduler.on_session_end()
  ├── auto_evolve.run_daily_audit()  [auto_evolve] (如果今天还没跑过)
  └── checkpoint.save(clean_shutdown) [checkpoint]
```

---

## 2. 研究增强层 — 每模块的理论升级

### 2.1 learnings.py → 增强记忆系统

**当前实现:** SQLite + Ebbinghaus衰减 (λ=0.05) + 简单字符重叠去重

**研究融入:**

#### 2.1.1 FOREVER 论文的自适应遗忘曲线
> 出处: arXiv, "FOREVER: Ebbinghaus-based continual learning for LLM agents"

当前用固定λ=0.05。FOREVER给出了更好的公式:

```python
# 当前 (固定衰减):
strength = importance * exp(-0.05 * days) * (1 + recall_count * 0.2)

# 升级为 (自适应衰减):
λ(n) = λ₀ × (1 − β × tanh(γ × n))
# n = recall_count (回忆次数)
# λ₀ = 0.05 (初始衰减率)
# β = 0.8 (最大衰减缓解)
# γ = 0.5 (缓解速度)
# 效果: 回忆3次后衰减率降到 0.012，几乎永久保留
```

**改造方案:** 修改 `_calculate_strength()` 方法，将 `(1 + recall_count * 0.2)` 替换为 FOREVER 的 `λ(n)` 公式。

#### 2.1.2 SimpleMem 的语义压缩
> 出处: SimpleMem (2025), 26.4% F1提升, 30x token压缩

当前学习内容是原始文本。SimpleMem 证明了语义结构化压缩的效果:

```python
# 改造: 学习存储时增加 compact_summary 字段
# 提取时对每条 learning 生成:
#   who: 涉及的实体
#   what: 发生了什么
#   why: 根本原因
#   action: 应采取的行动
# 存储压缩版本，检索时用压缩版匹配，展示时用完整版
```

**改造方案:** 在 `ingest_llm_learnings()` 中增加结构化提取步骤，新增 `compact_summary` 列。

#### 2.1.3 ReMe 的效用剪枝
> 出处: ReMe (2025), utility-based pruning, threshold 0.3, compact_ratio 0.7

当前剪枝规则是 `strength < 0.1 且 age > 30天`。ReMe 给出了更科学的效用函数:

```python
utility = recency_score * relevance_score * importance
# recency_score = 1 / (1 + days_since_last_recall)
# relevance_score = 基于当前mode的相关性 (0-1)
# 剪枝阈值: 0.3 (低于此值时合并而非删除)
# compact_ratio: 0.7 (合并后保留70%的信息密度)
```

**改造方案:** 修改 `decay_and_prune()` 方法，低效用学习先尝试合并相似条目，无法合并再删除。

#### 2.1.4 A-MEM 的 Zettelkasten 语义链接 (远期)
> 出处: A-MEM (2025), ChromaDB semantic linking, similarity > 0.7

当前学习之间无关联。A-MEM 用 Zettelkasten 方法建立原子笔记间的语义链接:
- 每条 learning 有 `linked_ids` 字段
- 新 learning 入库时，检索相似条目 (余弦 > 0.7)
- 自动建立双向链接
- 检索时可以沿链接展开相关学习

**优先级: 低** — 需要向量数据库 (可用sqlite-vss或简化为TF-IDF)

---

### 2.2 skill_forge.py → 增强技能系统

**当前实现:** DRAFT→TESTED→ACTIVE→PROMOTED生命周期 + 关键词匹配

**研究融入:**

#### 2.2.1 SkillRL 的双技能库 + Token压缩
> 出处: SkillRL (2025), 15.3%改进, 10-20x token压缩 (注: 是倍数不是百分比)

当前只有一个技能库。SkillRL 用双库设计:

```python
# General SkillBank: 跨任务通用技能
#   - 错误处理模式、代码审查清单、API调用模板
#   - 来源: 从多次成功中提炼的模式

# Task-Specific SkillBank: 任务特定技能
#   - 某类错误的修复方案、特定库的使用技巧
#   - 来源: 单次成功但有明确上下文

# 技能压缩: 将技能从自然语言压缩为结构化模板
# 效果: 减少 10-20% 的 prompt token 使用
```

**改造方案:** 在 `skills` 表添加 `bank_type` 字段 (general/task_specific)，提升时评估是否泛化为 general。

#### 2.2.2 SkillsBench 的关键发现: 聚焦优于全面
> 出处: SkillsBench (2025), 自生成技能对新手无益

**重要洞察:** 自动生成的技能对新手无益，聚焦的技能 (2-3个模块) 比全面文档更有效。

**改造方案:**
- 每次 `find_matching_skills()` 最多返回3个最相关技能 (而非全部匹配)
- 技能按使用频率和成功率排序
- 新技能需要 "聚焦审查": 每条技能必须针对具体场景，而非泛泛而谈

#### 2.2.3 VOYAGER 的技能验证循环 (借鉴但不抄)
> 出处: VOYAGER (Minecraft LLM agent), executable skill verification

VOYAGER 在存储技能前会验证其可执行性。NeoMind 可以类似地:

```python
# 存储技能前:
# 1. 如果是代码修复技能 → 尝试在沙箱中复现+修复
# 2. 如果是流程技能 → 检查步骤的完整性
# 3. 验证通过才进入 TESTED 状态
```

#### 2.2.4 技能安全: Prompt Injection 防护
> 出处: arXiv:2510.26328, 技能注入攻击

**关键风险:** 恶意技能可能包含prompt injection。需要信任分级:

```python
TRUST_TIERS = {
    "system": 1.0,      # NeoMind自己生成的技能
    "verified": 0.8,     # 经过多次成功验证的技能
    "user": 0.6,         # 用户提供的技能
    "external": 0.3,     # 外部来源的技能 (未来)
}
# 低信任技能在注入prompt前进行内容审查
```

---

### 2.3 reflection.py → 增强反思系统

**当前实现:** quick (启发式) → error (模式匹配) → deep (LLM周反思)

**研究融入:**

#### 2.3.1 PreFlect: 执行前的前瞻性反思
> 出处: PreFlect (2026), 11-17%改进 (实测11.68-17.14%)

当前反思全是回顾性的 (事后)。PreFlect 证明"事前反思"更有效:

```python
# 在每次复杂任务开始前:
def pre_reflect(task_description: str, mode: str) -> str:
    """生成执行前的自我提醒。

    基于历史错误模式和学习，生成:
    1. 此类任务最常犯的3个错误
    2. 应特别注意的事项
    3. 推荐的执行策略
    """
    # 从 learnings 和 reflection 中检索相关历史
    # 格式化为执行前提醒，注入到当前对话
```

**改造方案:** 在 `reflection.py` 新增 `pre_reflect()` 方法，scheduler在检测到复杂任务时调用。

#### 2.3.2 Reflexion 的滑动窗口
> 出处: Reflexion (2023), 91% HumanEval, 2-5次迭代最优

当前反思无上下文窗口管理。Reflexion的最佳实践:

```python
# 保留最近3次反思的滑动窗口
# 每次反思时参考前2-3次反思结果
# 避免超过5次迭代 (收益递减)
REFLECTION_WINDOW_SIZE = 3
MAX_REFLECTION_ITERATIONS = 5
```

#### 2.3.3 LATS 的搜索树反思 (远期)
> 出处: LATS (2023), MCTS + LLM value function, 92.7% HumanEval

对于复杂编码任务，可以引入轻量版MCTS:

```python
# 简化版: 不用完整MCTS，但借鉴其评估思路
# 对于编码任务失败时:
# 1. 生成2-3个替代方案 (expansion)
# 2. 用LLM评估每个方案的成功概率 (evaluation)
# 3. 选择概率最高的方案重试 (selection)
# 4. 记录哪个路径成功 (backpropagation → learnings)
```

#### 2.3.4 AutoRefine 的子代理提取
> 出处: AutoRefine (2026), 20-73%步骤减少

反思中发现的重复子任务可以自动提取为子代理:

```python
# 如果反思发现某个3步以上的子流程重复出现3次以上:
# → 自动提取为 skill_forge 中的 PROCEDURE 类型技能
# → 下次遇到时直接调用，减少步骤
```

**改造方案:** 在 `reflect_deep` 的输出中增加 "repeated_procedures" 字段，触发 skill_forge 自动提取。

---

### 2.4 meta_evolve.py → 增强元进化系统

**当前实现:** 基于成功率的参数调整 (>70%增加, <30%减少)

**研究融入:**

#### 2.4.1 PromptBreeder 的自指涉进化
> 出处: PromptBreeder (2024), 自指涉 — 进化规则本身也进化

当前meta_evolve的调整规则是硬编码的 (>70% → 增加)。PromptBreeder的思路:

```python
# 不仅进化策略参数，还进化调整规则本身:
# Level 1 (当前): 参数值 (learning_max_per_extraction = 3)
# Level 2 (新增): 调整阈值 (success_threshold = 0.7)
# Level 3 (远期): 调整方向 (应该增加还是减少?)

# 实现: 在 state 中存储 adjustment_rules
"adjustment_rules": {
    "learning": {
        "increase_threshold": 0.7,   # 可被meta-meta调整
        "decrease_threshold": 0.3,
        "step_size": 1,
    },
    ...
}
```

#### 2.4.2 Agent0 的课程-执行者共生竞争
> 出处: Agent0 (2025), 18%数学改进

Agent0 证明了任务难度自动调节的价值:

```python
# 应用到 meta_evolve:
# 如果 goal_tracker 的目标达成率太高 (>90%) → 目标太简单，增加难度
# 如果达成率太低 (<20%) → 目标太难，降低难度
# 这就是 "课程" (curriculum) 的自动调节
```

#### 2.4.3 MAE 的 Proposer-Solver-Judge 三角
> 出处: MAE (2025), 4.54%改进

当前只有 meta_evolve 自己评估自己。MAE 的三角架构:

```python
# Proposer: reflection → 提出改进假说
# Solver: self_edit / prompt_tuner → 实施改进
# Judge: meta_evolve → 评估改进效果
# 三方分工，避免 "球员当裁判"
```

**改造方案:** meta_evolve 的 `analyze_and_adjust()` 中不再自己提出假说，而是从 reflection 的 hypotheses 中获取。

---

### 2.5 prompt_tuner.py → 增强提示调优

**当前实现:** 信号收集 → 随机变体生成 → A/B评估 (5%阈值)

**研究融入:**

#### 2.5.1 OPRO: LLM-as-Optimizer
> 出处: OPRO (2023), 超人类prompt 8% on GSM8K

当前变体生成是随机扰动参数。OPRO证明LLM自身是更好的优化器:

```python
# 当前: 随机选参数随机扰动
# 升级: 将过去5轮的 (参数, 分数) 对喂给LLM
# LLM根据趋势提出下一组参数
# 这比随机搜索更高效，尤其在参数空间大时

def generate_variant_opro(self, mode: str) -> Dict:
    """LLM-guided variant generation."""
    history = self._get_recent_variants(mode, n=5)
    prompt = f"""Based on these prompt parameter experiments:
    {history}
    Suggest the next set of parameters to try.
    Focus on parameters that showed improvement trends."""
    # 调用 LLM → 解析建议 → 生成变体
```

**改造方案:** `generate_variant()` 增加 `method` 参数，支持 "random" (当前) 和 "opro" (LLM引导)。

#### 2.5.2 EvoPrompt 的进化算法
> 出处: EvoPrompt (2024), 遗传算法 + 差分进化

保留表现好的变体基因，淘汰差的:

```python
# 维护一个 "变体种群" (population_size=5)
# 每周:
# 1. 评估所有变体的分数
# 2. 交叉: 取两个最优变体的参数混合
# 3. 变异: 对交叉结果小幅扰动
# 4. 选择: 保留top5，淘汰其余
```

---

### 2.6 self_edit.py → 增强代码自修改

**当前实现:** AST安全检查 → 语法验证 → fork-pytest → git commit → hot reload

**研究融入:**

#### 2.6.1 NemoClaw 的内核级沙箱 (远期)
> 出处: NemoClaw (2025), Landlock + seccomp + network namespace

当前沙箱依赖 Python 级别的黑名单 (FORBIDDEN_CALLS)。NemoClaw 的内核级方案更安全:

```python
# 当前: AST 层面检测 exec/eval/os.system → 可被绕过
# 升级:
# Phase 1 (简单): bubblewrap (bwrap) 包裹 pytest 执行
#   bwrap --ro-bind /app /app --dev /dev --proc /proc \
#         --unshare-net python -m pytest
# Phase 2 (完整): Landlock LSM (Linux 5.13+)
#   - 限制文件系统访问范围
#   - 禁止网络访问
#   - 限制进程创建
```

**改造方案:** `_run_tests_in_fork()` 中增加 bwrap 包裹选项 (如果 bwrap 可用)。

#### 2.6.2 Constitutional AI for Code
> 出处: Anthropic Constitutional AI 理念应用于代码审查

```python
# 在 AST 检查之后，增加 "宪法审查" 步骤:
CODE_CONSTITUTION = [
    "修改不得降低现有测试覆盖率",
    "修改不得引入新的外部依赖",
    "修改必须保持向后兼容",
    "修改不得触及安全相关文件",
    "修改不得超过50行 (单次)",
]
# 每次self-edit前，LLM对照宪法审查修改意图
```

---

### 2.7 cost_optimizer.py → 增强成本优化

**当前实现:** 固定模型路由 + SHA-256响应缓存 + 日预算$0.06

**研究融入:**

#### 2.7.1 RouteLLM 的学习型路由
> 出处: RouteLLM (2024), 85%成本降低

当前路由是硬编码规则 (simple→cheap, complex→expensive)。RouteLLM用机器学习:

```python
# 当前: if complexity == "simple" → deepseek-chat
# 升级: 基于历史数据学习路由策略
# 记录: (task_description, model_used, success, cost)
# 训练简单的 logistic regression:
#   - 特征: task长度, 关键词(code/analyze/chat), mode
#   - 标签: 哪个model成功且最便宜
# 每周重新训练 (sklearn, 不需要GPU)

# 简化实现: 基于 token 计数 + 历史成功率的启发式路由
def recommend_model_adaptive(self, prompt: str, mode: str) -> str:
    token_count = len(prompt.split())
    historical = self._get_model_success_rates(mode)
    # 如果 cheap model 在类似任务上成功率 > 80% → 用 cheap
    # 否则 → 用 expensive
```

**改造方案:** `recommend_model()` 从硬编码升级为数据驱动。

#### 2.7.2 GPTCache 的语义缓存
> 出处: GPTCache, 语义相似度缓存

当前缓存用精确 SHA-256 匹配。语义缓存更智能:

```python
# 当前: hash("How to sort a list?") ≠ hash("What's the way to sort lists?")
# 升级: 用 TF-IDF + 余弦相似度 做模糊匹配
# 阈值: 0.85 (足够相似才复用缓存)
# 不需要向量数据库，sklearn 的 TfidfVectorizer 即可
```

#### 2.7.3 BudgetThinker 的自适应推理深度
> 出处: BudgetThinker (2025), 思考预算自动分配

```python
# 不同任务分配不同的 "思考预算":
# 简单问候: 0 tokens thinking → 直接回复
# 代码修复: 500 tokens thinking → 中等推理
# 架构设计: 2000 tokens thinking → 深度推理
# 通过 max_tokens 和 temperature 控制
```

---

### 2.8 self_unblock.py → 增强自解围

**当前实现:** 6个内置诊断 + LLM生成adhoc脚本 (50行限制, 30s沙箱)

**研究融入:**

#### 2.8.1 CER (Contextual Experience Replay) 的经验回放
> 出处: CER (2025), 31.9% VisualWebArena SOTA

当修复策略成功时，记录完整上下文:

```python
# 存储成功的修复经验:
FIX_EXPERIENCE = {
    "error_signature": "sqlite3.OperationalError: database is locked",
    "diagnosis": "disk_full + WAL checkpoint failure",
    "fix_script": "PRAGMA wal_checkpoint(TRUNCATE); ...",
    "context": {"disk_usage": "95%", "db_size": "50MB"},
    "success": True,
}
# 下次遇到相似错误时，先查经验库，优先复用已验证的修复
```

**改造方案:** 新增 `fix_experiences` 表，`attempt_fix()` 前先查询。与 `skill_forge` 集成 — 成功的修复自动结晶为技能。

---

### 2.9 health_monitor.py + watchdog.py → 增强进程管理

**当前实现:** supervisord + 心跳检测 + boot loop保护 + Telegram告警

**研究融入:**

#### 2.9.1 s6-overlay 替代 supervisord (推荐)
> 出处: Docker最佳实践研究, s6-overlay

```
对比:
  supervisord: Python实现, 30MB内存, 仅限进程管理
  s6-overlay:  C实现, 极低内存占用(具体数值未验证), 原生Docker集成, 有序启动/关闭

推荐: 迁移到 s6-overlay
原因:
  1. 内存占用降低30x
  2. 原生 readiness notification (进程真正就绪才标记)
  3. 有序关闭 (先停 agent, 再停 monitor, 最后停 watchdog)
  4. 更适合容器环境

迁移路径:
  /etc/s6-overlay/s6-rc.d/
    ├── neomind-agent/     (type: longrun)
    ├── health-monitor/    (type: longrun, depends: neomind-agent)
    └── watchdog/          (type: longrun, depends: health-monitor)
```

**优先级: 中** — 当前 supervisord 可用，s6 是优化项。

#### 2.9.2 SQLite WAL 容器陷阱
> 出处: Docker最佳实践研究

```
关键发现: SQLite WAL 模式在 Docker volume mount 到非Linux VM 时可能损坏
原因: macOS/Windows Docker Desktop 使用 VirtioFS/gRPC-FUSE，不支持共享内存锁

解决方案:
  1. 数据库文件放在 Docker volume (不是 bind mount)
  2. 或者使用 PRAGMA journal_mode=DELETE (牺牲并发性能)
  3. 或者确保 /data/neomind/db/ 在容器内部 (不挂载到宿主机)

当前状态: DB_PATH = /data/neomind/db/ — 需确认不在 bind mount 上
```

#### 2.9.3 结构化日志 + 内存profiling
> 出处: Docker最佳实践研究

```python
# 升级: structlog 替代 logging
import structlog
logger = structlog.get_logger()
# 输出 JSON 格式，便于 Docker log driver 解析

# 内存监控: 每小时检查一次
import tracemalloc
tracemalloc.start()
# 如果内存增长超过200MB → 触发告警 + GC
```

---

### 2.10 checkpoint.py → 增强状态管理

**当前实现:** 原子JSON保存/恢复 + 历史日志

**研究融入:**

#### 2.10.1 MemGPT/Letta 的三层记忆 + 上下文管理
> 出处: MemGPT/Letta (2024), 3-tier memory, WARNING at 70%, FLUSH at 100%

```python
# 将 checkpoint 扩展为上下文管理器:
# Tier 1: 工作记忆 (当前对话) — 始终在context中
# Tier 2: 会话记忆 (本次会话的摘要) — 按需加载
# Tier 3: 持久记忆 (learnings/skills) — SQLite查询

# 上下文压力管理:
# tokens_used < 70% max → 正常运行
# tokens_used > 70% → WARNING, 开始摘要旧对话
# tokens_used > 90% → FLUSH, 将旧对话移到 Tier 2, 仅保留摘要
```

**改造方案:** checkpoint 新增 `context_pressure` 字段，scheduler 在 `on_turn_complete` 中检查。

---

## 3. 集成架构

### 3.1 数据流管道

```
┌─────────────────────────────────────────────────────────────────┐
│                        数据流全景                                │
│                                                                  │
│  用户对话 ──┬──→ reflection.reflect_quick() ──→ 快速反思记录      │
│              │                                                    │
│              ├──→ prompt_tuner.record_signal() ──→ 信号收集       │
│              │                                                    │
│              └──→ cost_optimizer.record_call() ──→ 成本记录       │
│                                                                  │
│  错误发生 ──┬──→ reflection.reflect_on_error() ──→ 错误反思      │
│              │         │                                          │
│              │         └──→ hypotheses ──→ goal_tracker (实验目标) │
│              │                                                    │
│              ├──→ learnings.add_error_learning() ──→ 错误学习    │
│              │         │                                          │
│              │         └──→ skill_forge (如果修复成功)            │
│              │                                                    │
│              └──→ self_unblock.diagnose() ──→ 自动修复           │
│                        │                                          │
│                        └──→ fix_experience ──→ skill_forge       │
│                                                                  │
│  每日循环 ──┬──→ auto_evolve.daily_audit() ──→ 指标报告          │
│              │         │                                          │
│              │         └──→ goal_tracker.auto_generate() (低指标) │
│              │                                                    │
│              ├──→ learnings.decay_and_prune() ──→ 记忆维护       │
│              │                                                    │
│              ├──→ prompt_tuner.generate_variant() ──→ 新变体     │
│              │                                                    │
│              └──→ cost_optimizer.cleanup_cache() ──→ 缓存清理    │
│                                                                  │
│  每周循环 ──┬──→ auto_evolve.weekly_retro() ──→ 综合报告        │
│              │                                                    │
│              ├──→ prompt_tuner.evaluate_and_adopt() ──→ 采纳/回滚│
│              │                                                    │
│              ├──→ meta_evolve.analyze_and_adjust() ──→ 策略调整  │
│              │         │                                          │
│              │         └──→ 调整所有引擎的参数                    │
│              │                                                    │
│              ├──→ reflection.reflect_deep() ──→ 深度反思         │
│              │         │                                          │
│              │         ├──→ hypotheses ──→ goal_tracker          │
│              │         └──→ procedures ──→ skill_forge           │
│              │                                                    │
│              └──→ goal_tracker.expire_stale() ──→ 目标过期       │
│                                                                  │
│  Prompt注入 ──→ learnings.get_prompt_injection()                 │
│               + goal_tracker.get_goal_summary()                  │
│               + [NEW] reflection.pre_reflect() (复杂任务前)      │
│               ──→ 注入到系统提示词中                              │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 模块间依赖矩阵

```
               auto  health watch check unblk sedit upgrd learn skill refl  ptune goal  meta  cost  sched dash
auto_evolve     —     —      —     —     —     —     —     —     —    —     —     —     —     —     ←     —
health_monitor  —     —      —     —     —     —     —     —     —    —     —     —     —     —     ←     —
watchdog        —     —      —     —     —     —     —     —     —    —     —     —     —     —     —     —
checkpoint      —     —      —     —     —     —     —     —     —    —     —     —     —     —     ←     —
self_unblock    —     —      —     —     —     —     —     ←     ←    —     —     —     —     —     ←     —
self_edit       —     —      —     —     —     —     —     —     —    —     —     —     ←     ←     ←     —
upgrade         —     —      —     —     —     —     —     —     —    —     —     —     —     —     —     —
learnings       —     —      —     —     —     —     —     —     —    —     —     —     —     —     ←     ←
skill_forge     —     —      —     —     —     —     —     —     —    —     —     —     —     —     ←     ←
reflection      —     —      —     —     —     —     —     ←     ←    —     —     ←     ←     —     ←     ←
prompt_tuner    —     —      —     —     —     —     —     —     —    —     —     —     ←     —     ←     ←
goal_tracker    —     —      —     —     —     —     —     —     —    ←     —     —     ←     —     ←     ←
meta_evolve     —     —      —     —     —     —     —     —     —    —     —     —     —     —     ←     ←
cost_optimizer  —     —      —     —     —     —     —     —     —    —     —     —     —     —     ←     ←
scheduler       →     →      →     →     →     —     —     →     →    →     →     →     →     →     —     —
dashboard       →     —      —     —     —     —     —     →     →    →     →     →     →     →     —     —

→ = 依赖   ← = 被依赖   — = 无直接依赖
```

**关键约束:**
- `scheduler` 是唯一的跨模块调用者 (所有依赖通过 scheduler 协调)
- 各引擎之间**无直接依赖** (松耦合)
- `reflection` 产出流向 `goal_tracker` 和 `skill_forge`，但通过 scheduler 中转
- `meta_evolve` 读取所有引擎的 outcomes，但不直接调用它们

### 3.3 SQLite 数据库布局

```
/data/neomind/db/
├── learnings.db        [learnings.py]
│   ├── learnings           — 结构化学习条目
│   └── learning_events     — 回忆/使用事件
│
├── skills.db           [skill_forge.py]
│   ├── skills              — 技能定义+生命周期
│   └── skill_usage         — 使用记录
│
├── reflections.db      [reflection.py]
│   ├── reflections         — 反思记录
│   └── improvement_hypotheses — 改进假说
│
├── goals.db            [goal_tracker.py]
│   └── goals               — 自主改进目标
│
├── cost_tracking.db    [cost_optimizer.py]
│   ├── api_calls           — API调用记录
│   └── response_cache      — 响应缓存
│
└── [NEW] fix_experiences.db [self_unblock.py]
    └── fix_experiences     — 成功修复的经验

/data/neomind/evolution/
├── meta_state.json     [meta_evolve.py]
├── meta_history.jsonl  [meta_evolve.py]
├── checkpoint.json     [checkpoint.py]
├── checkpoint_history.jsonl [checkpoint.py]
├── health_state.json   [health_monitor.py]
└── prompt_configs/     [prompt_tuner.py]
    ├── chat.yaml
    ├── coding.yaml
    └── fin.yaml

/data/neomind/skills/   [skill_forge.py]
├── skill_001.py
├── skill_001.md
└── ...
```

### 3.4 Docker 部署拓扑

```
┌─────────────────────────────────────────────────┐
│           Docker Container: neomind              │
│                                                  │
│  ┌─────────┐                                    │
│  │  tini   │  PID 1 (signal forwarding)         │
│  └────┬────┘                                    │
│       │                                          │
│  ┌────┴─────────────────────────────────┐       │
│  │          supervisord / s6-overlay     │       │
│  └────┬──────────┬──────────┬───────────┘       │
│       │          │          │                    │
│  ┌────┴────┐ ┌───┴────┐ ┌──┴──────┐            │
│  │ Agent   │ │ Health │ │Watchdog │            │
│  │ Process │ │Monitor │ │        │            │
│  │         │ │  :18791│ │        │            │
│  └────┬────┘ └───┬────┘ └──┬─────┘            │
│       │          │          │                    │
│       ▼          ▼          ▼                    │
│  /data/neomind/ (Docker volume, 持久化)         │
│  ├── db/         (SQLite databases)             │
│  ├── evolution/  (JSON/YAML state)              │
│  ├── skills/     (crystallized skill files)     │
│  ├── crash_log/  (crash reports)                │
│  └── logs/       (structured logs)              │
│                                                  │
│  /app/ (代码, git repo, 可self-edit)            │
│                                                  │
│  Exposed: 18790 (Telegram bot), 18791 (health)  │
└─────────────────────────────────────────────────┘
```

---

## 4. 分阶段实施路线图

### Phase 1: 基础稳固 (Week 1-2)

**目标: 确保现有17模块可以正确启动并协作**

| 任务 | 涉及模块 | 优先级 | 估时 |
|------|---------|--------|------|
| 编写所有模块的 `__init__` + 导入测试 | 全部 | P0 | 2h |
| scheduler 集成测试 (mock所有引擎) | scheduler | P0 | 3h |
| SQLite 数据库初始化脚本 | learnings, skills, reflection, goals, cost | P0 | 1h |
| Docker volume 挂载验证 (WAL安全) | 全部DB | P0 | 1h |
| supervisord → agent/monitor/watchdog 三进程启动 | health_monitor, watchdog | P0 | 2h |
| Telegram 告警端到端测试 | health_monitor | P0 | 1h |
| checkpoint save/restore 端到端测试 | checkpoint | P1 | 1h |
| self_unblock 6个诊断器测试 | self_unblock | P1 | 2h |
| self_edit AST安全 + git commit 测试 | self_edit | P1 | 2h |

**交付: NeoMind 可以稳定启动、心跳正常、异常时自动告警**

### Phase 2: 认知层激活 (Week 3-4)

**目标: 激活学习、技能、反思三引擎**

| 任务 | 涉及模块 | 优先级 | 估时 |
|------|---------|--------|------|
| learnings: 集成到 on_error 和 on_session_end | learnings, scheduler | P0 | 2h |
| learnings: FOREVER 自适应衰减实现 | learnings | P1 | 2h |
| learnings: prompt injection 格式化+测试 | learnings | P0 | 1h |
| skill_forge: 集成 forge_from_error_fix 到 on_error | skill_forge, scheduler | P0 | 2h |
| skill_forge: 双技能库 (general/task_specific) | skill_forge | P2 | 2h |
| reflection: quick反思集成到每轮 | reflection, scheduler | P0 | 1h |
| reflection: 新增 pre_reflect() (PreFlect) | reflection | P1 | 3h |
| reflection: 错误反思 → hypothesis → goal 管道 | reflection, goal_tracker | P1 | 2h |
| prompt_tuner: 信号收集 + 首个变体生成 | prompt_tuner | P1 | 2h |
| 日循环完整测试 | scheduler | P0 | 2h |

**交付: NeoMind 能从错误中学习、从成功中提炼技能、持续反思**

### Phase 3: 主动进化 (Week 5-6)

**目标: 激活目标追踪、提示调优、代码自修改**

| 任务 | 涉及模块 | 优先级 | 估时 |
|------|---------|--------|------|
| goal_tracker: 从 daily_audit 指标自动生成目标 | goal_tracker, auto_evolve | P1 | 2h |
| goal_tracker: 从 reflection hypotheses 生成实验目标 | goal_tracker, reflection | P1 | 2h |
| goal_tracker: prompt summary 注入 | goal_tracker, scheduler | P1 | 1h |
| prompt_tuner: 周评估 + 采纳/回滚完整流程 | prompt_tuner | P1 | 3h |
| prompt_tuner: OPRO LLM引导变体生成 | prompt_tuner | P2 | 3h |
| self_edit: 完整管道端到端测试 | self_edit | P1 | 3h |
| self_edit: bwrap 沙箱增强 | self_edit | P2 | 2h |
| cost_optimizer: 自适应模型路由 | cost_optimizer | P2 | 3h |
| cost_optimizer: 语义缓存 (TF-IDF) | cost_optimizer | P3 | 3h |
| 周循环完整测试 | scheduler | P0 | 2h |

**交付: NeoMind 主动设定目标、调优提示词、安全修改代码**

### Phase 4: 元进化 + 加固 (Week 7-8)

**目标: 激活元层、优化Docker部署、安全加固**

| 任务 | 涉及模块 | 优先级 | 估时 |
|------|---------|--------|------|
| meta_evolve: 周分析 + 策略调整 | meta_evolve | P1 | 2h |
| meta_evolve: PromptBreeder 自指涉 (规则也进化) | meta_evolve | P2 | 3h |
| meta_evolve: MAE 三角架构 (从reflection获取假说) | meta_evolve, reflection | P2 | 2h |
| dashboard: 集成所有引擎的 get_stats() | dashboard | P2 | 3h |
| self_unblock: 修复经验库 + skill_forge 集成 | self_unblock, skill_forge | P2 | 3h |
| 安全审计: skill prompt injection 防护 | skill_forge | P1 | 2h |
| 安全审计: self_edit 宪法审查 | self_edit | P2 | 2h |
| Docker: s6-overlay 迁移评估 | Dockerfile | P3 | 4h |
| Docker: structlog 结构化日志 | 全部 | P3 | 2h |
| Docker: 内存profiling + 告警 | health_monitor | P3 | 2h |
| 全系统集成测试 (1天模拟运行) | 全部 | P0 | 4h |

**交付: 完整的自进化系统，经过安全审计和压力测试**

---

## 5. 关键设计决策

### 5.1 为什么用 scheduler 中心化调度而非事件驱动?

**选择: 中心化 scheduler**

理由:
1. 可预测性: 所有进化活动的执行时机明确
2. 可控性: safe mode 一键关闭所有进化
3. 可审计性: actions_taken 列表完整记录了每次执行
4. 简单性: 无需事件总线/消息队列基础设施

代价:
- scheduler.py 是单点，需要额外关注其稳定性
- 新模块必须在 scheduler 中注册

### 5.2 为什么所有引擎都是 lazy-init?

**选择: 所有引擎在首次使用时才初始化**

理由:
1. 启动速度: agent 启动不需要加载所有引擎
2. 容错: 任何引擎初始化失败不阻塞主流程
3. 内存: 不使用的引擎不占内存
4. 模块化: 可以独立部署/测试每个引擎

### 5.3 为什么 Ebbinghaus 而不是简单的 FIFO/LRU?

**选择: Ebbinghaus 遗忘曲线 + 自适应λ(n)**

理由:
1. 符合人类记忆模型: 常用知识保留，冷知识衰减
2. 自动平衡: 无需手动设置保留数量
3. 研究支持: FOREVER 论文验证了该方法在 LLM agents 上的效果
4. 渐进式: 不会突然丢失知识 (与硬截断不同)

### 5.4 为什么 Git-Gated Self-Edit 而不是 apply_patch?

**选择: 每次自编辑都是 git commit**

理由:
1. 完整审计轨迹: 每次修改都有历史
2. 原子回滚: git revert 即可撤销
3. diff可视化: 便于用户审查
4. 与 upgrade.py 兼容: 同一个 git repo

### 5.5 为什么三独立进程 (agent + monitor + watchdog)?

**选择: supervisord 管理三个独立进程**

理由:
1. 故障隔离: agent 崩溃不影响 monitor 告警
2. 层层保护: monitor 检测 agent 挂起, watchdog 检测 monitor 挂起
3. Docker-friendly: tini 作为 PID 1 处理信号
4. 可观测性: 每个进程独立日志

---

## 6. 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| Self-edit 引入bug | 中 | 高 | AST安全 + pytest沙箱 + git回滚 + 10次/天限制 |
| SQLite WAL 在 Docker volume 损坏 | 低 | 高 | DB放在容器内volume (不bind mount)，定期VACUUM |
| 进化overhead超预算 | 中 | 低 | cost_optimizer $0.06/day硬限 + meta_evolve自调节 |
| 技能库prompt injection | 低 | 高 | 信任分级 + 内容审查 + 仅限自生成技能 |
| Boot loop (快速反复重启) | 低 | 高 | 3次/5分钟检测 → safe mode + Telegram告警 |
| 记忆膨胀 (学习+技能过多) | 中 | 中 | Ebbinghaus衰减 + ReMe效用剪枝 + 每日清理 |
| 反思过度 (浪费token) | 中 | 低 | quick反思零成本 + deep反思仅周一次 + 预算控制 |
| scheduler 崩溃 | 极低 | 高 | 全方法 try/except + health_monitor独立检测 |

---

## 7. 研究参考文献总表

### 记忆系统
| 论文/项目 | 关键贡献 | 应用到的模块 |
|-----------|---------|-------------|
| FOREVER (2025) | 自适应Ebbinghaus λ(n) = λ₀×(1−β×tanh(γ×n)) | learnings |
| SimpleMem (2025) | 语义压缩, 26.4% F1↑, 30x token↓ | learnings |
| ReMe (2025) | 效用剪枝 (threshold=0.3), compact_ratio=0.7 | learnings |
| A-MEM (2025) | Zettelkasten语义链接, ChromaDB | learnings (远期) |
| MemGPT/Letta (2024) | 三层记忆, 上下文压力管理 | checkpoint |
| CER (2025) | 上下文经验回放, 31.9% SOTA | self_unblock |

### 技能系统
| 论文/项目 | 关键贡献 | 应用到的模块 |
|-----------|---------|-------------|
| VOYAGER (2023) | 可执行技能验证 | skill_forge |
| SkillRL (2025) | 双技能库, 15.3%↑, token压缩 | skill_forge |
| SkillsBench (2025) | 聚焦>全面, 自生成技能无益 | skill_forge |
| SkillRouter (2025) | Top-1路由仅64% → 技能路由难 | skill_forge |
| arXiv:2510.26328 | 技能prompt injection攻击 | skill_forge安全 |

### 反思系统
| 论文/项目 | 关键贡献 | 应用到的模块 |
|-----------|---------|-------------|
| Reflexion (2023) | 滑动窗口3, 最优2-5次迭代, 91% HumanEval | reflection |
| PreFlect (2026) | 前瞻性反思 (事前), 11-17%↑ | reflection |
| AutoRefine (2026) | 子代理提取, 20-73%步骤↓ | reflection → skill_forge |
| LATS (2023) | MCTS + LLM评估, 92.7% HumanEval | reflection (远期) |
| Self-Refine (2023) | 迭代细化, 零样本 | reflection |

### 元进化
| 论文/项目 | 关键贡献 | 应用到的模块 |
|-----------|---------|-------------|
| PromptBreeder (2024) | 自指涉 — 变异规则也进化 | meta_evolve |
| OPRO (2023) | LLM作为优化器, +8% GSM8K | prompt_tuner |
| Agent0 (2025) | 课程-执行者共生, +18%数学 | meta_evolve |
| MAE (2025) | Proposer-Solver-Judge三角 | meta_evolve |
| EvoPrompt (2024) | 遗传算法+差分进化 | prompt_tuner |

### 成本与安全
| 论文/项目 | 关键贡献 | 应用到的模块 |
|-----------|---------|-------------|
| RouteLLM (2024) | 学习型路由, 85%成本↓ | cost_optimizer |
| GPTCache (2023) | 语义缓存 | cost_optimizer |
| BudgetThinker (2025) | 自适应推理深度 | cost_optimizer |
| NemoClaw (2025) | Landlock+seccomp沙箱 | self_edit (远期) |
| Constitutional AI | 宪法审查理念 | self_edit |

### Docker/基础设施
| 项目/实践 | 关键贡献 | 应用到的模块 |
|-----------|---------|-------------|
| s6-overlay | 极低内存(未验证具体值), 有序启停, 原生Docker | health_monitor, watchdog |
| SQLite WAL gotcha | 非Linux VM挂载风险 | 所有DB模块 |
| structlog | JSON结构化日志 | 全局 |
| tracemalloc | 内存泄漏检测 | health_monitor |

---

## 8. 成功指标

| 指标 | 基线 (无进化) | Phase 2 目标 | Phase 4 目标 |
|------|-------------|-------------|-------------|
| 任务成功率 | ~80% | 85% | 90%+ |
| 错误重复率 | 无数据 | <30% | <15% |
| 平均响应质量 (用户满意度) | ~0.6 | 0.7 | 0.8+ |
| 进化日开销 | $0 | <$0.03 | <$0.06 |
| 知识库有效条目 | 0 | 50+ | 200+ |
| 活跃技能数 | 0 | 10+ | 30+ |
| 目标达成率 | N/A | 30% | 50%+ |
| 不间断运行时间 | 数小时 | 24h | 7d+ |
| 启动循环检测 | 无 | 3次/5分钟 | 3次/5分钟 |

---

## 9. 下一步行动

1. **立即 (今天):** 运行所有 `py_compile` 检查，确保17个模块语法无误
2. **本周:** Phase 1 全部完成 — 基础稳固，三进程可启动
3. **下周:** Phase 2 开始 — 认知层激活
4. **持续:** 每周review进化指标，meta_evolve 自动调参

---

> 本文档是 NeoMind 自我进化系统的 **活文档**。
> 随着系统运行和学习，本计划会根据 meta_evolve 的分析结果持续更新。
