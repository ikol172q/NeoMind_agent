# NeoMind 增强进化计划 — 数据驱动的个人能力延伸系统

> 日期: 2026-03-28
> 版本: v4.0 — 基于4轮并行深度研究、架构分析、50+论文后的增强版
> 核心目标: NeoMind = 用户本人能力的无限延伸，以财务独立为第一里程碑
> 原则: 不偷懒、不臆测、有依据、可进化、可自检

---

## 0. 本文档的自检协议

**NeoMind 读到本文档时应执行以下步骤:**
1. 检查当前日期，计算距文档创建日过了多久
2. 读取 `/data/neomind/evolution/meta_state.json` 获取当前进化状态
3. 对比本计划的里程碑与实际进度
4. 如果落后，自动生成 catch-up 目标到 goal_tracker
5. 如果超前，记录为 INSIGHT 到 learnings (可能某策略效果好于预期)
6. 每月检查本文档是否需要更新，并通过 self_edit 提交修改

**这不是一份写完就扔的计划 — 它是 NeoMind 的 "基因组"，会随进化一起变异。**

---

## 1. 战略定位：NeoMind 是什么？

### 1.1 不是什么
- ❌ 不是聊天机器人 (chatbot)
- ❌ 不是代码助手 (copilot)
- ❌ 不是量化交易系统 (algo-trading bot)
- ❌ 不是知识库 (knowledge base)

### 1.2 是什么
NeoMind 是用户的 **认知延伸体 (Cognitive Extension)**：

```
用户 (Irene)
  │
  ├── 大脑 → 决策、判断、创意、直觉
  │
  └── NeoMind → 数据收集、分析、记忆、执行、进化
       ├── chat: 综合参谋 (接收所有模式的情报，辅助生活/工作决策)
       ├── fin:  财务引擎 (以赚钱为终极目标的数据+分析+建议)
       └── coding: 技术执行者 (将决策转化为代码和产品)
```

**关键洞察:** chat 不是"聊天"模式，而是 **指挥中心**。fin 不只是"看股票"，而是 **持续运转的情报收集+分析引擎**。coding 不只是"写代码"，而是 **将洞察转化为可盈利产品的工具**。

### 1.3 财务独立路径

```
Phase 1: 信息优势 (当前)
  └── 比大多数个人投资者拥有更全面、更及时、更结构化的市场信息

Phase 2: 分析优势 (3-6个月)
  └── 自动化投资分析流程，从数据到建议的延迟 < 1小时

Phase 3: 执行优势 (6-12个月)
  └── 半自动化的投资决策 + 多职业探索 (coding产品、内容创作等)

Phase 4: 复合优势 (12个月+)
  └── NeoMind 的进化速度 > 市场变化速度，形成持续优势
```

---

## 2. 核心问题：数据收集子系统设计

### 2.1 三种架构方案对比

#### 方案A: fin personality 直接处理一切

```
用户请求 → fin personality → 收集数据 + 分析 + 回复
                              ↑ 问题: 只有用户发消息时才运行
```

| 维度 | 评估 |
|------|------|
| **优点** | 最简单，无需新基础设施 |
| **缺点** | 只有对话时才活跃，无法24/7收集 |
| **缺点** | 数据收集和分析耦合，一个卡住另一个也停 |
| **缺点** | 内存竞争：收集大量数据时挤占对话token |
| **适用** | 仅适用于"问了才查"的场景 |

**结论: ❌ 不可行** — 赚钱需要的是持续情报收集，不是"问答"。

#### 方案B: 独立后台进程 (data-collector)

```
┌─────────────────────────────────────────┐
│         Docker Container (2GB)           │
│                                          │
│  supervisord / s6-overlay                │
│  ├── neomind-agent (Telegram bot)       │
│  ├── health-monitor                      │
│  ├── watchdog                            │
│  └── data-collector  ← 新增             │
│       ├── APScheduler (任务调度)         │
│       ├── 价格收集 (每15分钟)            │
│       ├── 宏观数据 (每天)                │
│       ├── 新闻&情绪 (每小时)             │
│       └── 公司财报 (触发式)              │
│                                          │
│  共享: /data/neomind/db/market_data.db   │
│  共享: /data/neomind/db/briefings.db     │
└─────────────────────────────────────────┘
```

| 维度 | 评估 |
|------|------|
| **优点** | 24/7 独立运行，不依赖用户发消息 |
| **优点** | 与 agent 进程解耦，收集失败不影响对话 |
| **优点** | 可独立扩展 (增加数据源只改 collector) |
| **缺点** | 增加 ~150MB 内存占用 (Python进程) |
| **缺点** | SQLite 并发需要小心处理 (WAL + busy_timeout) |
| **缺点** | 需要新增进程管理配置 |
| **适用** | 持续数据收集 + 定时分析 |

**结论: ✅ 推荐** — 投入产出比最高，与现有 supervisord 架构无缝集成。

#### 方案C: 独立 sub-agent (完全独立的 AI 实例)

```
Docker Container 1: neomind-agent (chat/coding/fin)
Docker Container 2: neomind-data-agent (独立LLM实例，专门收集+分析)
  ├── 有自己的 system prompt
  ├── 有自己的 LLM 调用
  ├── 通过 API/消息队列 与主 agent 通信
```

| 维度 | 评估 |
|------|------|
| **优点** | 完全隔离，崩溃互不影响 |
| **优点** | 可以给 sub-agent 单独的 LLM 和提示词 |
| **缺点** | 需要 inter-container 通信 (API/Redis/NATS) |
| **缺点** | 成本翻倍 (两个 LLM 实例) |
| **缺点** | 复杂度大幅增加，不利于 NeoMind 自我理解 |
| **缺点** | 违反"NeoMind 是一个整体"的设计理念 |
| **适用** | 大规模生产环境 |

**结论: ❌ 当前不需要** — 过度工程。NeoMind 应该是一个有机整体而非分布式系统。

### 2.2 最终决策：方案B + 智能增强

