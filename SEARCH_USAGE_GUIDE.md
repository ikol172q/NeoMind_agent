# NeoMind 搜索引擎使用指南

> 版本: 2.0 | 更新日期: 2026-03-25

---

## 快速开始

NeoMind 的搜索引擎**零配置即可工作**——不需要任何 API key，DuckDuckGo + Google News RSS 会作为默认搜索源自动启用。

如果想要更好的搜索质量，可以按下面的步骤逐步添加更多搜索源。每多加一个源，搜索质量通过 RRF（Reciprocal Rank Fusion）融合都会有所提升。

---

## 架构概览

```
用户输入查询
    │
    ▼
┌─ Query Router ─────────────────────────────────────┐
│  根据查询内容自动分类:                              │
│  news / tech / finance / academic / general         │
│  → 调整各搜索源的信任权重                           │
└────────────────────────────────────────────────────┘
    │
    ▼
┌─ Query Expansion ──────────────────────────────────┐
│  生成 2-3 个查询变体:                               │
│  • 同义词替换                                       │
│  • 中英跨语言翻译                                   │
│  • 时间范围扩展                                     │
│  • 疑问句→陈述句改写                                │
└────────────────────────────────────────────────────┘
    │
    ▼
┌─ Parallel Source Firing ───────────────────────────┐
│  所有可用搜索源并行发起请求:                        │
│  Tier 1 (免费无限) + Tier 2 (免费有限) + Tier 3    │
└────────────────────────────────────────────────────┘
    │
    ▼
┌─ RRF Merge + Temporal Ranking ─────────────────────┐
│  • 信任权重加权的 RRF 合并                          │
│  • 跨源出现奖励（3+ 源出现 → +20%）                │
│  • 时间衰减加权（新闻越新越好）                     │
└────────────────────────────────────────────────────┘
    │
    ▼
┌─ FlashRank Semantic Reranking ─────────────────────┐
│  ~4MB CPU 模型，无需 GPU                            │
│  混合 60% 语义分数 + 40% 结构分数                   │
└────────────────────────────────────────────────────┘
    │
    ▼
┌─ Content Extraction ───────────────────────────────┐
│  trafilatura (主力) → Crawl4AI (JS 页面 fallback)  │
└────────────────────────────────────────────────────┘
    │
    ▼
┌─ Cache ────────────────────────────────────────────┐
│  内存 (5min TTL) + SQLite 磁盘 (24h TTL)           │
└────────────────────────────────────────────────────┘
```

---

## 搜索源配置

### Tier 1 — 免费无限（自动启用，无需配置）

| 搜索源 | 说明 | 状态 |
|--------|------|------|
| **DuckDuckGo** | 通用搜索，英文/中文双区域 | 自动启用 |
| **Google News RSS** | 新闻搜索，英文/中文 | 自动启用 |

这两个源不需要任何配置，安装后即可使用。

### Tier 2 — 免费有额度（设置 API key 后启用）

在 `.env` 文件中添加对应的 API key 即可启用。每个源都是可选的，添加越多搜索质量越好。

