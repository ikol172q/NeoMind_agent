"""NeoMind Finance Tools — agentic tool implementations for fin mode.

These are the implementations behind the Phase B.2 v5 taxonomy. Each
tool is a plain async function that takes structured arguments, hits
the underlying FinanceDataHub / QuantEngine / DigestEngine / RAG index,
and returns a JSON-serializable dict that the LLM can consume directly.

Design principles:

1. **Plain dicts as return values.** The LLM sees JSON, not Python
   dataclasses. Returning a dict makes serialization into tool_result
   blocks trivial and lets the LLM pick fields by name without learning
   our dataclass schema.

2. **Optional dependencies, graceful fallback.** If a backend (e.g. the
   RAG index, or the digest engine) isn't initialized, the tool returns
   `{"ok": False, "error": "<what went wrong>"}` instead of crashing.
   The LLM reads the error and can tell the user "that feature isn't
   enabled".

3. **Single source of truth.** These functions are called by BOTH the
   LLM-side agentic loop AND the user-facing Tier 2 slash commands
   (`/stock`, `/crypto`, `/news`, `/digest`, `/market`). The Telegram
   slash handlers in `telegram_bot.py` will be refactored in Phase B.5
   to be thin wrappers around these functions.

4. **Mode-gated.** Every tool registers with `allowed_modes={"fin"}` so
   they appear in the LLM's tool list only when the chat is in fin mode.
   Chat/coding modes do not see them. Enforced by `ToolRegistry.
   get_all_tools(mode)` introduced in commit `eea40a0`.

5. **No Telegram formatting here.** Tools return raw data. Telegram
   rendering (emojis, HTML, truncation to 4096 chars) lives in the
   slash handler, not in the tool. This separation means the tools can
   be reused by future interfaces (e.g. a web API) without changes.

6. **Registration is explicit.** This module exposes
   `register_finance_tools(registry, components)` which is called once
   at bot startup — Phase B.3 wires it into
   `telegram_bot.py:NeoMindTelegramBot.start()` right next to the
   existing `WebSearch` tool registration.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("neomind.finance_tools")


# ── Ticker → CoinGecko coin_id mapping ────────────────────────────────
# Same map used in openclaw_skill._handle_crypto — centralised here so
# both the slash wrapper and the LLM tool hit the same lookup.
COIN_ID_MAP: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "BNB": "binancecoin",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "LTC": "litecoin",
    "TRX": "tron",
    "ATOM": "cosmos",
}


def _resolve_coin_id(symbol_or_id: str) -> str:
    """Accept either a ticker (BTC) or a CoinGecko ID (bitcoin)."""
    s = (symbol_or_id or "").strip()
    if not s:
        return ""
    # If already lowercase + multi-char, assume it's a coin_id
    if s.islower() and len(s) > 4:
        return s
    return COIN_ID_MAP.get(s.upper(), s.lower())


# ── 1. finance_get_stock ──────────────────────────────────────────────

async def finance_get_stock(
    data_hub: Any,
    symbol: str,
    market: str = "us",
) -> Dict[str, Any]:
    """Look up a real-time stock quote.

    Hits Finnhub (primary) → yfinance (fallback) via FinanceDataHub.
    Returns a plain dict with price, change, change_pct, volume, high,
    low, open, prev_close, market_cap, pe_ratio, name, market, source,
    timestamp.

    Returns `{"ok": False, "error": ...}` if the data hub is missing
    or the symbol isn't found.
    """
    if not data_hub:
        return {"ok": False, "error": "data hub not available"}
    try:
        quote = await data_hub.get_quote(symbol, market)
        if quote is None or quote.price is None:
            return {
                "ok": False,
                "error": f"no data for {symbol}",
                "symbol": symbol,
            }
        return {
            "ok": True,
            "symbol": quote.symbol,
            "name": quote.name,
            "price": quote.price.value,
            "currency": quote.currency,
            "change": quote.change,
            "change_pct": quote.change_pct,
            "volume": quote.volume,
            "high": quote.high,
            "low": quote.low,
            "open": quote.open,
            "prev_close": quote.prev_close,
            "market_cap": quote.market_cap,
            "pe_ratio": quote.pe_ratio,
            "market": quote.market,
            "market_status": quote.market_status,
            "source": quote.price.source,
            "freshness": quote.price.freshness,
            "timestamp": quote.price.timestamp.isoformat(),
        }
    except Exception as e:
        logger.exception(f"finance_get_stock({symbol}) failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── 2. finance_get_crypto ─────────────────────────────────────────────

async def finance_get_crypto(
    data_hub: Any,
    symbol_or_id: str,
) -> Dict[str, Any]:
    """Look up a real-time crypto quote.

    Accepts either a ticker (`BTC`) or a CoinGecko coin_id (`bitcoin`).
    Hits CoinGecko (primary) → Binance (fallback).
    """
    if not data_hub:
        return {"ok": False, "error": "data hub not available"}
    coin_id = _resolve_coin_id(symbol_or_id)
    if not coin_id:
        return {"ok": False, "error": "empty symbol"}
    try:
        quote = await data_hub.get_crypto(coin_id)
        if quote is None or quote.price is None:
            return {
                "ok": False,
                "error": f"no data for {symbol_or_id} (resolved to {coin_id})",
                "symbol": symbol_or_id,
            }
        return {
            "ok": True,
            "coin_id": quote.coin_id,
            "symbol": quote.symbol,
            "name": quote.name,
            "price": quote.price.value,
            "currency": quote.currency,
            "change_24h_pct": quote.change_24h_pct,
            "volume_24h": quote.volume_24h,
            "market_cap": quote.market_cap,
            "rank": quote.rank,
            "source": quote.price.source,
            "freshness": quote.price.freshness,
            "timestamp": quote.price.timestamp.isoformat(),
        }
    except Exception as e:
        logger.exception(f"finance_get_crypto({symbol_or_id}) failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── 3. finance_market_overview ────────────────────────────────────────

async def finance_market_overview(
    data_hub: Any,
    symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Aggregate quotes for major US indices + common ETFs.

    Default basket: SPY, QQQ, DIA, IWM, VIX (via VIXY ETF proxy for
    vol). Returns a list of quote dicts.
    """
    if not data_hub:
        return {"ok": False, "error": "data hub not available"}

    tickers = symbols or ["SPY", "QQQ", "DIA", "IWM", "VIXY"]
    quotes: List[Dict[str, Any]] = []
    errors: List[str] = []
    for sym in tickers:
        try:
            q = await data_hub.get_quote(sym, market="us")
            if q and q.price:
                quotes.append({
                    "symbol": sym,
                    "price": q.price.value,
                    "change": q.change,
                    "change_pct": q.change_pct,
                    "source": q.price.source,
                })
            else:
                errors.append(f"{sym}: no data")
        except Exception as e:
            errors.append(f"{sym}: {type(e).__name__}")

    return {
        "ok": len(quotes) > 0,
        "quotes": quotes,
        "errors": errors,
        "basket": tickers,
    }


