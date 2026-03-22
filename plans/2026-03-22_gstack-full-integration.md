# NeoMind × gstack 完整融合计划

> 目标：将 gstack 的 27 个 skill 和架构模式 100% 消化为 NeoMind 的能力，
> 而非照搬代码。NeoMind 有自己的灵魂：三人格（chat/coding/fin）、
> 个人助手身份、零泄露隐私、自我进化、全量日志。

## 🏗 当前状态诊断

### 已完成（~60%）
- SKILL.md loader + 11 个 skill 文件
- Browser daemon (Playwright, 40+ commands, @ref system)
- Safety guards (/careful /freeze /guard)
- Sprint framework (7-phase, per-mode)
- Evidence trail (append-only JSONL)
- Self-audit engine (6-cycle)
- Provider sync (xbar ↔ Telegram, bidirectional)

### 致命问题
1. **测试全线崩溃** — 85% 的测试因 `aiohttp` import 失败无法运行
2. **功能未接入** — Skills/Sprint/Evidence/Guards 定义了但没插入 agent 主循环
3. **Skill 是空壳** — investigate/qa/ship/office-hours 只有描述没有实现
4. **三人格无差异** — 除了 system prompt 不同，行为层面几乎一样
5. **跨人格不共享** — chat 学到的偏好 coding 不知道
6. **日志不完整** — CLI 模式无持久化，evidence trail 只 Telegram 用
7. **自我进化是死的** — audit/self-iteration 有代码但从未被触发

### gstack 缺失的 skills
| gstack skill | NeoMind 状态 | 优先级 |
|---|---|---|
| /cso (安全审计) | ❌ 不存在 | P1 — fin 和 coding 都需要 |
| /retro (回顾) | ❌ 不存在 | P2 — 自我进化核心 |
| /benchmark (性能) | ❌ 不存在 | P3 — coding 需要 |
| /canary (部署监控) | ❌ 不存在 | P3 — coding 需要 |
| /codex (跨模型审查) | ❌ 不存在 | P4 — nice to have |
| /autoplan (顺序编排) | ❌ 不存在 | P2 — 三人格协同 |
| /land-and-deploy | ❌ 不存在 | P3 — /ship 的延伸 |
| /document-release | ❌ 不存在 | P4 |
| /setup-browser-cookies | ❌ 不存在 | P3 — browse 增强 |
| /design-consultation | ❌ 不存在 | P4 |
| /plan-ceo-review | ❌ 不存在 | P4 — 改为 /plan-review |
| /gstack-upgrade | ❌ 不存在 | P1 — 自我进化核心 |

---

## NeoMind 核心原则（不可妥协）

1. **三人格各有所长，互有共享**
   - chat: 日常对话、信息搜索、生活规划 → 共享记忆给 fin/coding
   - coding: 开发、部署、调试、代码审查 → 共享工具给 chat/fin
   - fin: 投资分析、交易验证、风险管理 → 共享数据分析给 chat/coding

2. **100% 个人助手，零泄露**
   - 所有 API 调用走本地 LiteLLM 代理（可切换）
   - 敏感数据（portfolio、credentials）AES-256 加密存储
   - 日志本地存储，不外传
   - system prompt 里不包含个人信息，个人信息存 secure_memory

3. **自我进化**
   - 定期自审计（不是手动触发，是自动的）
   - 从对话中学习偏好并持久化
   - 代码自检 + 自修复
   - 版本自升级能力

4. **全量日志**
   - 每一次 LLM 调用、命令执行、文件操作都记录
   - 日志持久化、可追溯、可搜索
   - 按天归档，支持回看

---

## Phase 1: 修复基础设施（让已有代码真正工作）

### 1.1 修复测试体系
- **问题**: `from agent.core import NeoMindAgent` 触发 aiohttp 全量导入
- **方案**:
  - workflow/ 模块零外部依赖（纯 Python stdlib）
  - 测试用 `importlib` 隔离导入（provider_state 已验证此模式）
  - 为每个 workflow 模块写独立测试
- **验收**: `pytest tests/ -x` 全绿

### 1.2 将 workflow 接入 agent 主循环
- **Sprint**: LLM 推理前自动注入当前 sprint 上下文到 system prompt
- **Guards**: 每次命令执行前自动调用 `check_command()`，file edit 前调用 `check_file_edit()`
- **Evidence**: 每次 LLM 调用、文件操作、命令执行都自动写 evidence trail
- **Review**: 每个 sprint 的 review phase 自动加载对应 skill 的 review prompt
- **目标**: 从"有代码但没用"变成"默认启用，无感运行"

