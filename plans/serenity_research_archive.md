# Serenity (@aleabitoreddit) 一手研究语料库 — living checklist

> ✅ **全部建成并浏览器实测通过 (2026-06-02)** — Phase 0-4 完成:
> 采集(X 3540+媒体1580+Substack1)→ 入库 fin.db `research_corpus` → API(8 端点)→ 每日自动 `serenity_sync` job + 手动 /sync + 截图 ingest → web `Serenity` 标签(渲染/统计/Chokepoint 地图/媒体服务均实测 OK)。
> 已知限:X 仅近 ~4 个月(单搜上限);Reddit 被墙跳过;Substack 仅 1 篇。

**目标**:把 Serenity 的一手内容(X / Substack / Reddit)永久归档 + 每日更新,集成进 NeoMind Fin dashboard,
用于从头复习他的 **Chokepoint Theory / CPO·硅光子** 投资思路。**杜绝二手消息**:存原话+原图,我的分析是单独一层。

## 已锁定决策
- crawl 用 **Apify `kaitoeasyapi` actor**(apidojo 返回空,已弃)。token 在 `~/.apify_token`(只读不打印)。
- Substack **不订阅** → 只存免费(audience=everyone)内容。
- 老推文(2022–2025)**跳过付费回填**(X 单搜上限 ~3.5k≈4 个月,且多为回复);早期思路靠 **Reddit + Substack** 覆盖。
- 永久存储:`~/.neomind/fin/research_archive/serenity/` + 入 `fin.db` + 每月 jsonl 导出。

## Phase 0 — 采集（免费优先）
- [x] X 近段(kaitoeasyapi): **3540 条 / 989 原创**,2026-02-06~06-02 → `x_raw.jsonl` + `x_originals.jsonl`
- [⚠] Reddit `u/AleaBito`:**本机 403 硬墙(数据中心 IP,换 UA/old.reddit 均失败)** — 待决策:Apify Reddit scraper(~几分钱)/ 用户粘贴关键帖 / 跳过
- [x] Substack:**仅 1 篇已发布长文**(Sivers CPO deep-dive,全文 1.6 万字符)→ `substack_full.jsonl`
- [x] 下载 X 媒体:**1580 张 / 175MB / 0 失败**(1161 条有图)→ `media/` + `media_manifest.json`

## Phase 1 — 存储 + 入库
- [x] `research_corpus` 表已建于 fin.db + ingest **3541 行**(X 989推+2551回复 / Substack 1),已抽 $ticker,按 post_id 去重
- [x] canonical:`schema.sql` 已补 `research_corpus` 表 + 3 索引
- [x] `agent/finance/research_corpus.py` 模块 + `build_research_router()` **已注册+重启+验证 `/api/research/stats` OK**
  - 端点:stats / posts(筛选) / ticker/{sym} / sync(手动增量) / ingest_screenshot(截图兜底) / media/{fname}
- 学习信号(提及最多):SIVE 545 / LITE 381 / AXTI 364 / AAOI 355 / NVDA 244 / MRVL 186 / COHR 172 / SOI 170 / IQE 162 / POET 112 → **压倒性 CPO/硅光子/化合物半导体链**

## Phase 2 — 每日更新
- [x] 截图 ingest 端点 `POST /api/research/ingest_screenshot`(兜底)+ 手动 `POST /api/research/sync`
- [x] `scheduler/jobs/serenity_sync.py`(每日 12:00 UTC `daily_sync()`)+ 注册 DEFAULT_JOBS — **重启验证: job 已注册 + /sync 端到端通(pulled 100/upsert OK)**

## Phase 3 — Dashboard 标签 `Research`
- [ ] `web/src/tabs/Research.tsx`:原始时间线(原话+原图)/ 搜索筛选(ticker/主题/平台/日期)
- [ ] `web/src/lib/api.ts` hooks

## Phase 4 — 学习层
- [ ] per-ticker 视图 + 自他提及日起的真实收益叠加(yfinance)
- [ ] Chokepoint 供应链地图(衬底→激光/CPO→…)+ thesis 演化轴
- [ ] 我的连接分析(单独标注,不混原文)
