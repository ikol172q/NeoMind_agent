# NeoMind Agent 搜索能力改进计划

> 调研日期: 2026-03-25 | 搜索次数: 22+ | 覆盖方案: 30+

---

## 一、现状诊断

NeoMind 当前搜索架构：
- **Web 搜索**: 仅依赖 DuckDuckGo（`duckduckgo-search` 库），存在速率限制、IP 封锁、结果质量不稳定的问题
- **内容提取**: 使用 `trafilatura`（这是正确选择，benchmark 表现最好）
- **金融模式**: 有 `hybrid_search.py` 支持多层搜索（DDG + Google News RSS + 可选 Tavily/Serper/SearXNG），但通用模式缺失
- **Reranking**: 已有 RRF（Reciprocal Rank Fusion），但缺少语义 reranking
- **Query Expansion**: 金融模式有 LLM query expansion，通用模式缺失
- **新闻搜索**: 仅依赖 RSS feeds，覆盖面有限

**核心问题**: 通用搜索（chat/coding 模式）过度依赖单一 DuckDuckGo 源，缺乏多源聚合、语义搜索、智能 reranking。

---

## 二、调研发现：所有候选方案

### A. AI 原生搜索 API（为 LLM/Agent 设计）

| 方案 | 特点 | 免费额度 | 价格 | 推荐度 |
|------|------|----------|------|--------|
| **Tavily** | AI 搜索引擎，直接返回 LLM 可用的聚合内容+引用，SimpleQA 93.3% 准确率 | 1000次/月 | $5/1k | ⭐⭐⭐⭐⭐ |
| **Exa.ai** | 语义/神经搜索，embedding-based next-link prediction，支持 Auto/Neural/Fast/Deep 模式 | 1000 credits | 按用量 | ⭐⭐⭐⭐⭐ |
| **Brave Search API** | 独立索引（300亿+页面），LLM Context API 返回智能分块，无追踪 | ~1000次/月($5 credit) | $5/1k | ⭐⭐⭐⭐⭐ |
| **You.com** | SimpleQA 93% 准确率，Deep Search + 结构化输出，MCP 支持 | 有免费层 | 按用量 | ⭐⭐⭐⭐ |
| **Perplexity Sonar** | 不返回链接列表，而是返回带引用的 LLM 生成回答，OpenAI 兼容接口 | 有限 | $5/1k | ⭐⭐⭐⭐ |
| **LinkUp** | GDPR 合规，内容授权而非爬取，适合受监管行业 | 有免费层 | 按用量 | ⭐⭐⭐ |
| **Firecrawl** | 搜索+爬取+AI提取一体化，返回 clean markdown，有 /agent 端点 | 有免费层 | 按用量 | ⭐⭐⭐⭐ |

### B. 传统 SERP API（结构化搜索引擎结果）

| 方案 | 特点 | 免费额度 | 价格 | 推荐度 |
|------|------|----------|------|--------|
| **Serper.dev** | 最快最便宜的 Google SERP API，<1s 响应 | 2500次 | $0.30-1.00/1k | ⭐⭐⭐⭐⭐ |
| **SerpAPI** | 支持 20+ 搜索引擎，最广泛覆盖 | 100次/月 | $50/5k | ⭐⭐⭐ |
| **Google Custom Search** | 官方 Google API，但范围受限 | 100次/天 | $5/1k (超额) | ⭐⭐ |
| **Kagi API** | 付费高质量搜索，元搜索引擎 | 无 | $25/1k | ⭐⭐⭐ |

### C. 自托管/开源搜索引擎

| 方案 | 特点 | 成本 | 推荐度 |
|------|------|------|--------|
| **SearXNG** | 元搜索引擎，聚合多个搜索引擎，无追踪，LangChain/LiteLLM 集成 | 免费（自托管） | ⭐⭐⭐⭐⭐ |
| **Meilisearch** | 全文+向量+地理搜索，适合本地数据 | 免费（自托管） | ⭐⭐⭐ |
| **Typesense** | 容错搜索，轻量级 Elasticsearch 替代 | 免费（自托管） | ⭐⭐⭐ |

### D. Web 内容提取/爬虫

| 方案 | 特点 | 推荐度 |
|------|------|--------|
| **Jina Reader (r.jina.ai)** | URL 前加前缀即可获取 LLM 友好内容，自动图片描述，搜索端点 s.jina.ai | ⭐⭐⭐⭐⭐ |
| **Crawl4AI** | GitHub 最热开源 LLM 爬虫，Playwright 异步，Apache 2.0，51K+ 开发者 | ⭐⭐⭐⭐⭐ |
| **Firecrawl** | 搜索+爬取一体，返回 markdown/JSON | ⭐⭐⭐⭐ |
| **ScrapeGraphAI** | LLM 驱动的结构化提取，用自然语言描述要什么 | ⭐⭐⭐⭐ |
| **trafilatura** | 当前已在用，benchmark 表现最好，保持 ✅ | ⭐⭐⭐⭐⭐ |