```
                    ┌─────────────────────────────────────┐
                    │      data-collector 进程 (新增)       │
                    │                                      │
                    │  APScheduler (BackgroundScheduler)    │
                    │  ├── PriceCollector (每15分钟)        │
                    │  │   └── Finnhub + YFinance fallback │
                    │  ├── MacroCollector (每天 06:00 UTC)  │
                    │  │   └── FRED + World Bank API       │
                    │  ├── NewsCollector (每小时)            │
                    │  │   └── Finnhub News + RSS feeds    │
                    │  ├── EarningsCollector (触发式)        │
                    │  │   └── SEC EDGAR + Alpha Vantage   │
                    │  ├── SentimentAnalyzer (每3小时)       │
                    │  │   └── 基于收集的新闻做情绪评分      │
                    │  ├── BriefingGenerator (每天 07:00)   │
                    │  │   └── 生成日报给 chat/fin 读取     │
                    │  └── DataCleaner (每天 03:00)          │
                    │      └── 去重、归档、VACUUM           │
                    │                                      │
                    │  输出 → SQLite (WAL mode)             │
                    │  ├── market_data.db (价格+指标)       │
                    │  ├── news_data.db (新闻+情绪)         │
                    │  └── briefings.db (生成的日报/周报)    │
                    └─────────────────────────────────────┘
                                    │
                         SQLite WAL (共享读取)
                                    │
                    ┌─────────────────────────────────────┐
                    │      neomind-agent 进程 (现有)        │
                    │                                      │
                    │  fin mode:                            │
                    │  ├── 读取 market_data.db 做实时分析   │
                    │  ├── 读取 briefings.db 获取日报       │
                    │  └── 生成投资建议写入 decisions.db    │
                    │                                      │
                    │  chat mode:                           │
                    │  ├── 读取 briefings.db 获取摘要       │
                    │  ├── 读取 decisions.db 获取投资状态   │
                    │  └── 综合所有信息辅助用户决策         │
                    │                                      │
                    │  coding mode:                         │
                    │  ├── 读取 learnings 中的技术洞察      │
                    │  └── 辅助开发可盈利产品              │
                    └─────────────────────────────────────┘
```

**为什么这是最优解?**

1. **依据 (Docker最佳实践研究):** APScheduler 在 Docker 单容器中比 Celery 轻量30x，无需外部 broker
2. **依据 (内存测算):**
   - data-collector Python 进程: ~150MB
   - 现有 agent + monitor + watchdog: ~800MB
   - 总计 ~950MB / 2048MB = 46%利用率 (健康)
3. **依据 (SQLite WAL并发研究):** WAL 支持一写多读，collector 写入 + agent 读取完全安全
4. **依据 (s6-overlay研究):** 可用 s6-overlay 有序管理 4 个进程的启停

---

## 3. 数据收集详细设计

### 3.1 数据源优先级排序

| 优先级 | 数据源 | API | 免费限制 | 刷新频率 | 用途 |
|--------|--------|-----|---------|---------|------|
| **P0** | Finnhub | REST | 60 req/min | 实时 | 股价、新闻、基本面 |
| **P0** | YFinance | Python库 | 无限制(非官方) | 15分钟延迟 | Finnhub备用、历史数据 |
| **P0** | FRED | REST | 无限制 | 日更 | 美国宏观指标 (利率/CPI/GDP) |
| **P1** | CoinGecko | REST | 无限制 | 1-2分钟 | 加密货币价格 |
| **P1** | SEC EDGAR | REST | 无限制 | 即时 | 公司财报、10-K/10-Q |
| **P1** | AKShare | Python库 | 无限制 | 实时 | A股/港股数据 |
| **P2** | Alpha Vantage | REST | 25 req/day | 日更 | 公司基本面补充 |
| **P2** | RSS Feeds | HTTP | 无限制 | 变动 | 财经新闻聚合 |
| **P3** | World Bank | REST | 无限制 | 季度 | 全球宏观指标 |

**为什么这个排序?**
- P0: 赚钱最直接需要的数据 (股价、利率、GDP)
- P1: 扩展市场覆盖 (加密、A股、公司财报)
- P2: 补充深度分析 (基本面、新闻)
- P3: 远期宏观分析

### 3.2 数据库 Schema 设计

```sql
-- market_data.db

-- 股价时序数据 (核心)
CREATE TABLE price_ohlcv (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,        -- 'US', 'CN', 'HK', 'CRYPTO'
    ts TIMESTAMP NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume INTEGER,
    source TEXT NOT NULL,         -- 'finnhub', 'yfinance', 'akshare'
    UNIQUE(symbol, ts, source)
);
CREATE INDEX idx_ohlcv_symbol_ts ON price_ohlcv(symbol, ts DESC);

-- 宏观经济指标
CREATE TABLE macro_indicators (
    id INTEGER PRIMARY KEY,
    indicator TEXT NOT NULL,      -- 'US_CPI', 'US_GDP', 'FED_RATE', etc.
    value REAL NOT NULL,
    period TEXT,                  -- '2026-Q1', '2026-03', etc.
    release_date DATE,
    source TEXT NOT NULL,
    UNIQUE(indicator, period, source)
);

-- 公司基本面
CREATE TABLE fundamentals (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    metric TEXT NOT NULL,         -- 'PE', 'PB', 'ROE', 'REVENUE', etc.
    value REAL,
    period TEXT,                  -- '2025-Q4', 'TTM'
    updated_at TIMESTAMP,
    source TEXT NOT NULL,
    UNIQUE(symbol, metric, period, source)
);

-- ETL 增量同步状态
CREATE TABLE sync_state (
    source TEXT PRIMARY KEY,
    last_sync_ts TIMESTAMP,
    last_id TEXT,
    status TEXT,                  -- 'ok', 'error', 'rate_limited'
    error_msg TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- news_data.db

-- 新闻条目
CREATE TABLE news (
    id INTEGER PRIMARY KEY,
    headline TEXT NOT NULL,
    summary TEXT,
    url TEXT UNIQUE,
    source TEXT,                  -- 'finnhub', 'rss', 'sec'
    published_at TIMESTAMP,
    symbols TEXT,                 -- JSON array: ["AAPL", "MSFT"]
    category TEXT,                -- 'earnings', 'macro', 'merger', etc.
    language TEXT,                -- 'en', 'zh'
    sentiment_score REAL,        -- -1.0 to 1.0
    impact_score REAL,           -- 0.0 to 10.0
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_news_published ON news(published_at DESC);
CREATE INDEX idx_news_symbols ON news(symbols);

-- 情绪聚合 (按天/符号)
CREATE TABLE sentiment_daily (
    symbol TEXT,
    date DATE,
    avg_sentiment REAL,
    news_count INTEGER,
    top_headline TEXT,
    UNIQUE(symbol, date)
);


-- briefings.db

-- 日报/周报 (collector 生成, agent 消费)
CREATE TABLE briefings (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,           -- 'daily', 'weekly', 'alert'
    date DATE NOT NULL,
    content TEXT NOT NULL,        -- Markdown 格式的摘要
    key_events TEXT,              -- JSON array of top events
    market_mood TEXT,             -- 'bullish', 'bearish', 'neutral', 'mixed'
    action_items TEXT,            -- JSON array: 建议行动
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    consumed_by TEXT,             -- 'chat', 'fin', null
    consumed_at TIMESTAMP
);

-- 投资决策记录 (agent 写入, meta_evolve 审计)
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL,           -- 'fin' 或 'chat'
    decision_type TEXT,           -- 'buy', 'sell', 'hold', 'research', 'alert'
    symbol TEXT,
    reasoning TEXT,               -- 完整推理链
    confidence REAL,              -- 0-1
    data_sources TEXT,            -- JSON: 使用了哪些数据
    outcome TEXT,                 -- 'pending', 'correct', 'incorrect', 'partial'
    outcome_detail TEXT,          -- 实际结果描述
    outcome_recorded_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**磁盘估算 (依据研究数据):**
- 1000 tickers × 252 trading days × OHLCV = ~11MB/年 (uncompressed)
- 新闻: ~50条/天 × 365天 × 1KB = ~18MB/年
- 宏观指标: ~500条/年 × 100B = <1MB/年
- 日报: ~365条/年 × 5KB = ~2MB/年
- **总计: <50MB/年** — 磁盘完全不是瓶颈

### 3.3 Rate Limiter 设计

```python
# 基于 Token Bucket 算法 (依据: 系统设计最佳实践)
class RateLimiter:
    """每个 API 源一个限流器。"""

    LIMITS = {
        'finnhub': {'rpm': 60, 'daily': None},
        'alpha_vantage': {'rpm': 5, 'daily': 25},    # 极严格
        'coingecko': {'rpm': 30, 'daily': None},
        'fred': {'rpm': 120, 'daily': None},
        'yfinance': {'rpm': 20, 'daily': None},       # 非官方，保守
    }