### 1.3 修复 Skill 空壳
- investigate → 接入 browser daemon + grep/find，输出结构化根因分析
- qa → 接入 browser daemon，生成回归测试并执行
- ship → 接入 git，自动 PR + test + changelog
- office-hours → 接入 chat mode，6 个 forcing questions 自动引导

---

## Phase 2: 融合缺失的 gstack Skills（NeoMind 化）

### 2.1 /cso → NeoMind 安全审计（所有人格共享）
- gstack 原版: OWASP Top 10 + STRIDE，仅扫代码
- NeoMind 化:
  - coding: 代码安全审计（OWASP + 依赖扫描）
  - fin: 交易安全审计（API key 泄露、仓位异常、wash sale 检测）
  - chat: 隐私审计（对话中是否意外泄露个人信息）
- 输出: 安全报告 Markdown + severity 评分

### 2.2 /retro → NeoMind 回顾（自我进化驱动）
- gstack 原版: 团队回顾，per-person metrics
- NeoMind 化:
  - 自动汇总本周的 sprint、对话、操作
  - 分析成功/失败模式
  - 生成改进建议并写入 `~/.neomind/evolution/retro-{date}.md`
  - 下周 system prompt 自动加载上周回顾摘要
- 触发: 每周日自动 + 手动 `/retro`

### 2.3 /autoplan → NeoMind 三人格协同
- gstack 原版: CEO → Design → Eng 顺序审查
- NeoMind 化:
  - chat 先理解需求（用户意图）
  - coding 评估技术可行性
  - fin 评估成本/ROI（如果涉及投资决策）
  - 三者各出意见，合并为最终计划
- 实现: `workflow/autoplan.py`，串行调用三人格的 review prompt

### 2.4 /benchmark → NeoMind 性能基准（coding 专属）
- 接入 browser daemon 做 Core Web Vitals 测量
- 记录历史基准，检测退化
- 输出: 性能报告 + 趋势图

### 2.5 /canary → NeoMind 部署监控（coding 专属）
- 部署后自动打开生产 URL
- Browser daemon 执行 smoke test
- 检查错误日志
- 持续 5 分钟监控，异常立刻告警

### 2.6 /neomind-upgrade → 自我升级（替代 /gstack-upgrade）
- 检测 git 仓库是否有新 commit
- 对比 CHANGELOG
- 安全升级（备份 → pull → test → 回滚如果失败）
- Docker 容器自动重建

---

## Phase 3: 三人格深度差异化 + 跨人格共享记忆

### 3.1 共享记忆层 (`memory/shared_memory.py`)
- SQLite 数据库: `~/.neomind/shared_memory.db`
- 表结构:
  - `preferences`: 用户偏好（语言、格式、时区 等）
  - `facts`: 用户事实（公司、角色、项目 等）
  - `patterns`: 行为模式（常用命令、常查股票 等）
  - `feedback`: 用户反馈（点赞/修正/投诉）
- 所有人格可读写，写入时标记来源人格
- 读取时优先本人格数据，其次共享

### 3.2 人格行为差异化
- **chat**:
  - 默认对话式输出（不用 bullet）
  - 主动记住用户偏好（叫什么名字、什么语气）
  - 搜索结果做摘要，不原样转发
  - 新增: /remind, /todo, /schedule 生活助手能力

- **coding**:
  - 默认结构化输出（代码块、diff）
  - Sprint 自动激活（每个任务自动创建 sprint）
  - Guards 默认开启（/careful 默认 on）
  - Review 自动触发（每次 commit 前）
  - 新增: /perf, /deploy, /monitor

- **fin**:
  - 默认谨慎语气（涉及钱的事不能随便）
  - 每笔交易必须过 trade-review（不可跳过）
  - 数据来源必须标注
  - Paper trading 默认先行
  - 新增: /backtest, /risk, /allocation

### 3.3 人格间协作协议
- chat 检测到编程需求 → 建议 `/mode coding`
- coding 检测到投资相关 → 建议 `/mode fin`
- fin 需要跑代码分析 → 内部调用 coding 的工具（不切换 mode）
- 所有人格都能调 browser daemon

---

## Phase 4: 自我进化闭环