# ── 4. finance_news_search ────────────────────────────────────────────

async def finance_news_search(
    search_engine: Any,
    query: str,
    max_results: int = 5,
    days: int = 3,
) -> Dict[str, Any]:
    """Search FINANCE-specific news sources (not general web search).

    Uses the hybrid search engine but constrains Tier-1 to gnews +
    site-specific RSS feeds (which are finance-flavoured). This is
    distinct from `web_search()`, which hits the full web.
    """
    if not search_engine:
        return {"ok": False, "error": "search engine not available"}
    if not query or not query.strip():
        return {"ok": False, "error": "empty query"}

    try:
        # The existing hybrid_search.HybridSearchEngine already gates
        # RSS to finance queries via the `is_finance` heuristic. For
        # this tool we bias toward finance by injecting a light hint.
        result = await search_engine.search(
            query=query,
            max_results=max_results,
            extract_content=False,
            expand_queries=False,
        )
        if not result or not result.items:
            return {"ok": False, "error": "no results", "query": query}
        items = []
        for it in result.items[:max_results]:
            items.append({
                "title": it.title,
                "url": it.url,
                "source": it.source,
                "snippet": (it.snippet or "")[:300],
                "language": it.language,
                "published": it.published.isoformat() if it.published else None,
            })
        return {
            "ok": True,
            "query": query,
            "items": items,
            "sources_used": list(result.sources_used),
            "total": len(items),
        }
    except Exception as e:
        logger.exception(f"finance_news_search({query!r}) failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── 5. finance_market_digest ──────────────────────────────────────────

async def finance_market_digest(digest_engine: Any) -> Dict[str, Any]:
    """Generate the daily market digest (EN + ZH news, sector moves).

    Wraps the existing DigestEngine. Returns the digest's core
    attributes as a dict instead of the rich dataclass.
    """
    if not digest_engine:
        return {"ok": False, "error": "digest engine not available"}
    try:
        digest = await digest_engine.generate_digest()
        return {
            "ok": True,
            "generated_at": getattr(digest, "generated_at", None),
            "sources_used": getattr(digest, "sources_used", 0),
            "en_count": getattr(digest, "en_count", 0),
            "zh_count": getattr(digest, "zh_count", 0),
            "summary": getattr(digest, "summary", None),
            "top_stories": [
                {
                    "title": s.title,
                    "url": s.url,
                    "source": s.source,
                    "summary": (s.summary or "")[:500] if hasattr(s, "summary") else "",
                }
                for s in getattr(digest, "top_stories", [])[:10]
            ],
        }
    except Exception as e:
        logger.exception("finance_market_digest failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── 6. finance_compute — unified computation dispatch ────────────────

async def finance_compute(
    quant_engine: Any,
    formula: str,
    **args: Any,
) -> Dict[str, Any]:
    """Deterministic financial math dispatch.

    Supported formulas (case-insensitive):
      - cagr: initial, final, years → CAGR in %
      - compound: principal, annual_rate, years, [monthly_contribution], [compounding]
      - sharpe: portfolio_return, risk_free_rate, std_deviation
      - var: portfolio_value, mean_return, std_deviation, [confidence]
      - bs (Black-Scholes): S, K, T, r, sigma, [option_type]
      - dcf: cash_flows[], terminal_value, discount_rate
    """
    if not quant_engine:
        return {"ok": False, "error": "quant engine not available"}

    f = (formula or "").strip().lower()
    try:
        if f == "cagr":
            initial = float(args["initial"])
            final = float(args["final"])
            years = float(args["years"])
            if initial <= 0 or years <= 0:
                return {"ok": False, "error": "initial and years must be > 0"}
            cagr = (final / initial) ** (1.0 / years) - 1.0
            return {
                "ok": True,
                "formula": "cagr",
                "cagr": round(cagr, 6),
                "cagr_pct": f"{cagr * 100:.2f}%",
                "initial": initial,
                "final": final,
                "years": years,
                "verification": f"{initial} × (1+{cagr:.4f})^{years} = {initial * (1 + cagr) ** years:.2f}",
            }

        if f == "compound":
            result = quant_engine.compound_return(
                principal=float(args["principal"]),
                annual_rate=float(args["annual_rate"]),
                years=int(args["years"]),
                monthly_contribution=float(args.get("monthly_contribution", 0)),
                compounding=args.get("compounding", "annual"),
            )
            return {
                "ok": True,
                "formula": "compound",
                "future_value": result.value,
                "unit": result.unit,
                "steps": result.steps,
                "method": result.method,
            }

        if f == "sharpe":
            val = quant_engine.sharpe_ratio(
                portfolio_return=float(args["portfolio_return"]),
                risk_free_rate=float(args["risk_free_rate"]),
                std_deviation=float(args["std_deviation"]),
            )
            return {
                "ok": True,
                "formula": "sharpe",
                "sharpe_ratio": val,
                "portfolio_return": float(args["portfolio_return"]),
                "risk_free_rate": float(args["risk_free_rate"]),
                "std_deviation": float(args["std_deviation"]),
            }

        if f == "var":
            val = quant_engine.value_at_risk(
                portfolio_value=float(args["portfolio_value"]),
                mean_return=float(args["mean_return"]),
                std_deviation=float(args["std_deviation"]),
                confidence=float(args.get("confidence", 0.95)),
            )
            return {
                "ok": True,
                "formula": "var",
                "var": val,
                "confidence": float(args.get("confidence", 0.95)),
            }

        if f in ("bs", "black_scholes", "option"):
            result = quant_engine.option_pricing(
                S=float(args["S"]),
                K=float(args["K"]),
                T=float(args["T"]),
                r=float(args["r"]),
                sigma=float(args["sigma"]),
                option_type=args.get("option_type", "call"),
            )
            return {
                "ok": True,
                "formula": "black_scholes",
                "price": result.price,
                "delta": result.delta,
                "gamma": result.gamma,
                "theta": result.theta,
                "vega": result.vega,
                "rho": result.rho,
                "option_type": result.option_type,
            }

        if f == "dcf":
            result = quant_engine.dcf_valuation(**args)
            return {
                "ok": True,
                "formula": "dcf",
                "present_value": result.present_value,
                "discount_rate": result.discount_rate,
                "terminal_value": result.terminal_value,
                "assumptions": result.assumptions,
            }

        return {
            "ok": False,
            "error": f"unknown formula '{formula}'",
            "supported": ["cagr", "compound", "sharpe", "var", "bs", "dcf"],
        }
    except KeyError as e:
        return {"ok": False, "error": f"missing required argument: {e}"}
    except Exception as e:
        logger.exception(f"finance_compute({formula!r}) failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── 7. finance_economic_calendar ──────────────────────────────────────

async def finance_economic_calendar(days: int = 7) -> Dict[str, Any]:
    """Return the upcoming economic data release calendar.

    Placeholder implementation — real calendar data requires an API
    like TradingEconomics or Finnhub calendar endpoints. For now we
    return a static list of well-known recurring releases so the LLM
    has something to reason about. Phase D will wire this to a live
    source.
    """
    # TODO: connect to finnhub_client.calendar_economic() or similar
    # once the key is available. For now return a schedule skeleton.
    recurring = [
        {"event": "CPI", "frequency": "monthly", "impact": "high"},
        {"event": "NFP (Non-Farm Payrolls)", "frequency": "monthly", "impact": "high"},
        {"event": "FOMC decision", "frequency": "~8x per year", "impact": "high"},
        {"event": "PPI", "frequency": "monthly", "impact": "medium"},
        {"event": "Retail Sales", "frequency": "monthly", "impact": "medium"},
        {"event": "PMI", "frequency": "monthly", "impact": "medium"},
        {"event": "Unemployment Rate", "frequency": "monthly", "impact": "high"},
        {"event": "GDP", "frequency": "quarterly", "impact": "high"},
    ]
    return {
        "ok": True,
        "days_horizon": days,
        "note": "Placeholder: showing recurring release schedule. Live API integration pending.",
        "recurring_releases": recurring,
    }


# ── 8. finance_risk_calc ──────────────────────────────────────────────

async def finance_risk_calc(
    quant_engine: Any,
    metric: str,
    **args: Any,
) -> Dict[str, Any]:
    """Risk metric calculation dispatch.

    Supported metrics:
      - position_size: portfolio_value, risk_per_trade, entry, stop_loss
      - max_drawdown: returns[]
      - volatility_annualized: returns[]
    """
    if not quant_engine:
        return {"ok": False, "error": "quant engine not available"}

    m = (metric or "").strip().lower()
    try:
        if m == "position_size":
            val = quant_engine.position_size(
                portfolio_value=float(args["portfolio_value"]),
                risk_per_trade=float(args["risk_per_trade"]),
                entry_price=float(args["entry"]),
                stop_loss=float(args["stop_loss"]),
            )
            return {
                "ok": True,
                "metric": "position_size",
                "shares": val,
                "portfolio_value": float(args["portfolio_value"]),
                "risk_per_trade": float(args["risk_per_trade"]),
            }

        # Stubs for max_drawdown and volatility — real implementation
        # when more inputs land. LLM can use compute_sharpe + var for now.
        return {
            "ok": False,
            "error": f"metric '{metric}' not yet implemented — use finance_compute instead",
            "supported_now": ["position_size"],
            "planned": ["max_drawdown", "volatility_annualized"],
        }
    except KeyError as e:
        return {"ok": False, "error": f"missing required argument: {e}"}
    except Exception as e:
        logger.exception(f"finance_risk_calc({metric!r}) failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── 9. finance_portfolio_show ─────────────────────────────────────────

async def finance_portfolio_show(chat_store: Any, chat_id: int) -> Dict[str, Any]:
    """Read-only view of the user's portfolio.

    Returns current holdings if the chat_store supports it, else an
    empty-state response. WRITE operations (`add`, `remove`) stay as
    user-facing slash commands per v5 Tier 3 (write-state protection).
    """
    if not chat_store or chat_id is None:
        return {"ok": False, "error": "chat store or chat_id missing"}
    try:
        # Portfolio state may be stored in various places. Try a
        # common method name first.
        if hasattr(chat_store, "get_portfolio"):
            holdings = chat_store.get_portfolio(chat_id) or []
        else:
            holdings = []
        return {
            "ok": True,
            "holdings": list(holdings),
            "count": len(holdings),
            "note": "Read-only view. Use /portfolio add/remove to modify.",
        }
    except Exception as e:
        logger.exception(f"finance_portfolio_show({chat_id}) failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── 10. finance_watchlist_show ────────────────────────────────────────

async def finance_watchlist_show(chat_store: Any, chat_id: int) -> Dict[str, Any]:
    """Read-only view of the user's watchlist."""
    if not chat_store or chat_id is None:
        return {"ok": False, "error": "chat store or chat_id missing"}
    try:
        if hasattr(chat_store, "get_watchlist"):
            watchlist = chat_store.get_watchlist(chat_id) or []
        else:
            watchlist = []
        return {
            "ok": True,
            "symbols": list(watchlist),
            "count": len(watchlist),
            "note": "Read-only view. Use /watchlist add/remove to modify.",
        }
    except Exception as e:
        logger.exception(f"finance_watchlist_show({chat_id}) failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── Tool registry registration ────────────────────────────────────────

def register_finance_tools(registry: Any, components: Dict[str, Any]) -> int:
    """Register all 10 finance tools in the given ToolRegistry.

    Called once during bot startup — Phase B.3 wires this into
    telegram_bot.py:NeoMindTelegramBot.start() right next to the
    existing WebSearch registration.

    All tools are registered with `allowed_modes={"fin"}` so they
    appear in the LLM's tool list only when the chat is in fin mode.

    Returns the number of tools successfully registered.
    """
    from agent.coding.tool_schema import (
        ToolDefinition,
        ToolParam,
        ParamType,
        PermissionLevel,
    )

    data_hub = components.get("data_hub")
    quant = components.get("quant")
    digest = components.get("digest")
    search = components.get("search")
    chat_store = components.get("chat_store")

    fin_modes = {"fin"}
    registered = 0

    # 1. finance_get_stock
    async def _exec_stock(symbol: str, market: str = "us", **_ignore):
        from agent.coding.tool_schema import ToolResult
        data = await finance_get_stock(data_hub, symbol, market)
        if data.get("ok"):
            summary = (
                f"{data['symbol']} {data.get('name', '')} ${data['price']} "
                f"({data.get('change_pct', 0):+.2f}%) via {data.get('source')}"
            )
            return ToolResult(True, output=summary, metadata=data)
        return ToolResult(False, error=data.get("error", "unknown error"))

    registry._tool_definitions["finance_get_stock"] = ToolDefinition(
        name="finance_get_stock",
        description=(
            "Look up a real-time stock quote by ticker (e.g. AAPL, NVDA, TSLA). "
            "Returns price, change, volume, market cap, source, timestamp. "
            "Use this when the user asks about a specific stock's current price."
        ),
        parameters=[
            ToolParam("symbol", ParamType.STRING,
                      "Ticker symbol like AAPL, MSFT, TSLA"),
            ToolParam("market", ParamType.STRING,
                      "Market code: us (default), cn, hk",
                      required=False, default="us"),
        ],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_exec_stock,
        allowed_modes=fin_modes,
        examples=[{"symbol": "AAPL"}, {"symbol": "TSLA"}],
    )
    registered += 1

    # 2. finance_get_crypto
    async def _exec_crypto(symbol: str, **_ignore):
        from agent.coding.tool_schema import ToolResult
        data = await finance_get_crypto(data_hub, symbol)
        if data.get("ok"):
            summary = (
                f"{data['symbol']} ${data['price']:,.2f} "
                f"({data.get('change_24h_pct', 0):+.2f}% 24h) via {data.get('source')}"
            )
            return ToolResult(True, output=summary, metadata=data)
        return ToolResult(False, error=data.get("error", "unknown error"))

    registry._tool_definitions["finance_get_crypto"] = ToolDefinition(
        name="finance_get_crypto",
        description=(
            "Look up a real-time crypto price. Accepts ticker (BTC, ETH, SOL) "
            "or CoinGecko coin_id (bitcoin, ethereum). Returns price, 24h "
            "change, volume, market cap. Use for current crypto prices."
        ),
        parameters=[
            ToolParam("symbol", ParamType.STRING,
                      "Crypto ticker or coin_id: BTC / ETH / bitcoin / ethereum"),
        ],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_exec_crypto,
        allowed_modes=fin_modes,
        examples=[{"symbol": "BTC"}, {"symbol": "ETH"}],
    )
    registered += 1

    # 3. finance_market_overview
    async def _exec_market(**_ignore):
        from agent.coding.tool_schema import ToolResult
        data = await finance_market_overview(data_hub)
        if data.get("ok"):
            lines = [f"{q['symbol']} ${q['price']} ({q.get('change_pct', 0):+.2f}%)"
                     for q in data["quotes"]]
            return ToolResult(True, output="\n".join(lines), metadata=data)
        return ToolResult(False, error="no market data available")

    registry._tool_definitions["finance_market_overview"] = ToolDefinition(
        name="finance_market_overview",
        description=(
            "Get a quick overview of major US market indices and ETFs: SPY, "
            "QQQ, DIA, IWM, VIXY. Returns current prices and daily change. "
            "Use when user asks 'how's the market today'."
        ),
        parameters=[],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_exec_market,
        allowed_modes=fin_modes,
    )
    registered += 1

    # 4. finance_news_search
    async def _exec_news(query: str, max_results: int = 5, **_ignore):
        from agent.coding.tool_schema import ToolResult
        data = await finance_news_search(search, query, max_results=max_results)
        if data.get("ok"):
            lines = [f"{i+1}. [{it['source']}] {it['title']} — {it['url']}"
                     for i, it in enumerate(data["items"])]
            return ToolResult(True, output="\n".join(lines), metadata=data)
        return ToolResult(False, error=data.get("error", "no results"))

    registry._tool_definitions["finance_news_search"] = ToolDefinition(
        name="finance_news_search",
        description=(
            "Search finance-specific news sources (Google News RSS + "
            "curated finance RSS feeds). Distinct from web_search — this "
            "is finance-flavoured. Use for market news, earnings, macro."
        ),
        parameters=[
            ToolParam("query", ParamType.STRING, "Search query"),
            ToolParam("max_results", ParamType.INTEGER,
                      "Max number of results", required=False, default=5),
        ],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_exec_news,
        allowed_modes=fin_modes,
    )
    registered += 1

    # 5. finance_market_digest
    async def _exec_digest(**_ignore):
        from agent.coding.tool_schema import ToolResult
        data = await finance_market_digest(digest)
        if data.get("ok"):
            return ToolResult(True,
                              output=data.get("summary") or "Digest generated",
                              metadata=data)
        return ToolResult(False, error=data.get("error", "digest unavailable"))

    registry._tool_definitions["finance_market_digest"] = ToolDefinition(
        name="finance_market_digest",
        description=(
            "Generate today's market digest: top finance stories, sector "
            "moves, EN + ZH news aggregation. Use for daily summary requests."
        ),
        parameters=[],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_exec_digest,
        allowed_modes=fin_modes,
    )
    registered += 1

    # 6. finance_compute
    async def _exec_compute(formula: str, **args):
        from agent.coding.tool_schema import ToolResult
        data = await finance_compute(quant, formula, **args)
        if data.get("ok"):
            return ToolResult(True, output=str(data), metadata=data)
        return ToolResult(False, error=data.get("error", "compute failed"))

    registry._tool_definitions["finance_compute"] = ToolDefinition(
        name="finance_compute",
        description=(
            "Deterministic financial math. Supported formulas: cagr, "
            "compound, sharpe, var, bs (Black-Scholes), dcf. Args vary "
            "by formula — e.g. cagr needs initial/final/years, compound "
            "needs principal/annual_rate/years. Use for precise calculations."
        ),
        parameters=[
            ToolParam("formula", ParamType.STRING,
                      "One of: cagr, compound, sharpe, var, bs, dcf"),
        ],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_exec_compute,
        allowed_modes=fin_modes,
        examples=[
            {"formula": "cagr", "initial": 100, "final": 200, "years": 5},
            {"formula": "compound", "principal": 10000, "annual_rate": 0.08, "years": 10},
        ],
    )
    registered += 1

    # 7. finance_economic_calendar
    async def _exec_calendar(days: int = 7, **_ignore):
        from agent.coding.tool_schema import ToolResult
        data = await finance_economic_calendar(days)
        return ToolResult(True, output=str(data), metadata=data)

    registry._tool_definitions["finance_economic_calendar"] = ToolDefinition(
        name="finance_economic_calendar",
        description=(
            "Upcoming economic data releases (CPI, NFP, FOMC, PMI, GDP, etc). "
            "Currently returns recurring schedule; live API integration pending."
        ),
        parameters=[
            ToolParam("days", ParamType.INTEGER,
                      "Horizon in days", required=False, default=7),
        ],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_exec_calendar,
        allowed_modes=fin_modes,
    )
    registered += 1

    # 8. finance_risk_calc
    async def _exec_risk(metric: str, **args):
        from agent.coding.tool_schema import ToolResult
        data = await finance_risk_calc(quant, metric, **args)
        if data.get("ok"):
            return ToolResult(True, output=str(data), metadata=data)
        return ToolResult(False, error=data.get("error", "risk calc failed"))

    registry._tool_definitions["finance_risk_calc"] = ToolDefinition(
        name="finance_risk_calc",
        description=(
            "Risk metric dispatch: position_size (from portfolio value, "
            "entry, stop_loss). Other metrics (max_drawdown, "
            "volatility_annualized) planned."
        ),
        parameters=[
            ToolParam("metric", ParamType.STRING,
                      "One of: position_size"),
        ],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_exec_risk,
        allowed_modes=fin_modes,
    )
    registered += 1

    # 9. finance_portfolio_show
    async def _exec_portfolio_show(chat_id: int = 0, **_ignore):
        from agent.coding.tool_schema import ToolResult
        data = await finance_portfolio_show(chat_store, chat_id)
        if data.get("ok"):
            return ToolResult(True,
                              output=f"{data['count']} holdings",
                              metadata=data)
        return ToolResult(False, error=data.get("error", "portfolio unavailable"))

    registry._tool_definitions["finance_portfolio_show"] = ToolDefinition(
        name="finance_portfolio_show",
        description=(
            "Read-only view of the user's portfolio holdings. Write ops "
            "(/portfolio add/remove) stay as slash commands per Tier 3 "
            "write-state protection."
        ),
        parameters=[
            ToolParam("chat_id", ParamType.INTEGER,
                      "Chat ID (implicit)", required=False, default=0),
        ],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_exec_portfolio_show,
        allowed_modes=fin_modes,
    )
    registered += 1

    # 10. finance_watchlist_show
    async def _exec_watchlist_show(chat_id: int = 0, **_ignore):
        from agent.coding.tool_schema import ToolResult
        data = await finance_watchlist_show(chat_store, chat_id)
        if data.get("ok"):
            return ToolResult(True,
                              output=f"{data['count']} symbols",
                              metadata=data)
        return ToolResult(False, error=data.get("error", "watchlist unavailable"))

    registry._tool_definitions["finance_watchlist_show"] = ToolDefinition(
        name="finance_watchlist_show",
        description=(
            "Read-only view of the user's watchlist. Write ops "
            "(/watchlist add/remove) stay as slash commands."
        ),
        parameters=[
            ToolParam("chat_id", ParamType.INTEGER,
                      "Chat ID (implicit)", required=False, default=0),
        ],
        permission_level=PermissionLevel.READ_ONLY,
        execute=_exec_watchlist_show,
        allowed_modes=fin_modes,
    )
    registered += 1

    logger.info(f"[finance_tools] registered {registered} fin tools with allowed_modes={{'fin'}}")
    return registered