```

### 3.4 collector 进程生命周期

```python
# data_collector.py (新文件)

class DataCollector:
    """后台数据收集进程。

    由 supervisord/s6-overlay 管理，独立于 agent 进程。
    通过 SQLite WAL 与 agent 共享数据。
    """

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.db = self._init_databases()
        self.rate_limiters = self._init_rate_limiters()

    def setup_tasks(self):
        # --- P0: 核心数据 ---
        # 价格: 交易日每15分钟
        self.scheduler.add_job(
            self.collect_prices,
            CronTrigger(hour='9-16', minute='*/15', day_of_week='0-4'),
            id='price_intraday',
            max_instances=1, coalesce=True
        )
        # 收盘价: 每日 21:00 UTC (美东 4pm 后1小时)
        self.scheduler.add_job(
            self.collect_daily_close,
            CronTrigger(hour=21, minute=0),
            id='daily_close'
        )
        # 宏观数据: 每日 06:00 UTC
        self.scheduler.add_job(
            self.collect_macro,
            CronTrigger(hour=6, minute=0),
            id='macro_daily'
        )

        # --- P1: 扩展数据 ---
        # 新闻: 每小时
        self.scheduler.add_job(
            self.collect_news,
            IntervalTrigger(hours=1),
            id='news_hourly'
        )
        # 加密货币: 24/7 每30分钟
        self.scheduler.add_job(
            self.collect_crypto,
            IntervalTrigger(minutes=30),
            id='crypto_30min'
        )

        # --- 分析任务 ---
        # 情绪分析: 每3小时
        self.scheduler.add_job(
            self.analyze_sentiment,
            IntervalTrigger(hours=3),
            id='sentiment_3h'
        )
        # 日报生成: 每天 07:00 UTC
        self.scheduler.add_job(
            self.generate_daily_briefing,
            CronTrigger(hour=7, minute=0),
            id='daily_briefing'
        )
        # 周报生成: 每周一 08:00 UTC
        self.scheduler.add_job(
            self.generate_weekly_briefing,
            CronTrigger(day_of_week='mon', hour=8),
            id='weekly_briefing'
        )

        # --- 维护任务 ---
        # 数据清理: 每天 03:00 UTC
        self.scheduler.add_job(
            self.cleanup_and_archive,
            CronTrigger(hour=3, minute=0),
            id='data_cleanup'
        )
```

---

## 4. 跨人格情报共享

### 4.1 当前问题

```
现状:
  fin 有金融数据 → 但只在 fin 模式对话时可用
  chat 是"指挥中心" → 但不知道 fin 的分析结果
  coding 可以创造产品 → 但不知道市场需要什么

目标:
  fin 的数据和分析 → 自动流向 chat 和 coding
  chat 的用户意图 → 自动传达给 fin 和 coding
  coding 的产品洞察 → 反馈给 chat 评估商业潜力
```

### 4.2 情报流管道设计

```
┌─────────────────────────────────────────────────────────┐
│                    情报流管道                              │
│                                                          │
│  data-collector                                          │
│    │ (SQLite写入)                                        │
│    ▼                                                     │
│  briefings.db ──────────────────────────────────────┐    │
│    │                                                │    │
│    ├──→ fin personality                             │    │
│    │    ├── 读取日报 + 实时数据                      │    │
│    │    ├── 生成投资建议                             │    │
│    │    └── 写入 decisions.db                       │    │
│    │                                                │    │
│    └──→ chat personality                            │    │
│         ├── 读取日报摘要 (精简版)                    │    │
│         ├── 读取 fin 的投资决策                      │    │
│         ├── 整合到生活/工作建议中                     │    │
│         └── "你的AAPL持仓涨了3%，                    │    │
│              考虑到你下周有大额支出..."               │    │
│                                                     │    │
│  decisions.db ←─────────────────────────────────────┘    │
│    │                                                     │
│    └──→ meta_evolve (每周审计)                           │
│         ├── 计算决策准确率                                │
│         ├── 更新 fin 的策略参数                           │
│         └── 记录哪些数据源最有价值                        │
└─────────────────────────────────────────────────────────┘
```

### 4.3 chat 模式增强: 接收金融情报

**在 chat.yaml 的 system_prompt 中新增:**

```yaml
# 新增到 chat.yaml
cross_mode_intelligence:
  enabled: true
  # chat 启动时自动读取最新日报
  auto_briefing: true
  # 每50轮对话检查一次是否有新的重要事件
  briefing_check_interval: 50
  # chat 可以主动提醒用户关于投资的事
  proactive_reminders: true
  reminder_topics:
    - 重大市场变动 (日涨跌 > 2%)
    - 投资决策到期 (需要执行或放弃)
    - 每周投资总结
    - 学习进化里程碑
