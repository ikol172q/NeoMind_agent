"""Cockpit overview — ONE fan-out endpoint that aggregates the three-account
view for the trading cockpit:

  • Schwab       — manual value core (positions/summary)
  • IBKR-live    — quant account, real money (trading/ibkr positions + account)
  • IBKR-paper   — DORMANT slot (no paper gateway running; lights up later)

plus trading state (halt/kill/budget), regime posture, wash-sale events, and a
Schwab∩IBKR tax-overlap check.

Design choice: it SELF-CALLS the existing endpoints over localhost, so the
cockpit shows EXACTLY what each source endpoint returns (zero logic
duplication / no drift). Each sub-fetch is independent — one failing degrades
to an ``_error`` marker on that panel, never a dead page.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter

_BASE = "http://127.0.0.1:8001"


async def _get(client: httpx.AsyncClient, path: str,
               params: Optional[Dict] = None) -> Any:
    """Fetch one endpoint; on any failure return an error marker instead of
    raising, so a single bad source can't take down the whole cockpit."""
    try:
        r = await client.get(_BASE + path, params=params or {}, timeout=15.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}", "_path": path}


def _tickers(obj: Any, kind: str) -> set:
    try:
        if kind == "schwab":
            return {p["ticker"] for p in obj.get("by_ticker", [])}
        return {p["symbol"] for p in (obj or {}).get("positions", [])}
    except Exception:
        return set()


def _overlap(schwab: Any, ibkr_live: Any) -> Dict[str, Any]:
    """Tax hygiene: IBKR quant universe must stay disjoint from Schwab holdings
    (same-underlying options can trigger cross-broker wash sales)."""
    s = _tickers(schwab, "schwab")
    i = _tickers(ibkr_live, "ibkr")
    both = sorted(s & i)
    return {"schwab_tickers": sorted(s), "ibkr_tickers": sorted(i),
            "overlap": both, "clean": len(both) == 0}


def build_cockpit_router() -> APIRouter:
    router = APIRouter(prefix="/api/cockpit", tags=["cockpit"])

    @router.get("/overview")
    async def overview() -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            (schwab, ibkr_live, ibkr_acct, state,
             regime, wash) = await asyncio.gather(
                _get(client, "/api/positions/summary"),
                _get(client, "/api/trading/ibkr/positions"),
                _get(client, "/api/trading/ibkr/account"),
                _get(client, "/api/trading/state"),
                _get(client, "/api/regime/today"),
                _get(client, "/api/db/wash-sales"),
            )
        return {
            "schwab": schwab,
            "ibkr_live": {"positions": ibkr_live, "account": ibkr_acct},
            "ibkr_paper": {
                "enabled": False,
                "note": "DU 纸户休眠：paper gateway(4002) 未运行。"
                        "有过 DSR gate 的策略要 paper 确认时再启用。",
            },
            "state": state,
            "regime": regime,
            "wash_sales": wash,
            "overlap": _overlap(schwab, ibkr_live),
        }

    return router


