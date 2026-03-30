# NeoMind 进化计划补充 v4.1 — 运维/合规/LLM无关/零停机

> 日期: 2026-03-28
> 补充: v4.0 增强进化计划的技术深化
> 关注: 零停机重启、LLM无关设计、法律合规、资源管理、后台监控

---

## A. 宿主机资源管理

### A.1 Mac Studio 配置参考

Mac Studio 常见配置 (用户以后可能换电脑，因此 NeoMind 必须自适应):

| 配置 | M2 Max | M2 Ultra | M4 Max |
|------|--------|----------|--------|
| CPU | 12核 | 24核 | 16核 |
| GPU | 38核 | 76核 | 40核 |
| 统一内存 | 32-96GB | 64-192GB | 36-128GB |
| SSD | 512GB-8TB | 1-8TB | 512GB-8TB |

**关键约束: Docker Desktop for Mac 默认分配:**
- 内存: 主机内存的 50% (如 64GB 主机 → Docker 可用 ~32GB)
- CPU: 主机全部核心
- 磁盘: 共享主机 SSD

**NeoMind 自适应策略:**

```yaml
# base.yaml → host 配置已添加

# NeoMind 启动时应该:
# 1. 检测可用内存: /proc/meminfo (容器内) 或 Docker API
# 2. 检测 CPU 核心数: /proc/cpuinfo
# 3. 动态调整:
#    - docker memory limit = 2GB → 保守模式 (当前)
#    - docker memory limit = 4GB+ → 可以加载更多库 (pandas, scikit-learn)
#    - docker memory limit = 8GB+ → 可以运行本地小型模型
```

**如何不让 Docker 爆掉:**

```yaml
# docker-compose.yml 中已有:
deploy:
  resources:
    limits:
      memory: 2G    # 硬上限, 超过会被 OOM-killed

# 额外防护 (需要添加):
# 1. data-collector 进程内存监控
#    - 每次 ETL 后检查 RSS (Resident Set Size)
#    - 如果 > 200MB → 释放 pandas DataFrame, gc.collect()
#    - 如果 > 300MB → 停止收集, 发 Telegram 告警
# 2. Agent 进程 context 压缩
#    - 已有 context warning_threshold: 0.61
#    - 需要增加内存层面的压力检测
```

**换电脑时需要做什么:**

```
1. Docker volume 迁移:
   docker run --rm -v neomind-data:/data -v $(pwd):/backup \
     alpine tar czf /backup/neomind-data.tar.gz /data

2. 在新电脑恢复:
   docker run --rm -v neomind-data:/data -v $(pwd):/backup \
     alpine tar xzf /backup/neomind-data.tar.gz -C /

3. 更新 base.yaml 中的 host.machine 字段
4. NeoMind 下次启动时自动检测新硬件
```

---

## B. 法律合规框架

### B.1 数据收集合规矩阵

| 数据源 | 合法性 | 限制 | NeoMind必须做的 |
|--------|--------|------|----------------|
| **Finnhub** | ✅ 合法 (官方API) | 60 req/min, 非商业用途 | 遵守 rate limit, 仅个人分析 |
| **YFinance** | ⚠️ 灰色地带 (非官方) | 无明确限制, 但随时可能被封 | 作为备用, 不依赖; 保守 rate limit |
| **FRED** | ✅ 合法 (公共数据) | 10 req/sec, 不可镜像 | 遵守 rate limit, 不批量下载 |
| **CoinGecko** | ✅ 合法 (官方API) | 30 req/min, 需标注来源 | 显示 "Powered by CoinGecko API" |
| **SEC EDGAR** | ✅ 合法 (公共数据) | 10 req/sec, 高效脚本 | 遵守 rate limit, 按需下载 |
| **Alpha Vantage** | ✅ 合法 (官方API) | 5 req/min, 25 req/day | 极保守使用, 仅补充数据 |
| **AKShare** | ⚠️ 需注意 | L1数据自由, L2需100K账户 | 仅使用 Level-1 公开数据 |

### B.2 合规红线 (绝对不可触碰)