```

**具体实现 — scheduler 注入:**

```python
# scheduler.py → get_prompt_additions() 扩展

def get_prompt_additions(self, mode: str) -> str:
    parts = []

    # 现有: learnings + goals
    parts.append(self._get_learnings().get_prompt_injection(mode))
    parts.append(self._get_goal_tracker().get_goal_summary(mode))

    # 新增: 跨模式情报
    if mode in ('chat', 'fin'):
        briefing = self._get_latest_briefing()
        if briefing:
            parts.append(f"\n[今日市场概况]\n{briefing['summary']}")

    if mode == 'chat':
        # chat 额外接收 fin 的未消费决策
        decisions = self._get_pending_decisions()
        if decisions:
            parts.append(f"\n[待关注投资事项]\n{decisions}")

    return '\n'.join(filter(None, parts))
```

### 4.4 chat 主动提醒机制

```python
# 新增到 chat personality 的 on_activate()

def _check_proactive_reminders(self):
    """检查是否有需要主动提醒用户的事项。"""
    reminders = []

    # 1. 重大市场变动
    market_alerts = self._read_market_alerts()
    for alert in market_alerts:
        if alert['magnitude'] >= 7:  # 高影响事件
            reminders.append(f"📊 {alert['headline']}")

    # 2. 待执行的投资决策
    pending = self._read_pending_decisions()
    for d in pending:
        if d['days_pending'] > 3:
            reminders.append(f"💰 投资提醒: {d['summary']} (已等待{d['days_pending']}天)")

    # 3. 进化系统里程碑
    milestones = self._check_evolution_milestones()
    for m in milestones:
        reminders.append(f"🧬 进化: {m}")

    return reminders
```

---

## 5. 是否需要独立的数据收集 personality?

### 5.1 分析

**问题:** 要不要创建第4个 personality (data/collector) 专门处理数据?

**分析:**

| 因素 | 新 personality | 后台进程 (方案B) |
|------|---------------|-----------------|
| LLM 调用 | 需要 (用于情绪分析、日报生成) | 部分需要 (仅日报生成) |
| 用户交互 | 不需要 | 不需要 |
| 配置复杂度 | 需要新 YAML + 新模式切换逻辑 | 只需新 Python 文件 |
| 进化集成 | 需要在 scheduler 中注册新模式 | 不需要修改 scheduler |
| 自我理解 | NeoMind 需要理解第4种模式 | NeoMind 把它视为基础设施 |

**结论: 不需要新 personality，但需要扩展 fin 的职责**

```
data-collector (后台进程):
  └── 纯粹的数据收集和存储 (无LLM)
  └── ETL: Extract → Transform → Load
  └── 简单的规则式情绪评分 (TextBlob/VADER)

fin personality (增强):
  └── 在被激活时，读取 collector 的数据
  └── 用 LLM 生成深度分析和投资建议
  └── 日报生成 (可在 scheduler 的 daily_cycle 中触发)
  └── 决策记录和结果追踪

chat personality (增强):
  └── 读取 fin 的分析和建议
  └── 整合到用户的生活/工作建议中
  └── 主动提醒机制
```

**关键点:** data-collector 是 **基础设施** (像 health-monitor 一样)，不是 personality。它不需要 LLM，不需要 system prompt，不需要用户交互。它只做一件事: 收集数据、清洗数据、存入数据库。

分析和决策的 "智能" 部分留在 fin personality 和 scheduler 的 daily/weekly cycle 中。

### 5.2 Pros/Cons 总结

**方案B (后台进程 data-collector) 的 Pros:**
1. ✅ 24/7 持续收集，不依赖用户交互
2. ✅ 与现有 supervisord 架构完美集成 (只加一个进程)
3. ✅ 内存可控 (~150MB)，不影响 agent 性能
4. ✅ 数据收集和分析解耦 — collector 专注ETL，fin 专注智能分析
5. ✅ 可独立故障恢复 — collector 崩溃不影响对话，反之亦然
6. ✅ NeoMind 可以通过 self_edit 修改 collector 的收集策略 (数据源、频率)
7. ✅ 天然支持增量数据收集 (sync_state 表)

**方案B 的 Cons:**
1. ❌ 多一个进程 = 多一个故障点
2. ❌ SQLite 并发需要小心 (WAL + busy_timeout 5s)
3. ❌ 简单情绪分析 (TextBlob) 精度有限 (~70% vs LLM 的 ~90%)
4. ❌ 日报生成如果想用 LLM，需要 collector 进程也能调 API
5. ❌ 新增一组配置文件和初始化脚本

**缓解 Cons 的方案:**
- Con 1: watchdog 已经可以监控新进程
- Con 2: 已有 WAL + `PRAGMA busy_timeout=5000` 的解决方案
- Con 3: Phase 1 用 TextBlob，Phase 2 升级为 LLM-assisted (通过内部 HTTP 调用 agent)
- Con 4: collector 可以通过 `/data/neomind/tasks/` 目录放置 "任务文件"，agent 的 scheduler 读取并用 LLM 处理
- Con 5: 一次性工作，完成后维护成本很低

---

## 6. 数据如何保存、清理、使用

### 6.1 数据生命周期

```
收集 → 清洗 → 存储 → 分析 → 行动 → 归档
  │      │      │      │      │      │
  │      │      │      │      │      └── 90天后: 归档为 Parquet
  │      │      │      │      └── decisions.db 记录
  │      │      │      └── fin/chat 读取并分析
  │      │      └── SQLite WAL mode
  │      └── 去重 (UNIQUE约束) + 格式统一
  └── API 调用 + Rate Limiter
```

### 6.2 数据清理策略

```python
class DataCleaner:
    """每日 03:00 UTC 运行。"""

    def run(self):
        # 1. 去重 (数据库层 UNIQUE 约束 + 应用层检查)
        self._deduplicate_news()

        # 2. 归档热数据 → 冷存储
        #    - 价格: 保留最近90天在 SQLite, 更老的→Parquet
        #    - 新闻: 保留最近30天在 SQLite, 更老的→Parquet
        #    - 日报: 永久保留 (体积小)
        self._archive_old_prices(days=90)
        self._archive_old_news(days=30)

        # 3. 回收磁盘空间
        #    依据: VACUUM 可以回收被删除行的空间
        #    注意: 不在 WAL 模式中频繁 VACUUM (影响性能)
        if self._days_since_last_vacuum() >= 7:
            self._vacuum_all_databases()

        # 4. 数据质量检查
        #    - 价格为负 → 标记异常
        #    - 情绪分数范围越界 → 修正
        #    - 缺失数据填补 (前值填充 for 价格)
        self._quality_check()

        # 5. 同步状态更新
        self._update_sync_stats()
