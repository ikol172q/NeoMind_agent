# NeoMind Telegram 测试指南

## 0. 启动前准备

### 环境变量（`.env`）

```bash
# 必须
TELEGRAM_BOT_TOKEN=<从 @BotFather 获取>
DEEPSEEK_API_KEY=<你的 DeepSeek key>

# 可选
TELEGRAM_AUTO_DETECT=true            # 群里自动检测金融话题
TELEGRAM_ALLOWED_GROUPS=-100xxxxx    # 限制群 ID（逗号分隔）
TELEGRAM_ADMIN_USERS=123456789       # 管理员 user ID
```

### 启动（Docker）

```bash
# ── 首次 build（或代码有改动后重新 build）──
docker compose build neomind-telegram

# ── 启动 Telegram bot ──
docker compose up neomind-telegram        # 前台（看日志）
docker compose up -d neomind-telegram     # 后台

# ── 看日志 ──
docker compose logs -f neomind-telegram

# ── 重启（改了代码后）──
docker compose build neomind-telegram && docker compose up -d neomind-telegram

# ── 如果同时需要 CLI ──
docker compose up neomind neomind-telegram

# ── 全家桶（NeoMind + OpenClaw + SearXNG）──
docker compose --profile full --profile search up -d
```

看到以下输出就表示启动成功：
```
[neomind] DeepSeek API: ✓
[neomind] Telegram Bot: ✓
[neomind] Starting as Telegram bot daemon...
[debug] Components loaded: [...]
[bot] Registering 17 command handlers...
```

### 启动（无 Docker / 本地调试）

```bash
python -c "
import asyncio
from agent.integration.telegram_bot import run_telegram_bot
asyncio.run(run_telegram_bot({}))
"
```

---

## 1. 基础功能验证（5 分钟）

发送以下命令，确认 bot 能正常响应：

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 1.1 | `/start` | 欢迎信息 + 功能列表 | ☐ |
| 1.2 | `/help` | 分类命令参考（金融、Web、工作流等） | ☐ |
| 1.3 | `/status` | 当前模式、provider、搜索状态、内存状态 | ☐ |
| 1.4 | `/mode` | 显示当前模式 + 可选模式（chat/fin/coding） | ☐ |

---

## 2. 模式切换（Mode）

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 2.1 | `/mode chat` | 切换到 Chat 模式 | ☐ |
| 2.2 | `/mode fin` | 切换到 Finance 模式 | ☐ |
| 2.3 | `/mode coding` | 切换到 Coding 模式 | ☐ |
| 2.4 | `/mode` | 显示当前模式 | ☐ |

---

## 3. 金融功能（Finance — `/mode fin` 下测试）

### 3.1 核心查询

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 3.1.1 | `/stock AAPL` | Apple 股价、基本面、分析 | ☐ |
| 3.1.2 | `/stock TSLA` | Tesla 股价 | ☐ |
| 3.1.3 | `/crypto BTC` | BTC 价格、市值、24h 变动 | ☐ |
| 3.1.4 | `/crypto ETH` | ETH 价格 | ☐ |

### 3.2 新闻与摘要

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 3.2.1 | `/news Fed rate cut` | 多源新闻搜索结果 | ☐ |
| 3.2.2 | `/news 央行降息` | 中文新闻搜索 | ☐ |
| 3.2.3 | `/digest` | 每日市场摘要（可能附 HTML 文件） | ☐ |

### 3.3 金融计算

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 3.3.1 | `/compute compound 10000 0.08 10` | 复利计算结果 | ☐ |
| 3.3.2 | `/compute sharpe 0.12 0.04 0.15` | Sharpe ratio 计算 | ☐ |
| 3.3.3 | `/compute var 100000 0.02 1.65` | VaR 计算 | ☐ |