### E. 搜索结果 Reranking

| 方案 | 特点 | 推荐度 |
|------|------|--------|
| **FlashRank** | 超轻量 ~4MB，无需 GPU/Torch，CPU 即可运行，pip install flashrank | ⭐⭐⭐⭐⭐ |
| **Cohere Rerank 3.5** | 最强商用 reranker，提升准确率 20-35%，但增加 200-500ms 延迟 | ⭐⭐⭐⭐ |
| **rerankers 库** | 统一 API 支持 FlashRank/Cohere/Cross-encoder 等多种 reranker | ⭐⭐⭐⭐⭐ |
| **RRF (已有)** | 当前已实现，继续保留 ✅ | ⭐⭐⭐⭐ |

### F. 新闻 API

| 方案 | 特点 | 推荐度 |
|------|------|--------|
| **NewsAPI.ai** | AI 友好，实体/概念搜索，情感分析 | ⭐⭐⭐⭐ |
| **GNews** | 6万+源，22 语言，价格适中 | ⭐⭐⭐⭐ |
| **NewsData.io** | 有免费层，支持多语言 | ⭐⭐⭐ |
| **Google News RSS** | 免费，当前已在用 ✅ | ⭐⭐⭐ |

### G. 搜索增强技术

| 技术 | 说明 | 推荐度 |
|------|------|--------|
| **LLM Query Expansion** | 用 LLM 生成 2-3 个变体查询，提升召回率 ~6.7% | ⭐⭐⭐⭐⭐ |
| **Multi-query + RRF** | RAG-Fusion 方法：多查询 → 多结果集 → RRF 合并 | ⭐⭐⭐⭐⭐ |
| **Snowball Refinement** | 第一轮结果的实体用于第二轮查询（hybrid_search.py 已有） | ⭐⭐⭐⭐ |
| **MCP Web Search Server** | 通过 MCP 协议标准化搜索工具调用 | ⭐⭐⭐ |

---

## 三、改进 TODO 清单（按优先级排序）

### 🔴 P0 — 立即实施（影响最大，成本最低） ✅ 全部完成

- [x] **1. 将 `hybrid_search.py` 的多源聚合架构泛化到所有模式** ✅
  - 重构为 `agent/search/` 包，核心 `engine.py` 中 `UniversalSearchEngine` 替代 `OptimizedDuckDuckGoSearch`
  - chat/coding/finance 模式全部使用统一搜索引擎
  - 文件: `agent/search/engine.py`, `agent/search/sources.py`, `agent/search/__init__.py`

- [x] **2. 集成 Brave Search API 作为主力搜索源** ✅
  - `BraveSearchSource` 实现于 `agent/search/sources.py`
  - 独立索引，LLM Context API 支持
  - 免费方案，API key 可选（`BRAVE_API_KEY`）

- [x] **3. 集成 Serper.dev 作为 Google SERP 源** ✅
  - `SerperSource` 实现于 `agent/search/sources.py`
  - 2500 次免费额度，API key 可选（`SERPER_API_KEY`）

- [x] **4. 添加 FlashRank 轻量 reranker** ✅
  - `FlashReranker` 实现于 `agent/search/reranker.py`
  - ~4MB CPU 模型，懒加载，blend 60% semantic + 40% structural
  - Dockerfile 已添加 `flashrank` 依赖

- [x] **5. 将 Query Expansion 从金融模式提取为通用功能** ✅
  - `QueryExpander` 实现于 `agent/search/query_expansion.py`
  - 4 策略: synonym / cross-language EN↔ZH / time-scope / question reformulation
  - 支持 general/finance 领域的不同同义词表

### 🟡 P1 — 短期实施（1-2 周） ✅ 全部完成

- [x] **6. 集成 Jina Reader (r.jina.ai / s.jina.ai)** ✅
  - `JinaSearchSource` 实现于 `agent/search/sources.py`
  - 搜索端点 `s.jina.ai` + 阅读端点 `r.jina.ai`
  - API key 可选（`JINA_API_KEY`），有 key 时才启用

- [x] **7. 集成 Tavily 作为 AI 原生搜索备选** ✅
  - `TavilySource` 实现于 `agent/search/sources.py`
  - 1000 次/月免费额度，API key 可选（`TAVILY_API_KEY`）