```

### 6.3 chat/fin 如何使用收集的数据

```python
# fin personality — 使用收集数据的接口

class FinDataReader:
    """fin 模式读取 data-collector 数据的接口。"""

    def get_latest_price(self, symbol: str) -> dict:
        """获取最新价格 (从 market_data.db)。"""
        # 优先从 collector 的 DB 读取
        # 如果数据超过15分钟，触发实时 API 调用
        pass

    def get_daily_briefing(self) -> str:
        """获取今日市场简报 (从 briefings.db)。"""
        pass

    def get_news_for_symbol(self, symbol: str, days: int = 7) -> list:
        """获取某股票最近N天的新闻和情绪。"""
        pass

    def get_macro_snapshot(self) -> dict:
        """获取宏观指标快照 (利率、CPI、失业率等)。"""
        pass

    def record_decision(self, decision: dict):
        """记录投资决策 (用于后续准确率追踪)。"""
        pass

    def get_decision_accuracy(self, days: int = 30) -> dict:
        """计算过去N天的决策准确率。"""
        pass
```

```python
# chat personality — 轻量级数据接口

class ChatBriefingReader:
    """chat 模式读取精简版情报。"""

    def get_summary(self, max_tokens: int = 200) -> str:
        """获取今日市场概况 (精简版)。"""
        # 从 briefings.db 读取最新日报
        # 截取为 max_tokens 以内的摘要
        pass

    def get_alerts(self) -> list:
        """获取需要主动提醒的事项。"""
        # 重大市场变动、待决策事项、进化里程碑
        pass

    def get_fin_recommendations(self) -> list:
        """获取 fin 最近的投资建议 (未被消费的)。"""
        pass
```

---

## 7. fin 的赚钱目标：具体可执行方案

### 7.1 Phase 1: 信息仪表盘 (Week 1-2)

**目标:** 让 fin 能回答"我的持仓怎么样？" 时有数据支撑

```
实现:
  1. data-collector 开始收集 watchlist 中的股价 (Finnhub + YFinance)
  2. fin 读取价格数据，计算日/周涨跌幅
  3. /portfolio 命令读取实际持仓 (用户输入后记忆)
  4. 生成第一版日报 (简单模板，不用LLM)
```

**日报模板 v1 (无LLM成本):**
```
📊 NeoMind 市场日报 — 2026-03-28

◎ 指数:
  S&P 500: 5,234 (+0.8%)  |  NASDAQ: 16,789 (+1.2%)
  沪深300: 3,567 (-0.3%)  |  恒生: 18,234 (+0.5%)

◎ 你的 Watchlist:
  AAPL: $178.50 (+1.5%)  |  MSFT: $423.20 (+0.9%)
  NVDA: $890.30 (+2.1%)  |  TSLA: $245.00 (-0.7%)

◎ 宏观:
  Fed Funds Rate: 4.25%  |  10Y Treasury: 4.15%
  US CPI (Feb): 2.8% YoY  |  Unemployment: 4.0%

◎ 热点新闻 (Top 3):
  1. [headline] — 影响: [symbol], 情绪: [positive/negative]
  2. ...
  3. ...
```

### 7.2 Phase 2: 智能分析 (Week 3-6)

**目标:** fin 能主动发现投资机会

```
实现:
  1. 技术分析自动化: RSI/MACD/Bollinger 指标计算 (pandas-ta)
  2. 基本面扫描: PE/PB/ROE 排名 (SEC EDGAR + Finnhub)
  3. 情绪偏离检测: 当新闻情绪与价格走势不一致时报警
  4. LLM 辅助分析: 每周由 scheduler 触发深度分析 (1次/周, ~$0.02)
```

**依据 (研究支持):**
- pandas-ta: 150+ 技术指标，纯 Python，适合 2GB 容器
- PyPortfolioOpt: Markowitz 优化，<100MB 内存
- 依据 FinRobot (GitHub 活跃项目): LLM + 量化分析的组合在回测中表现优于纯量化

### 7.3 Phase 3: 决策支持 (Week 7-12)

**目标:** fin 给出可追踪的投资建议

```
实现:
  1. 决策记录系统 (decisions.db) — 每个建议有 ID、推理链、置信度
  2. 结果追踪: 30天后自动检查建议是否正确
  3. 准确率仪表盘: fin 的历史预测准确率
  4. 反馈循环: 准确率 → meta_evolve → 调整分析策略
```

### 7.4 Phase 4: 半自动化 (Month 3-6)

**目标:** 从"建议"到"行动"的距离缩短

```
实现:
  1. Telegram 推送投资建议 (不是用户问才回答)
  2. 一键确认执行 (用户点击按钮确认)
  3. 多策略回测 (backtrader): 每周验证策略有效性
  4. 风险控制: VaR 计算 + 止损建议