### 3.4 预测与对比

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 3.4.1 | `/predict NVDA bullish 0.8 "AI growth"` | 记录预测成功 | ☐ |
| 3.4.2 | `/compare AAPL MSFT` | 两个资产对比 | ☐ |
| 3.4.3 | `/watchlist add AAPL` | 添加到关注列表 | ☐ |
| 3.4.4 | `/watchlist` | 查看关注列表 | ☐ |
| 3.4.5 | `/sources` | 数据源信任评分 | ☐ |

### 3.5 金融自动检测（群聊中）

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 3.5.1 | `$AAPL 今天怎么样` | 自动识别并回复（需要 TELEGRAM_AUTO_DETECT=true） | ☐ |
| 3.5.2 | `比特币最近走势如何` | 自动识别金融关键词 | ☐ |

---

## 4. 对话功能（Chat — `/mode chat` 下测试）

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 4.1 | `你好，介绍一下你自己` | 自然语言对话回复 | ☐ |
| 4.2 | `帮我解释一下 Python 装饰器` | 详细解释 | ☐ |
| 4.3 | `/think` | 切换深度思考模式 | ☐ |
| 4.4 | `分析一下这段代码有什么问题：def f(x): return x/0` | 深度思考分析（如已开启） | ☐ |
| 4.5 | `/think` | 关闭深度思考模式 | ☐ |

---

## 5. Web 命令

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 5.1 | `/read https://httpbin.org/html` | 提取并显示网页内容 | ☐ |
| 5.2 | `/links https://github.com` | 提取页面所有链接（内部/外部） | ☐ |
| 5.3 | `/read 1` | 跟进上一条 /links 的第 1 个链接 | ☐ |
| 5.4 | `/crawl https://httpbin.org --depth 1 --max 3` | BFS 爬取（小范围测试） | ☐ |

---

## 6. Hacker News

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 6.1 | `/hn` | 默认显示 top 5 HN 故事 | ☐ |
| 6.2 | `/hn best` | Best stories | ☐ |
| 6.3 | `/hn ask` | Ask HN stories | ☐ |
| 6.4 | `/hn show` | Show HN stories | ☐ |
| 6.5 | `/subscribe hn` | 订阅 HN 推送 | ☐ |
| 6.6 | `/subscribe off` | 取消订阅 | ☐ |

---

## 7. 工作流与安全（Workflow）

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 7.1 | `/sprint start "测试任务"` | 开始一个 sprint | ☐ |
| 7.2 | `/sprint status` | 查看 sprint 状态 | ☐ |
| 7.3 | `/sprint advance` | 推进 sprint 阶段 | ☐ |
| 7.4 | `/sprint complete` | 完成 sprint | ☐ |
| 7.5 | `/careful on` | 开启安全警告模式 | ☐ |
| 7.6 | `/careful status` | 查看安全模式状态 | ☐ |
| 7.7 | `/careful off` | 关闭安全模式 | ☐ |
| 7.8 | `/evidence recent 5` | 查看最近 5 条操作审计 | ☐ |
| 7.9 | `/evidence stats` | 审计统计 | ☐ |

---

## 8. Skills 与 Persona

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 8.1 | `/skills` | 列出当前模式可用的 skills | ☐ |
| 8.2 | `/skills all` | 列出所有 skills | ☐ |
| 8.3 | `/persona` | 查看/切换投资角色 | ☐ |
| 8.4 | `/rag status` | 查看 RAG 语料库状态 | ☐ |
| 8.5 | `/tune` | 自调优界面 | ☐ |

---

## 9. 系统管理

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 9.1 | `/context` | 当前对话 token 用量 | ☐ |
| 9.2 | `/history` | 最近对话历史 | ☐ |
| 9.3 | `/usage` | API 调用统计 | ☐ |
| 9.4 | `/provider` | 当前 LLM provider 状态 | ☐ |
| 9.5 | `/archive` | 归档当前对话 | ☐ |
| 9.6 | `/clear` | 清空 LLM 上下文 | ☐ |
| 9.7 | `/admin` | 管理面板（需要 admin 权限） | ☐ |

---