- [x] **8. 集成 Crawl4AI 作为内容提取备选** ✅
  - `Crawl4AIExtractor` 实现于 `agent/search/sources.py`
  - trafilatura 主力 → Crawl4AI 处理 JS 渲染页面的 fallback
  - 双重内容提取管道在 `engine.py` 中编排

- [x] **9. 搜索结果缓存系统升级** ✅
  - `SearchCache`（内存, 5min TTL）+ `DiskSearchCache`（SQLite, 24h TTL）
  - 实现于 `agent/search/cache.py`
  - 引擎自动查询双层缓存

- [x] **10. 新闻搜索增强** ✅
  - `NewsAPISource` 实现于 `agent/search/sources.py`（API key 可选: `NEWSAPI_API_KEY`）
  - `GoogleNewsRSSSource` 支持 en/zh 两种语言
  - 时间衰减权重 `compute_recency_boost()` 在 `engine.py` 中实现
  - 按语言过滤支持（`search_advanced(languages=[...])`)

### 🟢 P2 — 中期实施（2-4 周） ✅ 全部完成

- [x] **11. 部署 SearXNG 自托管实例** ✅
  - `docker-compose.yml` 中添加 `searxng` 服务（profiles: search, full）
  - `SearXNGSource` 实现于 `agent/search/sources.py`
  - 自动配置 JSON 格式输出，环境变量 `SEARXNG_URL`

- [x] **12. 集成 Exa.ai 语义搜索** ✅
  - `ExaSearchSource` (placeholder) 实现于 `agent/search/sources.py`
  - API key 可选（`EXA_API_KEY`），付费方案，先留 placeholder

- [x] **13. 统一搜索路由器（Search Router）** ✅
  - `QueryRouter` 实现于 `agent/search/router.py`
  - 5 种查询类型: news / tech / finance / academic / general
  - 每种类型有专属信任权重配置文件
  - 支持中英文 query 分类

- [x] **14. Cohere Rerank 作为高精度 reranker 选项** ✅
  - `CohereReranker` 实现于 `agent/search/reranker.py`
  - 付费方案，设置 `COHERE_API_KEY` + `pip install cohere` 后自动启用
  - 自动优先于 FlashRank（70% 语义 + 30% 结构分数混合）
  - 无 key 时 fallback 到 FlashRank（免费）

- [x] **15. 搜索质量监控仪表板** ✅
  - `SearchMetrics` 实现于 `agent/search/metrics.py`
  - JSONL 日志持久化（`~/.neomind/search_metrics.jsonl`）
  - `/search metrics` 和 `/search report` 命令集成到 `core.py`
  - 统计: 延迟 P50/P95、缓存命中率、源使用/故障、查询类型分布

### 🔵 P3 — 长期/可选 ✅ 全部完成

- [x] **16. You.com API 集成** ✅
  - `YouComSource` 实现于 `agent/search/sources.py`
  - 付费方案，设置 `YOUCOM_API_KEY` 后自动启用

- [x] **17. Perplexity Sonar API** ✅
  - `PerplexitySonarSource` 实现于 `agent/search/sources.py`
  - 返回 LLM 生成回答 + 引用 URL
  - 付费方案，设置 `PERPLEXITY_API_KEY` 后自动启用

- [x] **18. ScrapeGraphAI 集成** ✅
  - `ScrapeGraphAIExtractor` 实现于 `agent/search/sources.py`
  - 用自然语言描述数据提取需求，`pip install scrapegraphai`
  - 开源 MIT，需要 LLM 后端（默认 DeepSeek）

- [x] **19. 本地向量搜索** ✅
  - `LocalVectorStore` 实现于 `agent/search/vector_store.py`
  - FAISS + sentence-transformers（all-MiniLM-L6-v2）
  - SQLite 元数据存储，自动去重
  - 搜索结果自动后台索引
  - `pip install faiss-cpu sentence-transformers`

- [x] **20. MCP Web Search Server** ✅
  - `agent/search/mcp_server.py` — MCP 协议标准搜索服务器
  - 提供 `web_search` / `search_status` / `search_metrics` 三个工具
  - `python -m agent.search.mcp_server` 启动
  - `pip install mcp`

---

## 四、实施进度

```
✅ P0 任务 1-5 — 全部完成（2026-03-25）
   重构搜索架构 + Brave + Serper + FlashRank + Query Expansion

✅ P1 任务 6-10 — 全部完成（2026-03-25）
   Jina + Tavily + Crawl4AI + 分层缓存 + 新闻增强

✅ P2 任务 11-15 — 全部完成（2026-03-25）
   SearXNG Docker + Exa + QueryRouter + Cohere Reranker + SearchMetrics

✅ P3 任务 16-20 — 全部完成（2026-03-25）
   You.com + Perplexity Sonar + ScrapeGraphAI + FAISS 向量搜索 + MCP Server
```