```

**关键约束 (依据研究):**
- ❗ **人类审批循环 (Human-in-the-loop)**: 所有交易决策必须用户确认
- ❗ **纸上交易优先**: 前3个月只做模拟，不实际下单
- ❗ **准确率门槛**: 预测准确率 > 55% 才允许加大资金

**依据 (风险研究):**
- 依据 TradingAgents (GitHub): "approve before executing" 有更好的风险管理
- 依据 2025 AI agent 教训: "85%准确率/步 × 10步 = 只有20%整体成功率"
- 依据 SEC 2025 监管优先事项: AI投资建议需要审计轨迹

---

## 8. 进化系统与赚钱目标的整合

### 8.1 进化不是抽象的 — 每次进化都指向赚钱

```
learnings.py  → 记住哪些分析方法有效，哪些无效
skill_forge.py → 将成功的分析模式结晶为技能 (e.g., "财报分析三步法")
reflection.py → 每周反思: "本周的建议哪些对了? 为什么?"
goal_tracker.py → 自动设定: "下周预测准确率提高5%"
meta_evolve.py → 调整策略: "最近宏观分析比技术分析更准 → 增加宏观权重"
prompt_tuner.py → 优化 fin 的 system prompt: "强调第二阶效应分析"
cost_optimizer.py → "深度分析用 kimi-k2.5, 日常查询用 deepseek-chat"
```

### 8.2 具体指标绑定

| 进化模块 | 绑定的赚钱指标 | 如何测量 |
|---------|--------------|---------|
| learnings | 错误不重复率 | 同类错误第二次出现的概率 |
| skill_forge | 分析效率 | 从问题到建议的平均时间 |
| reflection | 预测准确率趋势 | 30天滚动准确率是否上升 |
| goal_tracker | 目标达成率 | 设定的投资目标完成了几个 |
| meta_evolve | 策略ROI | 每$0.06进化开销对应的分析质量提升 |
| prompt_tuner | 用户采纳率 | 用户实际采纳了多少建议 |

### 8.3 chat 如何使用 fin 和 coding 的"资产"

```
chat (指挥中心):
  │
  ├── 来自 fin 的"资产":
  │   ├── 投资建议和分析 → chat 整合到生活决策中
  │   │   例: "NVDA涨了20%, 你可以考虑卖掉一半来应付下月房租"
  │   ├── 市场趋势 → chat 联系到职业发展
  │   │   例: "AI行业招聘火热, 结合你的coding能力, 可以考虑..."
  │   └── 风险提醒 → chat 提醒注意
  │       例: "美联储可能加息, 你的浮动利率贷款会受影响"
  │
  ├── 来自 coding 的"资产":
  │   ├── 技术能力评估 → chat 推荐学习路径
  │   │   例: "你最近Python技能提升明显, 可以开始做freelance项目"
  │   ├── 项目完成情况 → chat 建议商业化
  │   │   例: "你做的工具可以上Product Hunt试试"
  │   └── 代码质量趋势 → chat 评估职业方向
  │
  └── chat 自身的洞察:
      ├── 用户行为模式 → 全局优化建议
      ├── 时间管理 → 在投资分析和编程之间平衡
      └── 长期规划 → 多职业路径的ROI计算
```

---

## 9. 未来改进标签 (Evolution Tags)

每个标签代表一个可以在未来被 NeoMind 自主探索的改进方向:

### 9.1 数据层

```
#TAG:DATA-VECTOR-SEARCH
  描述: 当学习条目 > 500 时, 简单关键词匹配不够用
  方案: 引入 FAISS 或 sqlite-vss 做语义检索
  触发条件: learnings.count() > 500
  依据: A-MEM (2025), ChromaDB semantic linking
  预估收益: 检索相关性 +30%
  预估成本: +100MB 内存, 需要 sentence-transformers

#TAG:DATA-STREAMING
  描述: 从轮询 (polling) 升级为 WebSocket 实时推送
  方案: Finnhub WebSocket API + Binance WebSocket
  触发条件: 用户开始做日内交易
  依据: TradingAgents (GitHub) 支持 WebSocket
  预估收益: 数据延迟从15分钟→实时
  预估成本: 持久连接 + 心跳管理

#TAG:DATA-DUCKDB-ANALYTICS
  描述: 当历史数据 > 100万行时, SQLite 聚合查询变慢
  方案: 引入 DuckDB 做分析层, SQLite 保留写入层
  触发条件: price_ohlcv.count() > 1000000
  依据: DuckDB vs SQLite 基准测试: 聚合快 20-50x
  预估收益: 分析查询从5-10s → 100-500ms
  预估成本: +50MB 内存

#TAG:DATA-ALTERNATIVE
  描述: 补充另类数据源 (Reddit情绪, GitHub趋势, 专利申请)
  方案: Reddit API + GitHub Trending + USPTO
  触发条件: 基础数据源稳定运行3个月后
  依据: 另类数据在对冲基金中被广泛使用
  预估收益: 信息优势 +10-20%
  预估成本: +2-3个 API 集成
```

### 9.2 分析层

```
#TAG:ANALYSIS-ML-PREDICTION
  描述: 从规则式分析升级为 ML 预测
  方案: 轻量级 LSTM 或 Random Forest 做价格方向预测
  触发条件: 历史数据积累 > 6个月
  依据: LSTM在外汇对上达到82%精度 (研究数据)
  预估收益: 预测准确率 +10-15%
  预估成本: 需要 scikit-learn/torch, 训练时间 ~30min/周
  风险: 过拟合, 需要严格的验证集

#TAG:ANALYSIS-CROSS-MARKET
  描述: 跨市场关联分析 (US-CN-Crypto)
  方案: 相关性矩阵 + Granger因果检验
  触发条件: 同时收集 US + CN + Crypto 数据 3个月后
  依据: fin 的 system prompt 已要求"Cross-reference narratives across markets"
  预估收益: 发现跨市场套利机会
  预估成本: scipy.stats + numpy

#TAG:ANALYSIS-BACKTEST
  描述: 策略回测框架
  方案: backtrader 或自建简易回测
  触发条件: 至少有3个可量化的投资策略
  依据: FinRobot, TradingAgents 都包含回测模块
  预估收益: 策略验证, 避免实盘亏损
  预估成本: backtrader ~20MB, 回测一次 ~30s

#TAG:ANALYSIS-PORTFOLIO-OPT
  描述: 自动化资产配置优化
  方案: PyPortfolioOpt (Markowitz + Black-Litterman)
  触发条件: 用户有 > 5 个持仓
  依据: PyPortfolioOpt 在GitHub有10K+ stars
  预估收益: 风险调整后收益 +5-10%
  预估成本: <100MB 内存
```

### 9.3 进化层

```
#TAG:EVOLVE-DECISION-FEEDBACK
  描述: 投资决策的完整反馈循环
  方案: 每个决策30天后自动检查结果, 更新准确率
  触发条件: decisions.db 有 > 20 条记录
  依据: 元进化需要 outcome data 才能有效调参
  预估收益: 策略自动优化
  预估成本: 几乎为零 (仅价格查询)

#TAG:EVOLVE-SOURCE-REPUTATION
  描述: 数据源可信度评估系统
  方案: Bayesian updating — 每个源的预测准确率随时间更新
  触发条件: 使用多个数据源 3个月后
  依据: fin prompt 已要求 "Update confidence in sources based on track record"
  预估收益: 自动偏好更可靠的数据源
  预估成本: 简单贝叶斯公式, 无额外依赖