| 搜索源 | 环境变量 | 免费额度 | 注册链接 | 推荐度 |
|--------|----------|----------|----------|--------|
| **Brave Search** | `BRAVE_API_KEY` | 注册送 $5 credit ≈ 1000 次/月 | [brave.com/search/api](https://brave.com/search/api/) | ⭐⭐⭐⭐⭐ |
| **Serper.dev** | `SERPER_API_KEY` | 注册送 2500 次 | [serper.dev](https://serper.dev/) | ⭐⭐⭐⭐⭐ |
| **Tavily** | `TAVILY_API_KEY` | 1000 次/月免费 | [tavily.com](https://www.tavily.com/) | ⭐⭐⭐⭐ |
| **NewsAPI** | `NEWSAPI_API_KEY` | 100 次/天免费 | [newsapi.org](https://newsapi.org/) | ⭐⭐⭐⭐ |
| **Jina AI** | `JINA_API_KEY` | 有免费额度 | [jina.ai/reader](https://jina.ai/reader/) | ⭐⭐⭐⭐ |
| **Exa.ai** | `EXA_API_KEY` | 注册送 1000 credits | [exa.ai](https://exa.ai/) | ⭐⭐⭐⭐ |
| **You.com** | `YOUCOM_API_KEY` | 有免费层 | [you.com](https://you.com/) | ⭐⭐⭐⭐ |
| **Perplexity Sonar** | `PERPLEXITY_API_KEY` | 有限免费 | [perplexity.ai](https://docs.perplexity.ai/) | ⭐⭐⭐⭐ |

**推荐顺序**: 如果只想加 1-2 个，优先加 **Brave** 和 **Serper**——一个独立索引 + 一个 Google 结果，互补性最强。

### Tier 3 — 自托管（无限制，需要 Docker）

| 搜索源 | 环境变量 | 说明 |
|--------|----------|------|
| **SearXNG** | `SEARXNG_URL` | 元搜索引擎，聚合 70+ 搜索引擎 |

启动方式：
```bash
# 使用 docker-compose 一键启动
docker compose --profile search up -d searxng

# 默认地址
# SEARXNG_URL=http://localhost:8888
```

---

## .env 配置示例

```bash
# 复制 .env.example 到 .env
cp .env.example .env

# ── 搜索 API Keys（所有都是可选的）──

# 推荐优先配置这两个：
BRAVE_API_KEY=BSA...your_key_here
SERPER_API_KEY=...your_key_here

# 可选（进一步提升质量）：
TAVILY_API_KEY=tvly-...your_key_here
NEWSAPI_API_KEY=...your_key_here
JINA_API_KEY=jina_...your_key_here
EXA_API_KEY=...your_key_here
YOUCOM_API_KEY=...your_key_here
PERPLEXITY_API_KEY=pplx-...your_key_here

# 高精度 Reranker（替代 FlashRank，付费）：
COHERE_API_KEY=...your_key_here

# 自托管 SearXNG：
SEARXNG_URL=http://localhost:8888
```

---

## 搜索命令

在 NeoMind 中可以使用以下搜索相关命令：

| 命令 | 说明 |
|------|------|
| `/search <query>` | 执行搜索 |
| `/search status` | 查看所有搜索源状态、启用情况 |
| `/search metrics` | 查看当前会话搜索统计（延迟、缓存命中率等） |
| `/search report` | 查看详细搜索质量报告（P50/P95 延迟、源使用情况、查询类型分布） |

**自动搜索**: NeoMind 会自动检测需要搜索的查询（包含 "news"、"latest"、"price"、日期等关键词），无需手动输入 `/search`。

---

## 诊断工具

如果搜索出现问题，可以运行内置诊断工具：

```bash
# 快速检查（不需要网络）
python -m agent.search.diagnose

# 完整检查（包含实际搜索测试）
python -m agent.search.diagnose --live
```

诊断工具会检查：
- 依赖安装情况（duckduckgo-search, feedparser, flashrank, trafilatura 等）
- API key 配置状态
- 搜索引擎初始化状态
- Query Router 分类测试
- Query Expansion 扩展测试
- (--live) 实际搜索端到端测试

---

## 智能搜索路由

搜索引擎会根据查询内容自动调整策略：

| 查询类型 | 示例 | 优先源 |
|----------|------|--------|
| **新闻** | "latest AI news", "最新政策" | Brave News, Google News, NewsAPI |
| **技术** | "python async tutorial", "react hooks" | Serper (Google), DDG, Jina |
| **金融** | "AAPL stock price", "央行降息" | 全源 + 金融 RSS |
| **学术** | "machine learning papers", "量子计算研究" | Exa (语义), Tavily (深度) |
| **通用** | "best restaurants in Tokyo" | 平衡权重 |

路由器使用正则模式匹配，支持中英文查询自动分类。

---

## 缓存策略

搜索结果使用两级缓存减少重复请求：

| 缓存层 | 存储 | TTL | 说明 |
|--------|------|-----|------|
| **内存缓存** | Python dict | 5 分钟（金融模式 15 分钟） | 相同查询秒级响应 |
| **磁盘缓存** | SQLite (~/.neomind/search_cache.db) | 24 小时 | 跨会话持久化 |

金融模式的内存缓存 TTL 更长（15 分钟），因为金融数据查询通常在短时间内会被重复访问。

---

## 搜索质量监控

搜索指标自动记录到 `~/.neomind/search_metrics.jsonl`，包括：
- 每次搜索的延迟（毫秒）
- 使用/失败的搜索源
- 结果数量和内容提取数量
- 查询类型分类
- 缓存命中情况

使用 `/search report` 查看聚合报告，包含 P50/P95 延迟、缓存命中率、各源使用频率等。

---

## 依赖安装

### 最小安装（仅 Tier 1）
```bash
pip install duckduckgo-search feedparser trafilatura
```

### 推荐安装（含 FlashRank reranker）
```bash
pip install duckduckgo-search feedparser trafilatura flashrank aiohttp lxml
```

### 完整安装（含所有可选组件）
```bash
pip install duckduckgo-search feedparser trafilatura flashrank aiohttp lxml crawl4ai exa_py
```

### Docker（含 SearXNG）
```bash
docker compose --profile full up -d
```

---

## 付费选项（Placeholder）

以下为付费方案，已在代码中预留接口，但**默认未启用**。等有需要时设置 API key 即可激活：

### Exa.ai 语义搜索
- **用途**: 基于 embedding 的语义搜索，适合探索性和复杂查询
- **价格**: 按用量计费，注册送 1000 credits
- **启用**: 设置 `EXA_API_KEY` 并安装 `pip install exa_py`
- **状态**: ✅ 已实现完整适配器

### Cohere Rerank
- **用途**: 高精度语义 reranker，比 FlashRank 准确率高 20-35%
- **价格**: 按用量计费
- **启用**: 设置 `COHERE_API_KEY` 并安装 `pip install cohere`
- **状态**: ✅ 已实现完整适配器，设置 key 后自动优先于 FlashRank
- **注意**: 日常使用 FlashRank（免费）已足够，Cohere 适合高价值查询场景

### You.com API
- **用途**: SimpleQA 93% 准确率，Web Search + AI Snippets
- **价格**: 按用量计费
- **启用**: 设置 `YOUCOM_API_KEY`
- **状态**: ✅ 已实现完整适配器

### Perplexity Sonar API
- **用途**: 返回带引用的 LLM 生成回答，适合需要直接答案的场景
- **价格**: ~$5/1k 次（sonar），~$1/1k（sonar-small）
- **启用**: 设置 `PERPLEXITY_API_KEY`
- **状态**: ✅ 已实现完整适配器

---

## 本地向量搜索（可选）

NeoMind 可以将历史搜索结果存储为向量，用于语义相似度检索。适合"之前搜过类似的吗？"类场景。

### 安装
```bash
pip install faiss-cpu sentence-transformers
```

### 工作原理
- 使用 `all-MiniLM-L6-v2`（~80MB）生成 embeddings
- FAISS 做快速向量检索（CPU，无需 GPU）
- 搜索结果自动在后台索引
- 数据存储在 `~/.neomind/vector_store/`

### 使用
向量搜索在引擎内部自动工作——每次搜索的结果都会被索引。如果需要手动查询相似历史：

```python
from agent.search import LocalVectorStore
store = LocalVectorStore()
similar = store.find_similar("之前搜过的某个话题", top_k=5)
```

---

## MCP 搜索服务器（可选）

NeoMind 的搜索能力可以通过 MCP（Model Context Protocol）协议暴露给外部 agent 和 IDE。

### 安装
```bash
pip install mcp
```

### 启动
```bash
python -m agent.search.mcp_server
```

### 提供的工具
| MCP Tool | 说明 |
|----------|------|
| `web_search` | 多源搜索（query, max_results, domain） |
| `search_status` | 搜索引擎状态 |
| `search_metrics` | 搜索质量指标 |

### 在 Claude Code 中使用
在 `.mcp.json` 中添加：
```json
{
  "mcpServers": {
    "neomind-search": {
      "command": "python",
      "args": ["-m", "agent.search.mcp_server"]
    }
  }
}
```

---

## ScrapeGraphAI 结构化提取（可选）

用自然语言描述想要提取什么数据，适合从网页中提取结构化信息（产品表格、价格列表等）。

### 安装
```bash
pip install scrapegraphai
```

### 使用
```python
from agent.search import ScrapeGraphAIExtractor
extractor = ScrapeGraphAIExtractor()
data = await extractor.extract_structured(
    url="https://example.com/products",
    prompt="Extract all product names and prices as a list"
)
```

需要一个 LLM 后端（默认使用 DeepSeek，通过 `DEEPSEEK_API_KEY`）。

---

## 文件结构

```
agent/search/                    # 搜索引擎包
├── __init__.py                  # 包入口，导出所有组件
├── engine.py                    # UniversalSearchEngine 核心编排器
├── sources.py                   # 13 个搜索源适配器（DDG, GNews, Brave, Serper,
│                                #   Tavily, Jina, Exa, NewsAPI, SearXNG, Crawl4AI,
│                                #   You.com, Perplexity, ScrapeGraphAI）
├── reranker.py                  # FlashReranker + RRFMerger + CohereReranker
├── query_expansion.py           # 查询扩展器（4 策略）
├── router.py                    # 查询路由器（5 类型）
├── cache.py                     # 双层缓存（内存 + SQLite）
├── metrics.py                   # 搜索质量指标追踪
├── vector_store.py              # 本地向量搜索（FAISS + sentence-transformers）
├── mcp_server.py                # MCP 协议搜索服务器
└── diagnose.py                  # CLI 诊断工具
```

---

## FAQ

**Q: 不配置任何 API key 能用吗？**
A: 可以。DuckDuckGo + Google News RSS 自动启用，零成本即可搜索。

**Q: 搜索很慢怎么办？**
A: 运行 `python -m agent.search.diagnose --live` 看哪个源慢。大部分情况下，第一次搜索较慢（需要初始化 FlashRank 模型），后续搜索会快很多。缓存命中时是毫秒级响应。

**Q: 怎么知道哪些源在工作？**
A: 在 NeoMind 中输入 `/search status`，会显示所有三个 Tier 的源启用状态。

**Q: FlashRank 模型会自动下载吗？**
A: 是的，第一次使用时会自动下载 ~4MB 模型到缓存目录。

**Q: 金融模式和通用模式搜索有什么区别？**
A: 金融模式会调整信任权重（偏向金融新闻源）、使用更快的时间衰减（小时级半衰期），以及更长的缓存 TTL（15 分钟）。

**Q: SearXNG 需要额外的服务器吗？**
A: 不需要独立服务器，`docker compose --profile search up -d searxng` 会在本地启动一个容器。资源占用很低。