**实现原则**: 免费方案优先，付费方案留作 placeholder。所有 API key 均为可选，零配置即可工作（DDG + Google News RSS 兜底）。

## 五、预算估算（月度）

| 项目 | 费用 | 备注 |
|------|------|------|
| Brave Search API | $0-5 | 免费 credit 覆盖基础用量 |
| Serper.dev | $0 | 2500 次免费，之后 $1/1k |
| Tavily | $0 | 1000 次/月免费 |
| Exa.ai | $0 | 1000 credits 免费 |
| FlashRank | $0 | 完全免费开源 |
| SearXNG | $0 | 自托管 |
| Jina Reader | $0-5 | 有免费额度 |
| You.com | $0+ | 有免费层，按用量计费 |
| Perplexity Sonar | $0+ | ~$5/1k (sonar), ~$1/1k (sonar-small) |
| Cohere Rerank | $0+ | 按用量计费，可选 |
| FAISS + sbert | $0 | 完全免费开源 |
| MCP Server | $0 | 完全免费开源 |
| ScrapeGraphAI | $0 | 开源 MIT，需 LLM 后端 |
| **总计** | **$0-15/月** | 可用免费层覆盖大部分需求 |

---

## 六、已实现文件清单

```
agent/search/                    # 搜索引擎包
├── __init__.py                  # 包入口，导出所有组件
├── engine.py                    # UniversalSearchEngine 核心编排器（10步搜索管道）
├── sources.py                   # 13 个搜索源适配器（DDG, GNews, Brave, Serper,
│                                #   Tavily, Jina, Exa, NewsAPI, SearXNG, Crawl4AI,
│                                #   You.com, Perplexity, ScrapeGraphAI）
├── reranker.py                  # FlashReranker + RRFMerger + CohereReranker
├── query_expansion.py           # QueryExpander（4策略: synonym/cross-lang/time/reformulation）
├── router.py                    # QueryRouter（news/tech/finance/academic/general 分类+权重）
├── cache.py                     # SearchCache（内存5min）+ DiskSearchCache（SQLite 24h）
├── metrics.py                   # SearchMetrics（JSONL持久化 + 聚合报告）
├── vector_store.py              # LocalVectorStore（FAISS + sentence-transformers）
├── mcp_server.py                # MCP 协议搜索服务器
└── diagnose.py                  # CLI 诊断工具

agent/search_legacy.py           # 原 search.py 重命名，保留 OptimizedDuckDuckGoSearch 兼容
agent/search_engine.py           # 兼容桥接模块
agent/core.py                    # 已修改：使用 UniversalSearchEngine + /search status|metrics|report
agent/__init__.py                # 已修改：更新导出
.env.example                     # 已修改：添加所有搜索 API key 文档
docker-compose.yml               # 已修改：添加 SearXNG 服务
Dockerfile                       # 已修改：添加 flashrank 依赖
pyproject.toml                   # 已修改：添加 agent.search 包 + 依赖
SEARCH_USAGE_GUIDE.md            # 新增：搜索引擎使用说明文档
```

## 七、关键调研来源

- [Best Web Search APIs for AI 2026 - Firecrawl](https://www.firecrawl.dev/blog/best-web-search-apis)
- [7 Free Web Search APIs for AI Agents - KDnuggets](https://www.kdnuggets.com/7-free-web-search-apis-for-ai-agents)
- [Beyond Tavily - Complete Guide to AI Search APIs 2026](https://websearchapi.ai/blog/tavily-alternatives)
- [SERP API Comparison 2025 - DEV](https://dev.to/ritza/best-serp-api-comparison-2025-serpapi-vs-exa-vs-tavily-vs-scrapingdog-vs-scrapingbee-2jci)
- [Brave Search API](https://brave.com/search/api/)
- [Exa AI](https://exa.ai/)
- [FlashRank - GitHub](https://github.com/PrithivirajDamodaran/FlashRank)
- [Crawl4AI - GitHub](https://github.com/unclecode/crawl4ai)
- [Jina AI Reader](https://jina.ai/reader/)
- [SearXNG](https://searxng.org/)
- [Serper.dev](https://serper.dev/)
- [Tavily](https://www.tavily.com/)
- [rerankers - GitHub](https://github.com/AnswerDotAI/rerankers)
- [RAG-Fusion - GitHub](https://github.com/Raudaschl/rag-fusion)
- [LLM Query Expansion - Jina AI GitHub](https://github.com/jina-ai/llm-query-expansion)
