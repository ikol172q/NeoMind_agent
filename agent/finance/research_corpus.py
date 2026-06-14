"""Serenity (@aleabitoreddit) 一手研究语料库.

存储 X / Substack / (将来 Reddit) 的**原始**帖子到 `research_corpus` 表,提供只读查询 API、
每日增量抓取(Apify kaitoeasyapi)、截图 ingest 兜底、以及本地媒体服务。

原则:杜绝二手消息——只存原话 + 原图(raw_json 全量保留),分析是单独一层。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse

DB_PATH = os.path.expanduser("~/.neomind/fin/fin.db")
ARCHIVE = os.path.expanduser("~/.neomind/fin/research_archive/serenity")
MEDIA_DIR = os.path.join(ARCHIVE, "media")
APIFY_TOKEN_FILE = os.path.expanduser("~/.apify_token")
ACTOR = "kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest"
HANDLE = "aleabitoreddit"

_TICK = re.compile(r"\$([A-Za-z]{1,6})\b")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def _tickers(text: str) -> List[str]:
    return sorted({"$" + m.upper() for m in _TICK.findall(text or "")})


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _ensure_table() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_corpus (
              post_id TEXT PRIMARY KEY, platform TEXT NOT NULL,
              author TEXT DEFAULT 'aleabitoreddit', kind TEXT, created_at TEXT,
              url TEXT, title TEXT, text TEXT, is_reply INTEGER DEFAULT 0,
              tickers TEXT, media_paths TEXT, metrics TEXT, raw_json TEXT NOT NULL,
              source_method TEXT DEFAULT 'apify', ingested_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_rc_platform ON research_corpus(platform);
            CREATE INDEX IF NOT EXISTS idx_rc_created  ON research_corpus(created_at);
            CREATE INDEX IF NOT EXISTS idx_rc_kind     ON research_corpus(kind);
            """
        )


def _x_created(s: str) -> Optional[str]:
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").isoformat()
    except Exception:
        return None


def _upsert(row: tuple) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO research_corpus VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )


def ingest_x_item(it: Dict[str, Any], manifest: Optional[Dict[str, list]] = None) -> str:
    """把一条 kaitoeasyapi 推文 upsert 进表,返回 post_id."""
    tid = str(it.get("id"))
    txt = it.get("text", "") or ""
    metrics = json.dumps({k: it.get(k + "Count") for k in ("like", "reply", "retweet", "quote", "view")})
    media = (manifest or {}).get(tid, [])
    pid = f"x:{tid}"
    _upsert((
        pid, "x", "aleabitoreddit", "reply" if it.get("isReply") else "tweet",
        _x_created(it.get("createdAt", "")), it.get("url"), None, txt,
        1 if it.get("isReply") else 0, json.dumps(_tickers(txt)),
        json.dumps(media), metrics, json.dumps(it, ensure_ascii=False), "apify", _now(),
    ))
    return pid