```python
COMPLIANCE_RED_LINES = [
    # 1. 身份欺骗
    "不可创建虚假账号绕过 API 限制",
    "不可伪造 User-Agent 或 IP 地址",
    "不可使用他人的 API Key",

    # 2. 数据滥用
    "不可将收集的原始数据转售或商业分发",
    "不可将数据用于操纵市场",
    "不可收集或存储他人的个人金融信息",

    # 3. 投资建议
    "不可声称自己是注册投资顾问 (RIA)",
    "不可向第三方提供有偿投资建议",
    "不可承诺投资回报率",

    # 4. 技术越界
    "不可绕过网站认证或访问控制 (CFAA)",
    "不可对任何网站进行 DDoS 或过度请求",
    "不可爬取 robots.txt 禁止的路径",
]
```

### B.3 合规自检 (写入 data-collector)

```python
class ComplianceChecker:
    """每次 API 调用前运行合规检查。"""

    def pre_request_check(self, source: str, endpoint: str) -> bool:
        """返回 True 表示可以请求, False 表示阻止。"""
        # 1. Rate limit 检查
        if self.rate_limiter.is_exceeded(source):
            logger.warning(f"Rate limit reached for {source}, skipping")
            return False

        # 2. 每日配额检查
        if self.daily_quota.is_exceeded(source):
            logger.warning(f"Daily quota reached for {source}")
            return False

        # 3. API Key 有效性
        if not self.has_valid_key(source):
            logger.error(f"No valid API key for {source}")
            return False

        return True

    def post_response_check(self, response) -> None:
        """检查响应是否包含合规问题。"""
        # 如果收到 429 (Rate Limited) → 自动增加间隔
        if response.status_code == 429:
            self.rate_limiter.backoff(source, factor=2)
            logger.warning(f"Rate limited by {source}, backing off")

        # 如果收到 403 (Forbidden) → 停止该源
        if response.status_code == 403:
            self.disable_source(source, reason="Access denied")
            self._alert_user(f"数据源 {source} 拒绝访问, 已自动停用")
```

---

## C. 零停机重启与热更新

### C.1 问题定义

NeoMind 需要在以下场景中保持对话不中断:

1. **代码自修改后的重新加载** (self_edit → importlib.reload)
2. **配置变更后的热更新** (prompt_tuner → YAML 重载)
3. **进程崩溃后的自动恢复** (supervisord restart)
4. **Docker 容器重建** (docker compose up --build)

### C.2 热更新架构

```
┌─────────────────────────────────────────────────────────────┐
│                  零停机更新策略                                │
│                                                              │
│  Level 1: importlib.reload (模块级热加载)                     │
│  ├── 适用: Python 模块的代码修改                              │
│  ├── 延迟: ~100ms                                            │
│  ├── 影响: 无 — 当前对话继续, 下次调用使用新代码              │
│  └── 回滚: import 旧模块, 或 git revert                     │
│                                                              │
│  Level 2: YAML 重载 (配置级热更新)                            │
│  ├── 适用: system prompt, 模型选择, 温度等配置变更            │
│  ├── 延迟: ~50ms                                             │
│  ├── 影响: 下一轮对话使用新配置                               │
│  └── 回滚: 从 checkpoint 恢复旧配置                          │
│                                                              │
│  Level 3: supervisord restart (进程级重启)                    │
│  ├── 适用: 新增依赖库, 数据库 schema 变更                    │
│  ├── 延迟: 5-15s                                             │
│  ├── 影响: 当前对话中断, 但 checkpoint 保存了上下文           │
│  ├── 保证: Telegram bot 重启后自动恢复, 用户可继续对话       │
│  └── 回滚: supervisord restart 回到上一版本                  │
│                                                              │
│  Level 4: docker compose restart (容器级重启)                │
│  ├── 适用: Dockerfile 变更, 系统库更新                       │
│  ├── 延迟: 30-120s                                           │
│  ├── 影响: 所有进程中断, 但 volume 数据保留                   │
│  ├── 保证: checkpoint 恢复完整对话上下文                     │
│  └── 回滚: docker compose up --build 用旧代码                │
│                                                              │
│  选择策略:                                                    │
│  self_edit 修改 → 优先 Level 1 → 失败则 Level 3             │
│  prompt_tuner 修改 → Level 2                                 │
│  scheduler 修改 → Level 3                                    │
│  Dockerfile 修改 → Level 4 (需用户确认)                      │
└─────────────────────────────────────────────────────────────┘
```

### C.3 对话上下文保持