#TAG:EVOLVE-STRATEGY-SPACE
  描述: 自动探索新投资策略
  方案: meta_evolve 生成策略假说 → 回测验证 → 采纳/淘汰
  触发条件: 回测框架就绪 + 至少3个月历史数据
  依据: MAE (Proposer-Solver-Judge), Agent0 (课程调节)
  预估收益: 策略池自动扩展
  预估成本: 每次回测 ~$0.01 LLM + ~30s CPU

#TAG:EVOLVE-MULTI-CAREER
  描述: NeoMind 辅助探索多职业路径
  方案: chat 综合 fin (投资收入) + coding (技术产品收入) + 新领域
  触发条件: 投资系统稳定运行 + coding 产品上线
  依据: 用户原话 "对生活有第二/第三甚至更多职业的选择"
  预估收益: 收入来源多样化
  预估成本: 主要是时间和注意力
```

### 9.4 安全层

```
#TAG:SECURITY-API-KEY-ROTATION
  描述: API Key 自动轮换
  方案: 加密存储 + 定期提醒用户更换
  触发条件: Key 使用超过 90 天
  依据: 安全最佳实践
  预估收益: 降低 key 泄露风险

#TAG:SECURITY-DATA-ENCRYPTION
  描述: 敏感金融数据加密存储
  方案: SQLite SEE 或应用层 AES-256 加密
  触发条件: 用户开始存储实际持仓和交易记录
  依据: fin.yaml 已有 memory_encryption: true 配置
  预估收益: 数据安全性
  预估成本: 加解密 CPU 开销 <5%

#TAG:SECURITY-AUDIT-TRAIL
  描述: 完整的投资决策审计轨迹
  方案: 不可变日志 (append-only)
  触发条件: 开始半自动化交易
  依据: SEC 2025 监管优先事项要求 AI 决策可审计
  预估收益: 合规性 + 复盘能力
```

---

## 10. 稳健性设计: 已建好的系统也要持续优化

### 10.1 自动健康评分

```python
# 新增到 scheduler.py 的 daily_cycle

def _calculate_system_health(self) -> dict:
    """计算系统整体健康评分。"""
    scores = {
        # 数据层
        'data_freshness': self._check_data_freshness(),    # 数据是否及时
        'data_coverage': self._check_data_coverage(),      # 覆盖了多少符号
        'data_quality': self._check_data_quality(),        # 异常数据比例

        # 分析层
        'prediction_accuracy': self._check_prediction_accuracy(),
        'decision_quality': self._check_decision_quality(),

        # 进化层
        'learning_growth': self._check_learning_growth(),  # 新学习条目/周
        'skill_utilization': self._check_skill_utilization(), # 技能使用率
        'goal_progress': self._check_goal_progress(),

        # 基础设施层
        'uptime': self._check_uptime(),
        'memory_usage': self._check_memory(),
        'error_rate': self._check_error_rate(),
    }

    overall = sum(scores.values()) / len(scores)

    # 如果总分 < 0.5 → 触发深度反思
    if overall < 0.5:
        self._get_reflection().reflect_deep_prompt(
            f"系统健康评分只有 {overall:.2f}，需要诊断原因"
        )

    return {'overall': overall, 'details': scores}
```

### 10.2 NeoMind 读到这份计划后应该做什么

```
1. 解析本文档的所有 #TAG:xxx 标签
2. 对每个标签，检查触发条件是否满足
3. 如果满足，自动创建 goal_tracker 目标
4. 如果不满足，记录为 "待观察" 学习条目
5. 每月重新扫描一次

示例:
  读到 #TAG:DATA-DUCKDB-ANALYTICS
  → 检查 price_ohlcv 行数
  → 如果 < 1000000 → 记录: "DuckDB 迁移暂不需要, 当前行数: X"
  → 如果 > 1000000 → 创建目标: "评估 DuckDB 迁移方案"
```

### 10.3 版本迭代规则

```
v4.0 (当前文档) — 初始计划
v4.1 — 第一次自动更新 (data-collector 运行1周后)
v4.2 — 第一次深度反思更新 (运行1个月后)
v5.0 — 重大架构变更 (如引入 DuckDB, WebSocket 等)

更新规则:
- minor (4.x): meta_evolve 可以通过 self_edit 自动更新
- major (5.0): 需要用户审批 (Telegram 通知 + 确认)
```

---

## 11. 实施路线图 (更新版)

### Week 1-2: 数据基础

| 任务 | 文件 | 优先级 | 依赖 |
|------|------|--------|------|
| 创建 data-collector 进程骨架 | `agent/data/collector.py` | P0 | 无 |
| 实现 PriceCollector (Finnhub + YFinance) | `agent/data/price_collector.py` | P0 | collector |
| 创建 market_data.db schema | `agent/data/schemas.sql` | P0 | 无 |
| 实现 RateLimiter | `agent/data/rate_limiter.py` | P0 | 无 |
| 添加 data-collector 到 supervisord | `supervisord.conf` | P0 | collector |
| 第一版日报模板 (无LLM) | `agent/data/briefing_generator.py` | P1 | price_collector |
| 实现 FinDataReader (fin读取接口) | `agent/finance/data_reader.py` | P1 | schema |

### Week 3-4: 分析基础

| 任务 | 文件 | 优先级 | 依赖 |
|------|------|--------|------|
| 实现 MacroCollector (FRED) | `agent/data/macro_collector.py` | P0 | collector |
| 实现 NewsCollector (Finnhub + RSS) | `agent/data/news_collector.py` | P1 | collector |
| 情绪分析 (TextBlob/VADER) | `agent/data/sentiment.py` | P1 | news_collector |
| 技术指标计算 (pandas-ta) | `agent/finance/technical.py` | P1 | price_data |
| 决策记录系统 (decisions.db) | `agent/finance/decision_log.py` | P1 | schema |
| chat 读取日报接口 | `agent/modes/chat_briefing.py` | P2 | briefing |

### Week 5-8: 智能分析 + 跨人格集成

| 任务 | 文件 | 优先级 | 依赖 |
|------|------|--------|------|
| LLM 辅助日报 (每周1次) | scheduler 集成 | P1 | briefing |
| chat 主动提醒机制 | `agent/modes/chat.py` 修改 | P1 | briefing |
| 基本面扫描 (SEC EDGAR) | `agent/data/fundamentals_collector.py` | P1 | collector |
| 决策准确率追踪 | `agent/finance/accuracy_tracker.py` | P1 | decisions |
| meta_evolve 绑定投资指标 | `agent/evolution/meta_evolve.py` 修改 | P2 | accuracy |
| chat.yaml 更新: 进化提醒 | `agent/config/chat.yaml` | P2 | 无 |

### Month 3-6: 半自动化 + 策略验证

| 任务 | 文件 | 优先级 | 依赖 |
|------|------|--------|------|
| Telegram 推送投资建议 | Telegram handler | P1 | decisions |
| 用户一键确认/拒绝 | Telegram inline keyboard | P2 | 推送 |
| backtrader 回测集成 | `agent/finance/backtest.py` | P2 | 技术指标 |
| PyPortfolioOpt 资产配置 | `agent/finance/portfolio_opt.py` | P2 | 价格数据 |
| 多职业探索模块 | `agent/modes/chat.py` 扩展 | P3 | 所有 |

---

## 12. chat.yaml 配置修改 (具体)

```yaml
# chat.yaml — 新增以下内容