# ---------------------------------------------------------------- Apify 抓取
def _apify_pull(max_items: int = 100) -> List[Dict[str, Any]]:
    token = open(APIFY_TOKEN_FILE).read().strip()
    inp = {"searchTerms": [f"from:{HANDLE}"], "maxItems": max_items, "queryType": "Latest"}
    url = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items?token={token}"
    req = urllib.request.Request(url, data=json.dumps(inp).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        items = json.load(urllib.request.urlopen(req, timeout=300))
    except Exception as e:
        raise RuntimeError(str(e).replace(token, "***")[:300])
    return [it for it in items if isinstance(it, dict) and not it.get("noResults") and it.get("id")]


def daily_sync(max_items: int = 100) -> Dict[str, Any]:
    """拉最新 max_items 条,upsert;返回新增/更新计数."""
    _ensure_table()
    items = _apify_pull(max_items)
    with _conn() as c:
        existing = {r[0] for r in c.execute("SELECT post_id FROM research_corpus WHERE platform='x'")}
    new = 0
    for it in items:
        if f"x:{it.get('id')}" not in existing:
            new += 1
        ingest_x_item(it)
    return {"pulled": len(items), "new": new, "updated": len(items) - new, "at": _now()}


def ingest_screenshot(text: str, created_at: Optional[str] = None, url: Optional[str] = None,
                      title: Optional[str] = None, platform: str = "x") -> str:
    """截图兜底:用户给截图,我 OCR 出原文后写入(source_method=screenshot)."""
    _ensure_table()
    key = re.sub(r"\W+", "", (text or "")[:40]) or _now()
    pid = f"shot:{platform}:{key}"
    _upsert((
        pid, platform, "aleabitoreddit", "tweet", created_at or _now(), url, title, text or "",
        0, json.dumps(_tickers((text or "") + " " + (title or ""))), "[]", "{}",
        json.dumps({"text": text, "via": "screenshot"}, ensure_ascii=False), "screenshot", _now(),
    ))
    return pid


# ---------------------------------------------------------------- 查询
def _row_to_dict(r: sqlite3.Row, with_raw: bool = False) -> Dict[str, Any]:
    d = {
        "post_id": r["post_id"], "platform": r["platform"], "kind": r["kind"],
        "created_at": r["created_at"], "url": r["url"], "title": r["title"], "text": r["text"],
        "is_reply": r["is_reply"], "tickers": json.loads(r["tickers"] or "[]"),
        "media_paths": json.loads(r["media_paths"] or "[]"), "metrics": json.loads(r["metrics"] or "{}"),
        "source_method": r["source_method"],
    }
    if with_raw:
        d["raw_json"] = r["raw_json"]
    return d


def stats() -> Dict[str, Any]:
    _ensure_table()
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM research_corpus").fetchone()[0]
        by_platform = dict(c.execute("SELECT platform,COUNT(*) FROM research_corpus GROUP BY platform").fetchall())
        by_kind = dict(c.execute("SELECT kind,COUNT(*) FROM research_corpus GROUP BY kind").fetchall())
        dr = c.execute("SELECT MIN(created_at),MAX(created_at) FROM research_corpus").fetchone()
        from collections import Counter
        cc: Counter = Counter()
        for (tj,) in c.execute("SELECT tickers FROM research_corpus WHERE tickers!='[]'"):
            for t in json.loads(tj):
                cc[t] += 1
    return {"total": total, "by_platform": by_platform, "by_kind": by_kind,
            "date_range": {"min": dr[0], "max": dr[1]}, "top_tickers": cc.most_common(30)}


def list_posts(platform=None, kind=None, ticker=None, q=None, limit=50, offset=0,
               originals_only=False) -> List[Dict[str, Any]]:
    _ensure_table()
    where, args = [], []
    if platform: where.append("platform=?"); args.append(platform)
    if kind: where.append("kind=?"); args.append(kind)
    if originals_only: where.append("is_reply=0")
    if ticker: where.append("tickers LIKE ?"); args.append(f'%"{ticker.upper()}"%')
    if q: where.append("(text LIKE ? OR title LIKE ?)"); args += [f"%{q}%", f"%{q}%"]
    sql = "SELECT * FROM research_corpus"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    with _conn() as c:
        return [_row_to_dict(r) for r in c.execute(sql, args)]


# ---------------------------------------------------------------- 学习层
CHOKEPOINT_LAYERS = {
    "材料/衬底": ["$AXTI", "$IQE", "$SOI", "$RPI", "$GFS"],
    "激光/光模块/CPO": ["$SIVE", "$LITE", "$AAOI", "$COHR", "$POET", "$MTSI"],
    "连接/DSP": ["$MRVL", "$CRDO", "$ALAB"],
    "代工/封装/测试": ["$TSEM", "$JBL", "$AEHR", "$TSM"],
    "算力/Neocloud": ["$NVDA", "$AVGO", "$AMD", "$NBIS", "$IREN", "$CRWV"],
    "存储": ["$SNDK", "$MU", "$EWY"],
    "国防/能源/其他": ["$RKLB", "$XLU", "$MP", "$KTOS"],
    "大盘/宏观(参照)": ["$MSFT", "$GOOGL", "$AMZN", "$META", "$INTC", "$AAPL", "$ARM"],
}


ANALYSIS = {
    "label": "分析层 · Claude 综合(基于他原文蒸馏,非他原话)",
    "updated": "2026-06-02",
    "method": "逆向拆 AI 供应链 → 找到单一来源、人人依赖却没人盯的「卡点元件」→ 把它的客户"
              "(公开 + 通过供应链/投资关系推断)全部映射 → 在机构反应前不对称下注。"
              "他的 $SIVE 报告即范例:CPO/光子的 CW 激光卡点,映射到 Apple/AMD/Marvell/Amazon 等。",
    "mental_model": "用「这是过去某赢家的同位」类比找新卡点 —— 他原话:SOI = 硅光子衬底的 AXTI;"
                    "SIVE = CPO 的 LITE。在衬底/激光/模块每一层找『还没被发现的那个』。",
    "stack": [
        {"layer": "衬底", "names": "SOI · AXTI · IQE"},
        {"layer": "CW 激光", "names": "SIVE(最高信念)"},
        {"layer": "光模块", "names": "LITE · AAOI · COHR · POET"},
        {"layer": "封装 / 测试", "names": "JBL · AEHR"},
    ],
    "flags": [
        "自报 YTD +3840% / +3152% / +1116% 极可疑 —— 只列赢家、从不报完整账户或亏损单。当营销看,不是真战绩。",
        "重度自我推广 +「bot farm 在攻击我的 SIVE」(置顶推)= 典型 talking his book(护盘),热度要打折。",
        "客户映射大量是推断(high confidence / likely / 投资关系映射),非确认;链断一环(如 AMD 不用 SIVE),论点就弱。",
        "SIVE 是斯德哥尔摩微盘 + 单一来源 = 二元脆弱;CPO 时点推迟或客户多源化可暴跌。",
    ],
    "takeaway": "方法是真聪明的(卡点映射 + 类比模型,值得学);但收益吹嘘和护盘要剥离 —— 学他怎么想,别信他报的数。",
}


# 供应链分层(上游→下游)+ 他陈述/推断过的供应关系边(grounded in 其 Substack + 推文)
SUPPLY_CHAIN_STAGES = [
    {"rank": 0, "stage": "材料/衬底", "tickers": ["$AXTI", "$SOI", "$IQE", "$RPI", "$GFS"]},
    {"rank": 1, "stage": "CW 激光/光源", "tickers": ["$SIVE"]},
    {"rank": 2, "stage": "光模块/CPO", "tickers": ["$LITE", "$AAOI", "$COHR", "$POET", "$MTSI"]},
    {"rank": 3, "stage": "连接/DSP", "tickers": ["$MRVL", "$CRDO", "$ALAB"]},
    {"rank": 4, "stage": "封装/封测/代工", "tickers": ["$JBL", "$AEHR", "$TSEM", "$TSM"]},
    {"rank": 5, "stage": "加速器/算力", "tickers": ["$NVDA", "$AVGO", "$AMD"]},
    {"rank": 6, "stage": "Neocloud/数据中心", "tickers": ["$NBIS", "$IREN", "$CRWV"]},
    {"rank": 7, "stage": "超大规模(需求端)", "tickers": ["$MSFT", "$GOOGL", "$AMZN", "$META", "$AAPL"]},
]
SUPPLY_CHAIN_EDGES = [
    ("$AXTI", "$SIVE", "InP 衬底 → 激光", "structural"),
    ("$IQE", "$SIVE", "化合物半导体 epi → 激光", "structural"),
    ("$SOI", "$LITE", "SiPh 衬底 → 光模块", "structural"),
    ("$SIVE", "$JBL", "1.6T 可插拔合作", "disclosed"),
    ("$SIVE", "$POET", "CPO 外部光源(ELS)合作", "disclosed"),
    ("$SIVE", "$MRVL", "Marvell Celestial 直接供货", "high"),
    ("$SIVE", "$AAPL", "Apple 硅光子(Watch)", "high"),
    ("$SIVE", "$AMD", "经 Ayar / GlobalFoundries CPO", "inferred"),
    ("$LITE", "$NVDA", "光模块 → 加速器互联", "structural"),
    ("$AAOI", "$NVDA", "光模块 → 加速器互联", "structural"),
    ("$JBL", "$NVDA", "封装/制造 → 加速器", "structural"),
    ("$NVDA", "$NBIS", "加速器 → neocloud", "structural"),
    ("$NVDA", "$IREN", "加速器 → neocloud", "structural"),
    ("$NVDA", "$CRWV", "加速器 → neocloud", "structural"),
    ("$IREN", "$MSFT", "IREN $9.7B 微软 GPU 合同", "disclosed"),
    ("$CRWV", "$META", "CoreWeave–Meta $21B 合同", "disclosed"),
    ("$NBIS", "$MSFT", "neocloud ↔ 超大规模", "structural"),
]


def _ticker_counts():
    from collections import Counter
    cnt: Counter = Counter()
    first: Dict[str, str] = {}
    with _conn() as c:
        for created, tj in c.execute(
            "SELECT created_at,tickers FROM research_corpus WHERE tickers!='[]' ORDER BY created_at"
        ):
            for t in json.loads(tj):
                cnt[t] += 1
                if t not in first:
                    first[t] = created or ""
    return cnt, first


def chokepoint_map() -> Dict[str, Any]:
    """按 Serenity 的供应链瓶颈框架给他最常提的票归层(实时统计)."""
    _ensure_table()
    cnt, first = _ticker_counts()
    layers, mapped = [], set()
    for layer, ts in CHOKEPOINT_LAYERS.items():
        items = sorted(
            ({"ticker": t, "mentions": cnt[t], "first": (first.get(t) or "")[:10]} for t in ts if cnt[t]),
            key=lambda x: -x["mentions"],
        )
        mapped.update(ts)
        if items:
            layers.append({"layer": layer, "tickers": items})
    unmapped = [{"ticker": t, "mentions": n, "first": (first.get(t) or "")[:10]}
                for t, n in cnt.most_common(60) if t not in mapped][:15]
    return {"layers": layers, "unmapped": unmapped}


def supply_chain() -> Dict[str, Any]:
    """供应链 flow:节点(他实际提过的票,带层级/首提日/提及数)+ 供应关系边."""
    _ensure_table()
    cnt, first = _ticker_counts()
    nodes, present = [], set()
    for st in SUPPLY_CHAIN_STAGES:
        for t in st["tickers"]:
            if cnt.get(t):
                nodes.append({"ticker": t, "stage": st["stage"], "rank": st["rank"],
                              "mentions": cnt[t], "first": (first.get(t) or "")[:10]})
                present.add(t)
    edges = [{"from": a, "to": b, "note": n, "conf": c}
             for (a, b, n, c) in SUPPLY_CHAIN_EDGES if a in present and b in present]
    return {"nodes": nodes, "edges": edges,
            "note": "首提日来自语料(~2026-02 起,X 单搜上限);更早的喊单在他 Reddit/旧推,不在此窗口。边=他陈述/推断的供应关系(disclosed 已公布 / high 高信心 / inferred 推断 / structural 层级流)。"}


_PROFILE_CACHE: Dict[str, Any] = {}


_FOREIGN_YF = {"$SIVE": "SIVE.ST", "$IQE": "IQE.L", "$SOI": "SOI.PA"}  # 他的关键外国票 → yfinance 符号


def company_profile(ticker: str) -> Dict[str, Any]:
    """单个公司速览:yfinance 实时指标/简介 + 他陈述的上下游 + 数据推导的风险标记。零编造。"""
    t = ticker if ticker.startswith("$") else "$" + ticker.upper()
    sym = _FOREIGN_YF.get(t, t[1:])
    if sym not in _PROFILE_CACHE:
        info: Dict[str, Any] = {}
        try:
            import yfinance as yf
            info = yf.Ticker(sym).info or {}
        except Exception:
            info = {}
        _PROFILE_CACHE[sym] = info
    info = _PROFILE_CACHE[sym]
    g = info.get
    metrics = {
        "price": g("currentPrice") or g("regularMarketPrice"), "currency": g("currency"), "exchange": g("exchange"),
        "marketCap": g("marketCap"), "trailingPE": g("trailingPE"), "forwardPE": g("forwardPE"),
        "priceToSales": g("priceToSalesTrailing12Months"), "revenue": g("totalRevenue"),
        "revenueGrowth": g("revenueGrowth"), "grossMargin": g("grossMargins"), "profitMargin": g("profitMargins"),
        "beta": g("beta"), "wk52High": g("fiftyTwoWeekHigh"), "wk52Low": g("fiftyTwoWeekLow"),
    }
    up = [{"ticker": a, "note": n, "conf": c} for (a, b, n, c) in SUPPLY_CHAIN_EDGES if b == t]
    down = [{"ticker": b, "note": n, "conf": c} for (a, b, n, c) in SUPPLY_CHAIN_EDGES if a == t]
    flags: List[str] = []
    pm, ps, mc, cur = g("profitMargins"), g("priceToSalesTrailing12Months"), g("marketCap"), g("currency")
    if isinstance(pm, (int, float)) and pm < 0: flags.append("当前亏损(净利率 < 0)")
    if isinstance(ps, (int, float)) and ps > 20: flags.append(f"估值偏贵(P/S ≈ {ps:.0f}x)")
    if isinstance(mc, (int, float)) and mc < 5e9: flags.append("小盘(市值 < $5B,波动剧烈)")
    if cur and cur != "USD": flags.append(f"外国上市({cur};IBKR 可交易但有汇率/时段/流动性)")
    if not isinstance(mc, (int, float)): flags.append("yfinance 无完整财务数据(代码歧义/停牌/数据缺失)")
    cnt, first = _ticker_counts()
    stage = next((s["stage"] for s in SUPPLY_CHAIN_STAGES if t in s["tickers"]), None)
    return {
        "ticker": t, "name": g("longName") or g("shortName") or sym, "sector": g("sector"),
        "industry": g("industry"), "stage": stage, "summary": g("longBusinessSummary"),
        "metrics": metrics, "upstream": up, "downstream": down, "risk_flags": flags,
        "mentions": cnt.get(t, 0), "first": (first.get(t) or "")[:10],
        "data_note": "指标/简介=yfinance 实时(小盘/外国票可能缺失);上下游=他陈述/推断的关系;风险标记由数据推导,非投资建议。",
    }


def mention_timeline(top_n: int = 24) -> Dict[str, Any]:
    """每只票按周的提及强度(注意力/信念强度代理,非仓位——他不报金额)。行按首次提及周排序。"""
    from collections import Counter, defaultdict
    from datetime import datetime, timedelta
    perTW: Dict[str, Counter] = defaultdict(Counter)
    total: Counter = Counter()
    first: Dict[str, str] = {}
    weeks_set = set()
    with _conn() as c:
        for created, tj in c.execute(
            "SELECT created_at,tickers FROM research_corpus WHERE tickers!='[]' AND created_at IS NOT NULL ORDER BY created_at"
        ):
            try:
                d = datetime.fromisoformat(created).replace(tzinfo=None)
            except Exception:
                continue
            wk = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
            weeks_set.add(wk)
            for t in json.loads(tj):
                perTW[t][wk] += 1
                total[t] += 1
                if t not in first:
                    first[t] = created[:10]
    weeks = sorted(weeks_set)
    rows = [{"ticker": t, "total": total[t], "first": (first.get(t) or "")[:10],
             "weekly": [perTW[t].get(w, 0) for w in weeks]} for t, _ in total.most_common(top_n)]

    def first_week(r):
        for i, n in enumerate(r["weekly"]):
            if n > 0:
                return i
        return 10 ** 6
    rows.sort(key=lambda r: (first_week(r), -r["total"]))
    return {"weeks": weeks, "rows": rows,
            "note": "格子亮度=当周提及次数(=他对该票注意力/信念强度的代理,非真实仓位——他从不报金额)。窗口 2/6 起;更早的喊单(如 AXTI 2022 在 Reddit)都压在最左周。行按首次提及周排序:上=最早。"}


def ticker_outcomes(top_n: int = 25) -> Dict[str, Any]:
    """他提及最多的 N 只票:自首次提及日起的收益(仅本语料窗口 ~4 个月;best-effort)."""
    _ensure_table()
    cnt, first = _ticker_counts()
    top = [t for t, _ in cnt.most_common(top_n)]
    rows: List[Dict[str, Any]] = []
    try:
        import yfinance as yf
        df = yf.download([t[1:] for t in top], period="1y", interval="1d",
                         auto_adjust=True, progress=False, group_by="ticker", threads=True)
    except Exception as e:
        return {"note": "yfinance 不可用", "error": str(e)[:200], "rows": []}
    for t in top:
        sym, fd = t[1:], (first.get(t) or "")[:10]
        rec = {"ticker": t, "mentions": cnt[t], "first": fd,
               "price_then": None, "price_now": None, "ret_pct": None}
        try:
            d = df[sym]["Close"].dropna()
            sub = d[d.index >= fd]
            if len(sub) > 1:
                p0, p1 = float(sub.iloc[0]), float(sub.iloc[-1])
                rec.update({"price_then": round(p0, 2), "price_now": round(p1, 2),
                            "ret_pct": round((p1 / p0 - 1) * 100, 1)})
        except Exception:
            pass
        rows.append(rec)
    return {"window_note": "收益仅覆盖语料窗口(~2026-02 起),非他的完整历史战绩", "rows": rows}


# ---------------------------------------------------------------- Router
def build_research_router() -> APIRouter:
    r = APIRouter(prefix="/api/research", tags=["research"])

    @r.get("/stats")
    def _stats():
        return stats()

    @r.get("/posts")
    def _posts(platform: Optional[str] = None, kind: Optional[str] = None,
               ticker: Optional[str] = None, q: Optional[str] = None,
               originals_only: bool = False, limit: int = Query(50, le=500), offset: int = 0):
        return list_posts(platform, kind, ticker, q, limit, offset, originals_only)

    @r.get("/ticker/{sym}")
    def _ticker(sym: str, limit: int = Query(300, le=1000)):
        s = sym if sym.startswith("$") else "$" + sym
        return list_posts(ticker=s, limit=limit)

    @r.get("/chokepoint_map")
    def _cmap():
        return chokepoint_map()

    @r.get("/analysis")
    def _analysis():
        return ANALYSIS

    @r.get("/supply_chain")
    def _sc():
        return supply_chain()

    @r.get("/profile/{ticker}")
    def _profile(ticker: str):
        return company_profile(ticker)

    @r.get("/timeline")
    def _timeline(top_n: int = Query(24, le=60)):
        return mention_timeline(top_n)

    @r.get("/outcomes")
    def _outcomes(top_n: int = Query(25, le=60)):
        return ticker_outcomes(top_n)

    @r.post("/sync")
    def _sync(max_items: int = 100):
        try:
            return daily_sync(max_items)
        except Exception as e:
            raise HTTPException(500, str(e)[:300])

    @r.post("/ingest_screenshot")
    def _shot(payload: Dict[str, Any] = Body(...)):
        if not payload.get("text"):
            raise HTTPException(400, "text required")
        pid = ingest_screenshot(payload["text"], payload.get("created_at"),
                                payload.get("url"), payload.get("title"),
                                payload.get("platform", "x"))
        return {"post_id": pid}

    @r.get("/media/{fname}")
    def _media(fname: str):
        if "/" in fname or ".." in fname:
            raise HTTPException(400, "bad name")
        fp = os.path.join(MEDIA_DIR, fname)
        if not os.path.exists(fp):
            raise HTTPException(404, "not found")
        return FileResponse(fp)

    return r