# ── Self-contained cockpit page (served at /cockpit). Vanilla JS, no build. ──
COCKPIT_HTML = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading Cockpit</title>
<style>
  :root{--bg:#0e1116;--card:#161b22;--line:#2a3138;--txt:#e6edf3;--dim:#8b949e;
        --schwab:#4a90d9;--live:#e0a33e;--paper:#6b7280;--good:#3fb950;--bad:#f85149}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font:14px/1.45 -apple-system,SF Pro,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:1200px;margin:0 auto;padding:16px}
  h1{font-size:16px;margin:0 0 12px;font-weight:600}
  .muted{color:var(--dim)} .mono{font-variant-numeric:tabular-nums;
       font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .strip{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
  .pill{background:var(--card);border:1px solid var(--line);border-radius:6px;
        padding:5px 10px;font-size:12px;white-space:nowrap}
  .pill b{color:var(--txt)} .pill .k{color:var(--dim)}
  button{background:#21262d;color:var(--txt);border:1px solid var(--line);
         border-radius:6px;padding:6px 12px;font-size:13px;cursor:pointer}
  button:hover{border-color:#4a5560} button.warn{border-color:var(--bad);color:#ffb3ae}
  .banner{border-radius:6px;padding:8px 12px;margin-bottom:12px;font-size:13px}
  .banner.ok{background:#0f2a17;border:1px solid #1f5130;color:#7ee2a0}
  .banner.bad{background:#2a1213;border:1px solid #5a1f22;color:#ffb3ae}
  .cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:8px;
        padding:12px;border-left:3px solid var(--line)}
  .card.schwab{border-left-color:var(--schwab)}
  .card.live{border-left-color:var(--live)}
  .card.paper{border-left-color:var(--paper);opacity:.75}
  .card h2{font-size:13px;margin:0 0 2px;font-weight:600}
  .card .sub{font-size:11px;color:var(--dim);margin-bottom:10px}
  .kpi{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:10px}
  .kpi div{font-size:11px;color:var(--dim)} .kpi b{display:block;font-size:15px;color:var(--txt)}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  td,th{text-align:right;padding:3px 4px;border-bottom:1px solid #20262d}
  th{color:var(--dim);font-weight:500} td:first-child,th:first-child{text-align:left}
  .pos{color:var(--good)} .neg{color:var(--bad)}
  .badge{font-size:10px;padding:1px 6px;border-radius:4px;background:#21262d;color:var(--dim)}
  .err{color:var(--bad);font-size:12px}
</style></head>
<body><div class="wrap">
  <h1>Trading Cockpit <span class="muted" id="ts" style="font-size:11px;font-weight:400"></span></h1>
  <div class="strip" id="strip"></div>
  <div id="overlap"></div>
  <div class="cols" id="cols"></div>
</div>
<script>
const $=s=>document.querySelector(s);
const money=n=>n==null?'—':'$'+Number(n).toLocaleString('en-US',{maximumFractionDigits:0});
const pct=n=>n==null?'—':(n>=0?'+':'')+Number(n).toFixed(1)+'%';
const cls=n=>n==null?'':n>=0?'pos':'neg';
function exp(e){if(!e||e.length<8)return e||'';return (+e.slice(4,6))+'/'+(+e.slice(6,8));}
function posLine(p){
  if(p.sec_type==='OPT'){const q=(p.position>0?'+':'')+p.position;
    return `${p.symbol} ${exp(p.expiry)} ${p.strike}${p.right} <span class="mono">${q}</span>`;}
  return `${p.symbol} <span class="mono">${(p.position>0?'+':'')+p.position}</span>`;}
let STATE={};

async function load(){
  try{const d=await (await fetch('/api/cockpit/overview')).json();STATE=d;render(d);
    $('#ts').textContent='· '+new Date().toLocaleTimeString();
  }catch(e){$('#cols').innerHTML='<div class="err">加载失败: '+e+'</div>';}
}
function render(d){
  // status strip
  const st=d.state||{}, rg=d.regime||{};
  const halted=st.global_halt==1;
  $('#strip').innerHTML=`
    <span class="pill"><span class="k">Regime</span> risk <b>${(rg.risk_appetite_score??'—')}</b>
        · vol <b>${(rg.volatility_regime_score??'—')}</b> <span class="muted">(posture,非择时)</span></span>
    <span class="pill"><span class="k">auto_trade</span> <b>${st.auto_trade==1?'ON':'off'}</b></span>
    <span class="pill"><span class="k">allow_live</span> <b>${st.allow_live==1?'YES':'no'}</b></span>
    <span class="pill"><span class="k">halt</span> <b style="color:${halted?'var(--bad)':'var(--good)'}">${halted?'HALTED':'clear'}</b></span>
    <span class="pill"><span class="k">budget</span> <b>${money(st.trading_budget_usd)}</b></span>
    <button onclick="toggleHalt(${halted})" class="${halted?'':'warn'}">${halted?'Resume':'Halt'}</button>
    <button onclick="load()">↻ Refresh</button>`;
  // overlap banner
  const ov=d.overlap||{};
  $('#overlap').innerHTML = ov.clean
    ? `<div class="banner ok">✓ Schwab ∩ IBKR = ∅ · 税务干净（wash-sale 事件: ${d.wash_sales?.count??0}）</div>`
    : `<div class="banner bad">⚠ 重叠标的: ${(ov.overlap||[]).join(', ')} — 跨券商 wash-sale 风险！</div>`;
  $('#cols').innerHTML = schwabCard(d.schwab)+liveCard(d.ibkr_live)+paperCard(d.ibkr_paper);
}
function schwabCard(s){
  if(!s||s._error)return card('schwab','SCHWAB','手动 · 价值核心 · 长线','<div class="err">'+(s?._error||'无数据')+'</div>');
  const rows=(s.by_ticker||[]).map(t=>`<tr><td>${t.ticker}</td>
     <td class="mono">${(t.weight_pct||0).toFixed(0)}%</td>
     <td class="mono ${cls(t.unrealized_pct)}">${pct(t.unrealized_pct)}</td>
     <td class="mono">${money(t.market_value)}</td></tr>`).join('');
  const top3=(s.by_ticker||[]).slice(0,3).reduce((a,t)=>a+(t.weight_pct||0),0);
  const kpi=`<div class="kpi"><div>总值<b>${money(s.total_value)}</b></div>
     <div>未实现<b class="${cls(s.unrealized)}">${money(s.unrealized)}</b></div>
     <div>top-3 集中<b>${top3.toFixed(0)}%</b></div></div>`;
  return card('schwab','SCHWAB','手动 · 价值核心 · 长线',kpi+
     `<table><tr><th>票</th><th>权重</th><th>盈亏</th><th>市值</th></tr>${rows}</table>`);
}
function liveCard(l){
  const p=l?.positions, a=l?.account;
  if(!p||p._error||p.connected===false)
    return card('live','IBKR · LIVE','量化 · 真钱 · 只读','<div class="err">'+(p?._error||p?.error||'未连接')+'</div>');
  const v=a?.values||{};
  const kpi=`<div class="kpi"><div>NetLiq<b>${money(v.NetLiquidation)}</b></div>
     <div>现金<b>${money(v.TotalCashValue)}</b></div>
     <div>购买力<b>${money(v.BuyingPower)}</b></div></div>`;
  const rows=(p.positions||[]).map(x=>`<tr><td>${posLine(x)}</td>
     <td class="mono muted">@${x.avg_cost}</td></tr>`).join('');
  return card('live','IBKR · LIVE <span class="badge">readonly</span>','量化 · 真钱 · 只读看盘',kpi+
     `<table><tr><th>持仓（${p.positions?.length||0}）</th><th>成本</th></tr>${rows}</table>`);
}
function paperCard(pp){
  return card('paper','IBKR · PAPER','验证沙盒 · 休眠',
     `<div class="muted" style="font-size:12.5px">${pp?.note||'未启用'}</div>`);
}
function card(k,title,sub,body){
  return `<div class="card ${k}"><h2>${title}</h2><div class="sub">${sub}</div>${body}</div>`;}
async function toggleHalt(halted){
  const on=!halted;
  if(on && !confirm('确认 HALT？将停止 auto-trade。'))return;
  await fetch('/api/trading/halt?on='+on+'&reason=cockpit',{method:'POST'});
  load();
}
load(); setInterval(load,30000);
</script></body></html>
"""