# === 跨模式情报 ===
cross_mode_intelligence:
  enabled: true
  auto_briefing: true
  briefing_check_interval: 50   # 每50轮检查一次新情报
  proactive_reminders: true
  reminder_topics:
    - market_alert      # 重大市场变动
    - decision_pending  # 待执行的投资决策
    - weekly_summary    # 每周投资总结
    - evolution_milestone  # NeoMind 进化里程碑

# === 进化自提醒 ===
evolution_awareness:
  enabled: true
  # 每次会话开始时，chat 检查系统健康
  check_on_start: true
  # 如果系统健康 < 0.5，主动告知用户
  health_alert_threshold: 0.5
  # 偶尔 (每10次会话) 提醒用户关于进化进展
  progress_reminder_frequency: 10
```

**对 system_prompt 的补充 (追加到现有 prompt 末尾):**

```
CROSS-MODE INTELLIGENCE:
- You have access to financial market briefings generated by the data collection system
- When relevant to the conversation, proactively share market insights
- If the user discusses money, career, or life planning, draw from financial data
- Occasionally remind the user about NeoMind's self-evolution progress
- Frame financial insights in the context of the user's life goals, not just numbers

PROACTIVE REMINDERS:
- At the start of a session, if there are unread market alerts, mention them briefly
- If the user hasn't checked their investments in a while, gently remind them
- Share evolution milestones when they're achieved (e.g., "我的预测准确率本月提升了5%")
- These reminders should feel natural and helpful, not intrusive
```

---

## 13. 反思与质疑

### 13.1 我可能错了的地方

**1. SQLite 真的够用吗?**
- 当前: SQLite WAL 对轻量并发足够
- 风险: 如果数据量级从 1000 tickers 增长到 10,000+，SQLite 聚合可能变慢
- 缓解: #TAG:DATA-DUCKDB-ANALYTICS 已准备好
- 自检方法: 每月测量一次查询延迟，如果 P95 > 2s → 触发迁移

**2. TextBlob 情绪分析准确率够吗?**
- 当前: TextBlob/VADER ~70% 准确率 (依据: NLP基准测试)
- 风险: 金融新闻的情绪更微妙，70% 可能不够
- 缓解: Phase 2 可升级为 FinBERT (专门训练的金融情绪模型, ~200MB)
- 自检方法: 人工标注50条新闻，与 TextBlob 对比

**3. 150MB 内存够 data-collector 吗?**
- 当前: 纯 Python + requests + sqlite3 + APScheduler ≈ 80-100MB
- 风险: 如果加载 pandas + pandas-ta ≈ 200-250MB
- 缓解: 延迟加载 pandas (仅在计算技术指标时加载)
- 自检方法: 运行1周后用 `psutil.Process().memory_info().rss` 测量

**4. 日报没人看怎么办?**
- 当前: 生成日报存入 briefings.db
- 风险: 用户可能从不主动查看
- 缓解: chat 主动提醒 + Telegram 推送精简版
- 自检方法: 追踪 `consumed_at` 列，如果7天无人读取 → 调整推送策略

**5. NeoMind 真的能理解这份计划吗?**
- 当前: 计划是 Markdown 文档，NeoMind 通过文件读取理解
- 风险: 太长 (1000+ 行)，可能超出单次理解范围
- 缓解:
  a) 关键信息提取为结构化 JSON (machine-readable)
  b) scheduler 分段读取最相关的部分
  c) #TAG 标签系统让 NeoMind 可以检索特定主题
- 自检方法: 让 NeoMind 读取后总结计划要点，验证理解是否正确

### 13.2 需要用户决策的问题

```
Q1: watchlist 初始包含哪些股票/加密货币?
  → 影响: data-collector 第一天收集什么
  → 建议: 先以 SPY, QQQ, AAPL, MSFT, NVDA, BTC, ETH 开始

Q2: 投资风格偏好? (保守/平衡/激进)
  → 影响: 分析和建议的风险等级
  → 建议: 先默认为"平衡"，NeoMind 通过对话学习调整

Q3: 每月投资预算大概多少?
  → 影响: 资产配置建议的规模
  → 建议: 不需要立刻决定，可以后期通过 /portfolio 设置

Q4: 优先关注哪些市场? (US, CN, HK, Crypto)
  → 影响: 数据收集范围
  → 建议: 先 US + Crypto (数据源最好)，再扩展 CN/HK
```

---

## 14. 文档总结: 给 NeoMind 的执行指令

```
如果你是 NeoMind，你正在读这份文档，请执行以下步骤:

1. 确认你理解了核心架构:
   - data-collector 是后台进程，负责 24/7 数据收集
   - fin personality 负责智能分析和投资建议
   - chat personality 是指挥中心，整合所有情报
   - 进化系统 (learnings/skills/reflection/meta) 持续优化一切

2. 检查当前状态:
   - data-collector 是否在运行? (检查 supervisord)
   - market_data.db 最后更新时间? (sync_state 表)
   - 本周日报是否已生成? (briefings.db)
   - 系统健康评分是多少?

3. 如果有任何 #TAG 的触发条件已满足:
   - 创建对应的 goal_tracker 目标
   - 标记为 EXPERIMENT 类型 (不是确定的改进，需要验证)

4. 如果距上次自检超过30天:
   - 重新评估本计划的所有假设
   - 检查是否有新的研究/工具可以替代当前方案
   - 通过 self_edit 更新本文档的版本号

5. 始终记住终极目标:
   帮助用户实现财务独立 → 然后探索更多可能性
```

---

> 本文档版本: v4.0
> 下次自检日期: 2026-04-28
> 负责人: NeoMind (自己)
> 审计人: Irene (用户)