```python
# 关键: Telegram 对话状态如何跨重启保持?

class ConversationPersistence:
    """确保重启后对话可以继续。"""

    def save_before_restart(self):
        """Level 3/4 重启前保存。"""
        # 1. 当前对话的摘要 (不是全文, 太大)
        summary = self._summarize_current_conversation()
        # 2. 用户最后的消息和 NeoMind 的回复
        last_exchange = self._get_last_exchange()
        # 3. 当前模式和配置
        mode_state = {
            'mode': self.current_mode,
            'turn_count': self.turn_count,
            'active_goals': self.goals,
        }
        # 4. 写入 checkpoint
        checkpoint.save({
            'conversation_summary': summary,
            'last_exchange': last_exchange,
            'mode_state': mode_state,
            'timestamp': datetime.now().isoformat(),
        })

    def restore_after_restart(self):
        """Level 3/4 重启后恢复。"""
        state = checkpoint.load()
        if state and state.get('conversation_summary'):
            # 将摘要注入到新对话的 system prompt 中
            self._inject_context(state['conversation_summary'])
            # 恢复模式
            self._switch_mode(state['mode_state']['mode'])
            # 通知用户
            self._send_message(
                "🔄 我刚完成了一次系统更新。"
                "之前的对话上下文已恢复，我们可以继续。"
            )
```

### C.4 data-collector 进程不中断 agent 对话

```
关键设计: data-collector 和 agent 是独立进程

agent 重启 → data-collector 不受影响, 继续收集
data-collector 重启 → agent 不受影响, 继续对话
两者通过 SQLite WAL 共享数据 → 无进程间耦合

supervisord 配置 (已有):
  [program:neomind-agent]      autorestart=true
  [program:health-monitor]     autorestart=true
  [program:watchdog]           autorestart=true
  [program:data-collector]     autorestart=true  ← 新增

单独重启某个进程:
  supervisorctl restart neomind-agent     # 只重启 agent
  supervisorctl restart data-collector    # 只重启 collector
```

---

## D. LLM 无关设计

### D.1 问题: NeoMind 使用多种 LLM

```
当前使用:
  chat: deepseek-chat (便宜, 通用)
  fin:  kimi-k2.5 (深度推理)
  coding: deepseek-chat / glm-5

每个 LLM 有不同的:
  - Token 限制 (128K vs 32K vs 8K)
  - 函数调用格式 (OpenAI格式 vs 自定义)
  - 工具支持 (有的支持 function calling, 有的不支持)
  - 定价 (1-100x 价差)
  - 能力 (数学、编程、分析各有强项)
```

### D.2 统一抽象层设计