### 4.1 自动审计 (`evolution/auto_audit.py`)
- Bot 启动时运行 cycle 1-2（轻量级）
- 每天午夜运行 cycle 3-4（中量级）
- 每周日运行 cycle 5-6（重量级）
- 发现 critical issue 自动通过 Telegram 通知用户

### 4.2 学习反馈循环
- 用户修正 → 记录到 shared_memory.feedback
- 每周 /retro 分析反馈模式
- 高频修正 → 自动调整 system prompt 参数
- 例: 用户连续 3 次说"太长了" → 降低 max_tokens 偏好

### 4.3 代码自检 + 自修复
- self_iteration.py 已有代码，需要:
  - 每次 `docker compose up` 时触发一轮检查
  - 发现 import error / syntax error → 自动修复并记录
  - 发现 deprecated API → 标记 TODO 并通知

### 4.4 版本自升级
- `/neomind-upgrade` 命令
- 检测 origin/main 新 commit
- 显示 diff 摘要让用户确认
- 自动 `git pull` + `docker compose build` + 回滚机制

---

## Phase 5: 全量日志 + 隐私加固

### 5.1 统一日志层 (`logging/unified_logger.py`)
- 所有 LLM 调用（请求 + 响应 + tokens + latency）
- 所有命令执行（input + output + exit code）
- 所有文件操作（read/write/delete + path + size）
- 所有 provider 切换
- 格式: JSONL，按天归档到 `~/.neomind/logs/YYYY-MM-DD.jsonl`
- CLI 和 Telegram 统一使用
- 查询: `/logs today`, `/logs search <keyword>`, `/logs stats`

### 5.2 日志安全
- 敏感内容自动脱敏（API key → `sk-***`, 密码 → `***`）
- 日志文件权限 600（仅用户可读）
- 可选: AES 加密日志文件

### 5.3 隐私加固
- 每次 LLM 请求前扫描: 是否包含手机号/邮箱/身份证/银行卡
- 发现 PII → 替换为 placeholder，日志记录原始值到加密存储
- 用户可选: `/privacy strict` (自动脱敏) / `/privacy normal` (仅警告)

---

## 实现顺序 & 预估

| Phase | 范围 | 核心文件 | 新增测试 |
|---|---|---|---|
| 1 | 修复基础 | core.py, workflow/*.py, tests/ | 40+ |
| 2 | 新 Skills | skills/shared/cso/, workflow/retro.py, autoplan.py | 30+ |
| 3 | 人格差异化 | memory/shared_memory.py, config/*.yaml | 20+ |
| 4 | 自我进化 | evolution/*.py, neomind-upgrade | 15+ |
| 5 | 日志+隐私 | logging/unified_logger.py, privacy.py | 20+ |

---

## 与 gstack 27 skills 的最终映射

| gstack skill | NeoMind 对应 | 归属人格 |
|---|---|---|
| /office-hours | /office-hours (chat) | chat + fin |
| /plan-ceo-review | /autoplan phase 1 | shared |
| /plan-eng-review | /autoplan phase 2 | coding |
| /plan-design-review | /autoplan phase 3 | coding |
| /design-consultation | /autoplan 子流程 | coding |
| /autoplan | /autoplan | shared |
| /review | /review (eng-review) | coding |
| /investigate | /investigate | shared |
| /design-review | browser + screenshot + diff | coding |
| /codex | /cross-review (可选) | coding |
| /qa | /qa | coding |
| /qa-only | /qa --readonly | coding |
| /cso | /security-audit | shared |
| /ship | /ship | coding |
| /land-and-deploy | /deploy | coding |
| /canary | /monitor | coding |
| /document-release | /ship 子步骤 | coding |
| /benchmark | /perf | coding |
| /browse | /browse | shared |
| /setup-browser-cookies | /browse --import-cookies | shared |
| /careful | /careful | shared |
| /freeze | /freeze | shared |
| /guard | /guard | shared |
| /unfreeze | /unfreeze | shared |
| /retro | /retro | shared |
| /gstack-upgrade | /neomind-upgrade | shared |
| — (NeoMind 独有) | /trade-review | fin |
| — (NeoMind 独有) | /finance-briefing | fin |
| — (NeoMind 独有) | /qa-trading | fin |
| — (NeoMind 独有) | /backtest | fin |
| — (NeoMind 独有) | /risk | fin |
| — (NeoMind 独有) | /privacy | shared |
| — (NeoMind 独有) | /logs | shared |

**总计: 33 skills（gstack 27 + NeoMind 独有 6）**