## 10. 新增功能（本次重构后）

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 10.1 | `/arch` | 生成架构图 HTML + JSON + 审计结果 | ☐ |
| 10.2 | `/arch audit` | 仅运行审计（不重新生成） | ☐ |
| 10.3 | `/arch json` | 仅输出 JSON | ☐ |
| 10.4 | `/dashboard` | 生成 evolution 仪表盘 HTML | ☐ |
| 10.5 | `/evolve status` | 查看自进化状态 | ☐ |
| 10.6 | `/evolve health` | 运行健康检查 | ☐ |
| 10.7 | `/upgrade check` | 检查可用更新 | ☐ |

---

## 10b. LLM 分析命令（通过 LLM 路由）

这些命令之前在 Telegram 里不可用，现在会路由到 LLM 处理：

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 10b.1 | `/summarize Python是一种编程语言，用于...` | LLM 返回摘要 | ☐ |
| 10b.2 | `/reason 如果所有A是B，所有B是C，那么所有A是C吗` | LLM 链式推理 | ☐ |
| 10b.3 | `/explain def fib(n): return n if n<2 else fib(n-1)+fib(n-2)` | LLM 代码解释 | ☐ |
| 10b.4 | `/translate Hello World to Japanese` | LLM 翻译 | ☐ |
| 10b.5 | `/generate 写一首关于AI的俳句` | LLM 生成内容 | ☐ |
| 10b.6 | `/search 最新AI新闻` | LLM 搜索回复 | ☐ |
| 10b.7 | `/plan 开发一个待办事项APP` | LLM 生成计划 | ☐ |

---

## 11. 群聊特定功能

在群聊环境中测试（需要把 bot 加入群组）：

| # | 操作 | 预期 | 通过？ |
|---|------|------|--------|
| 11.1 | 发送 `/neo_stock AAPL` | bot 响应（/neo_ 前缀在群聊中生效） | ☐ |
| 11.2 | @bot名 + 问题 | @mention 触发回复 | ☐ |
| 11.3 | 回复 bot 的消息 | bot 识别为 reply-to-me，继续对话 | ☐ |
| 11.4 | 发送不含关键词的普通消息 | bot 不响应（避免刷屏） | ☐ |

---

## 12. 边界与异常测试

| # | 发送 | 预期 | 通过？ |
|---|------|------|--------|
| 12.1 | `/stock` （无参数） | 友好提示用法 | ☐ |
| 12.2 | `/stock INVALIDTICKER999` | 优雅报错（查不到数据） | ☐ |
| 12.3 | `/compute` （无参数） | 显示用法提示 | ☐ |
| 12.4 | `/mode invalid` | 提示可用模式 | ☐ |
| 12.5 | `/unknowncmd` | 提示未知命令（typo handler） | ☐ |
| 12.6 | 发送超长消息（4000+ 字） | bot 能处理，回复可能被截断 | ☐ |
| 12.7 | 快速连发 5 条消息 | 限流保护，部分消息被跳过 | ☐ |

---

## 测试顺序建议

```
1. 私聊先测：/start → /help → /status → /mode fin
2. 金融核心：/stock → /crypto → /news → /digest → /compute
3. 对话能力：/mode chat → 自由聊天 → /think
4. Web 功能：/read → /links → /crawl
5. 工作流：/sprint → /careful → /evidence
6. 新功能：/arch
7. 群聊测试：/neo_ 前缀 → @mention → auto-detect
8. 边界测试：空参数 → 错误输入 → 限流
```

## 常见问题

| 问题 | 排查 |
|------|------|
| bot 不响应 | 检查 TELEGRAM_BOT_TOKEN 是否正确，终端有无报错 |
| `/stock` 报错 | 检查网络、API key（Finnhub/yfinance），DataHub 是否可用 |
| `/digest` 无内容 | 检查搜索组件是否初始化成功 |
| 群聊不响应 | 检查 TELEGRAM_ALLOWED_GROUPS，或用 /neo_ 前缀 |
| 回复被截断 | 正常——Telegram 限制 4096 字符/消息 |
| `/arch` 报错 | 确认 `scripts/gen_architecture.py` 存在且可执行 |