```
┌─────────────────────────────────────────────────┐
│              NeoMind LLM 抽象层                   │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  Prompt Manager (提示词管理器)             │   │
│  │  ├── 核心 prompt: 模型无关的角色定义      │   │
│  │  ├── 工具描述: 统一的工具 schema          │   │
│  │  ├── 上下文: 按模型 token 限制裁剪       │   │
│  │  └── 学习注入: 只注入最相关的 N 条        │   │
│  └──────────────────────────────────────────┘   │
│                       │                          │
│  ┌──────────────────────────────────────────┐   │
│  │  Tool Schema Translator (工具格式转换器)   │   │
│  │  ├── 内部格式: OpenAI function calling    │   │
│  │  ├── → DeepSeek: 原生支持                 │   │
│  │  ├── → Kimi: 需要转换为 Kimi tool format  │   │
│  │  ├── → GLM: 需要转换为 GLM tool format    │   │
│  │  ├── → Claude: 需要转换为 Anthropic format │   │
│  │  └── → 无工具支持的模型: 退化为 prompt     │   │
│  └──────────────────────────────────────────┘   │
│                       │                          │
│  ┌──────────────────────────────────────────┐   │
│  │  Context Budget Manager (上下文预算管理器) │   │
│  │  ├── 每个模型的 max_tokens 不同           │   │
│  │  ├── 预算分配:                            │   │
│  │  │   system prompt: 15-20%                │   │
│  │  │   learnings + goals: 5-10%             │   │
│  │  │   tool outputs: 20-30%                 │   │
│  │  │   conversation: 40-50%                 │   │
│  │  │   response: 保留 10-15%                │   │
│  │  └── 超预算时: 摘要旧对话, 裁剪工具输出   │   │
│  └──────────────────────────────────────────┘   │
│                       │                          │
│  ┌──────────────────────────────────────────┐   │
│  │  Cost Router (成本路由器)                  │   │
│  │  ├── 简单问候 → 最便宜模型                │   │
│  │  ├── 深度分析 → 推理模型 (kimi/deepseek-r) │   │
│  │  ├── 代码生成 → 编程强项模型              │   │
│  │  ├── 进化任务 → 预算内最佳模型            │   │
│  │  └── 数据驱动: 基于历史成功率优化路由     │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

### D.3 减少冗余信息的具体策略

**问题:** 不能"一股脑喂进去" — 每个 token 都有成本

```python
# 策略 1: 分层注入 (只注入最相关的)
def build_prompt(self, mode, query, model_max_tokens):
    budget = int(model_max_tokens * 0.75)  # 75% 给 input
    sections = []

    # 必须项: system prompt (固定, ~500 tokens)
    sections.append(('system', self.system_prompt, 500))

    # 条件项: 学习注入 (只有相关的, ~200 tokens)
    relevant = learnings.get_relevant(mode, query, limit=5)
    if relevant:
        sections.append(('learnings', format_learnings(relevant), 200))

    # 条件项: 技能提示 (最多3个, ~150 tokens)
    skills = skill_forge.find_matching(query, limit=3)
    if skills:
        sections.append(('skills', format_skills(skills), 150))

    # 条件项: 市场简报 (仅在 fin/chat 模式, ~200 tokens)
    if mode in ('fin', 'chat'):
        briefing = get_latest_briefing_summary(max_tokens=200)
        if briefing:
            sections.append(('briefing', briefing, 200))

    # 条件项: 目标提醒 (仅活跃目标, ~100 tokens)
    goals = goal_tracker.get_active_summary(max_tokens=100)
    if goals:
        sections.append(('goals', goals, 100))

    # 对话历史: 用剩余预算
    used = sum(s[2] for s in sections)
    remaining = budget - used
    conversation = self._trim_conversation(remaining)
    sections.append(('conversation', conversation, remaining))

    return sections

# 策略 2: 工具输出摘要 (不把完整的搜索结果塞进去)
def summarize_tool_output(output: str, max_tokens: int = 500) -> str:
    """对工具输出进行结构化摘要。"""
    if count_tokens(output) <= max_tokens:
        return output
    # 用 LLM 摘要 (如果输出很大)
    # 或者用规则: 保留前N行, 数据表保留列名+前5行
    return truncate_smart(output, max_tokens)

# 策略 3: MCP/工具优先于自然语言
# 如果一个功能可以通过工具调用完成, 就不要让 LLM 在自然语言中描述
# 例:
#   ❌ "请在SQLite中查询AAPL最近的价格" → LLM生成SQL → 执行
#   ✅ 直接调用 FinDataReader.get_latest_price("AAPL") → 返回结构化数据

# 策略 4: Skill/MCP 定义只传递激活的
# 不要把所有20个工具的 schema 都传给 LLM
# 根据当前模式和查询, 只传递相关的 3-5 个
def get_active_tools(mode: str, query: str) -> list:
    all_tools = registry.get_tools()
    # 基础工具: 所有模式都有
    active = [t for t in all_tools if t.is_core]
    # 模式工具: 只有该模式的
    active += [t for t in all_tools if mode in t.modes]
    # 查询相关: 根据关键词匹配
    active += [t for t in all_tools if t.matches_query(query)]
    # 去重 + 限制数量
    return deduplicate(active)[:8]  # 最多8个工具
```

### D.4 对不支持 function calling 的模型的退化方案

```python
class ToolCallFallback:
    """对不支持函数调用的模型, 用 prompt engineering 模拟。"""

    FALLBACK_PROMPT = """
    You have access to the following tools. To use a tool, respond with
    a JSON block in this format:

    ```json
    {"tool": "tool_name", "params": {"key": "value"}}
    ```

    Available tools:
    {tool_descriptions}

    Always use tools when you need real data. Never guess.
    """

    def format_for_model(self, tools, model_supports_functions):
        if model_supports_functions:
            return self._format_openai_style(tools)
        else:
            return self._format_prompt_style(tools)
```

---

## E. 后台监控系统

### E.1 设计原则

```
OpenClaw 的监控: 主要是 CLI 仪表盘
NeoMind 的监控: 24/7 自动化 + Telegram 告警

关键区别:
  - 不依赖用户打开终端
  - 异常时主动通知
  - 数据持久化 (不只是内存中的统计)
```

### E.2 监控指标体系

```python
# 三层监控

# Layer 1: 基础设施 (health-monitor + watchdog 已有)
INFRA_METRICS = {
    'process_alive': bool,         # 各进程是否存活
    'memory_usage_mb': float,      # 内存使用
    'disk_usage_pct': float,       # 磁盘使用
    'cpu_usage_pct': float,        # CPU 使用
    'uptime_hours': float,         # 不间断运行时间
    'restart_count_24h': int,      # 24小时内重启次数
}

# Layer 2: 数据管道 (data-collector 新增)
DATA_METRICS = {
    'last_price_update': datetime,  # 最后一次价格更新
    'last_news_update': datetime,   # 最后一次新闻更新
    'data_sources_active': int,     # 活跃数据源数量
    'api_errors_24h': int,          # 24小时 API 错误数
    'data_freshness_score': float,  # 数据新鲜度 (0-1)
    'db_size_mb': float,            # 数据库总大小
}

# Layer 3: 进化系统 (scheduler 已有, 需扩展)
EVOLUTION_METRICS = {
    'learnings_count': int,         # 学习条目总数
    'skills_active': int,           # 活跃技能数
    'prediction_accuracy_30d': float, # 30天预测准确率
    'goals_achieved_this_month': int, # 本月达成目标数
    'evolution_cost_today': float,  # 今日进化开销
    'system_health_score': float,   # 综合健康评分
}
```

### E.3 Telegram 告警级别

```python
ALERT_LEVELS = {
    'INFO': {
        'frequency': 'daily',     # 每日摘要
        'examples': [
            '日报已生成',
            '本周学习了3个新洞察',
            '预测准确率提升2%',
        ]
    },
    'WARNING': {
        'frequency': 'immediate',  # 立即发送
        'cooldown': 300,           # 5分钟内同类不重复
        'examples': [
            '数据源 Finnhub 连接超时',
            '内存使用超过 80%',
            '进化预算消耗 > 90%',
        ]
    },
    'CRITICAL': {
        'frequency': 'immediate',  # 立即发送
        'cooldown': 60,            # 1分钟内不重复
        'examples': [
            'Agent 进程崩溃, 已自动重启',
            '检测到 boot loop (3次/5分钟)',
            '所有数据源离线',
        ]
    },
}
```

### E.4 健康检查端点扩展

```python
# 当前: /health 只返回 agent 存活状态
# 扩展: /status 返回完整系统状态

@app.route('/status')
def full_status():
    return {
        'timestamp': datetime.now().isoformat(),
        'processes': {
            'agent': check_process('neomind-agent'),
            'health_monitor': check_process('health-monitor'),
            'watchdog': check_process('watchdog'),
            'data_collector': check_process('data-collector'),
        },
        'data_pipeline': {
            'last_price_update': get_last_update('price'),
            'last_news_update': get_last_update('news'),
            'active_sources': count_active_sources(),
        },
        'evolution': {
            'health_score': calculate_health_score(),
            'learnings': count_learnings(),
            'skills': count_active_skills(),
            'safe_mode': is_safe_mode(),
        },
        'resources': {
            'memory_mb': get_memory_usage(),
            'disk_pct': get_disk_usage(),
            'db_size_mb': get_db_total_size(),
        }
    }
```

---

## F. NeoMind 自我修改能力总览

### F.1 NeoMind 可以自己修改的

| 目标 | 方法 | 安全机制 | 示例 |
|------|------|---------|------|
| **Python代码** | self_edit.py (Git-Gated) | AST安全 + pytest + git | 修复bug, 优化算法 |
| **System Prompt** | prompt_tuner.py (A/B test) | 5%改进阈值 + 回滚 | 调整温度, 增加规则 |
| **YAML配置** | prompt_tuner + scheduler | 原子写入 + 备份 | 调整参数 |
| **数据库Schema** | self_edit → migration脚本 | 备份 + 测试 | 增加列, 新建表 |
| **收集策略** | meta_evolve → collector配置 | 合规检查器 | 增加数据源, 调频率 |
| **技能库** | skill_forge.py | 信任分级 + 审查 | 新增技能, 晋升/淘汰 |
| **学习条目** | learnings.py | Ebbinghaus衰减 | 自动提取和遗忘 |
| **进化参数** | meta_evolve.py | 成功率门槛 | 调整激进度 |

### F.2 NeoMind 不可以自己修改的

| 目标 | 原因 | 谁可以修改 |
|------|------|-----------|
| **.env (API Keys)** | 安全敏感 | 只有用户 |
| **Dockerfile** | 构建级变更 | 只有用户 |
| **docker-compose.yml** | 部署级变更 | 只有用户 |
| **self_edit.py 自身** | 防止安全机制被绕过 | 只有用户 |
| **health_monitor.py** | 防止监控被禁用 | 只有用户 |
| **watchdog.py** | 防止看门狗被禁用 | 只有用户 |
| **合规红线** | 法律要求 | 不可修改 |

### F.3 不依赖用户后台操作

```
NeoMind 的自主运行循环:

  24/7 运行中:
  │
  ├── data-collector: 自动收集市场数据
  ├── health-monitor: 自动检查健康状态
  ├── watchdog: 自动检测挂起
  │
  ├── 每轮对话后: scheduler.on_turn_complete()
  │   ├── 快速反思 (0 成本)
  │   ├── 信号收集
  │   └── 状态保存
  │
  ├── 每天 1 次: scheduler._run_daily_cycle()
  │   ├── 日审计
  │   ├── 学习衰减+剪枝
  │   ├── 提示词变体生成
  │   ├── 缓存清理
  │   ├── 数据清理
  │   └── 日报生成
  │
  ├── 每周 1 次: scheduler._run_weekly_cycle()
  │   ├── 深度反思 (LLM辅助)
  │   ├── 提示词评估+采纳
  │   ├── 元进化分析+策略调整
  │   ├── 目标过期检查
  │   ├── 决策准确率统计
  │   └── 周报生成
  │
  └── 每月 1 次: (新增)
      ├── 重新阅读进化计划
      ├── 检查 #TAG 触发条件
      ├── 生成月度进化报告
      └── 如有必要, 更新计划文档
```

---

## G. supervisord.conf 更新 (新增 data-collector)

```ini
; ── Data Collector (24/7 市场数据收集) ────────────
[program:data-collector]
command=python -u /app/agent/data/collector.py
directory=/app
autorestart=true
startretries=5
startsecs=10
stopwaitsecs=30
redirect_stderr=true
stdout_logfile=/data/neomind/collector.log
stdout_logfile_maxbytes=5MB
stdout_logfile_backups=2
environment=PYTHONUNBUFFERED=1,PYTHONPATH=/app
; data-collector 可以独立于 agent 重启
; 如果 agent 崩溃, collector 继续运行
; 如果 collector 崩溃, agent 继续运行
```

---

## H. 配置变更记录

### H.1 base.yaml 变更

新增:
- `identity` 节: NeoMind 核心身份定义 ("数据驱动的个人能力延伸系统")
- `evolution` 节: 自我进化授权 (可修改: 代码/配置/数据库/提示词/技能)
- `llm` 节: LLM 无关设计规范 (统一工具格式, 上下文预算, 结构化调用)
- `host` 节: 宿主机硬件感知 (内存预算, 进程分配)
- `compliance` 节: 法律合规框架 (rate limit, 个人使用, 合规红线)

### H.2 chat.yaml 变更

新增:
- `cross_mode_intelligence` 节: 跨模式情报接收 (自动日报, 主动提醒)
- `evolution_awareness` 节: 进化自我感知 (健康检查, 进度提醒)
- system_prompt 更新: 从 "Explorer" 升级为 "Command Center"
- 新增 CROSS-MODE INTELLIGENCE 指令
- 新增 PROACTIVE REMINDERS 指令
- 新增 SELF-EVOLUTION AWARENESS 指令

### H.3 fin.yaml 变更

- system_prompt 开头新增 SELF-EVOLUTION AWARENESS 段落
- 身份从 "Finance Intelligence Agent" 升级为 "Finance Engine"
- 强调: 分析准确率被追踪, 从错误中学习

### H.4 coding.yaml 变更

- system_prompt 开头新增 SELF-EVOLUTION AWARENESS 段落
- 身份从 "coding assistant" 升级为 "Coding Engine"
- 强调: 可以修改 NeoMind 自身代码, 技能可结晶复用

---

> 本文档是 v4.0 增强进化计划的补充，两份文档共同构成 NeoMind 的完整进化蓝图。
> NeoMind 应该同时阅读 v4.0 和 v4.1 来理解全貌。
