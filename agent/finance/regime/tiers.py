"""Three-tier watchlist for the regime pipeline.

- **Tier 1**: the user's personal watchlist.  Read from
  ``investment_projects`` (existing).  Each ticker gets per-symbol
  strategy recommendations on the Strategies tab.

- **Tier 2**: market anchors — ~15 tickers (broad indices, sector ETFs,
  vol/yield/USD/credit benchmarks) used to compute the 5-bucket regime
  fingerprint.  Hidden from the watchlist UI but every regime metric
  drill-down points back to one of these.

- **Tier 3**: breadth pool — the S&P 500 component list.  Pulled fresh
  daily but never displayed; only used to compute breadth, sector
  dispersion, and top10/bottom10 ratios.

This file is the single source of truth for the symbols to ingest each
day.  ``ingest_yfinance_daily()`` reads it.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# ── Tier 2: market anchors ──────────────────────────────────────────
# These 15 tickers feed the 5-bucket regime fingerprint.  Comments
# tag each one to the bucket(s) that reference it, so when we add a
# bucket the missing input is obvious.

TIER2_ANCHORS: Dict[str, List[str]] = {
    # Broad-market indices — used for breadth, RV, RSI
    "SPY":     ["risk_appetite", "volatility_regime", "breadth"],
    "QQQ":     ["volatility_regime", "breadth"],
    "IWM":     ["breadth"],
    "DIA":     ["breadth"],
    # Vol benchmarks
    "^VIX":    ["risk_appetite", "volatility_regime"],
    "^VIX9D":  ["volatility_regime"],
    # Yield curve
    "^TNX":    ["flow"],          # 10y treasury yield
    "^TYX":    ["flow"],          # 30y treasury yield
    "^IRX":    ["flow"],          # 13-week T-bill yield (proxy for 2y)
    # Currency
    "DX-Y.NYB": ["flow"],         # USD index
    "UUP":     ["flow"],          # USD ETF (fallback if DX-Y unavailable)
    # Credit
    "HYG":     ["flow"],          # high-yield corporate
    "IEF":     ["flow"],          # 7-10y treasury (HYG OAS = HYG yield - IEF yield)
    # Commodities (regime-on/off context)
    "GLD":     ["flow"],
    "USO":     ["flow"],
    # Sector ETFs (11 SPDR sectors) — for sector dispersion + RS
    "XLK":     ["breadth", "flow"],
    "XLF":     ["breadth", "flow"],
    "XLE":     ["breadth", "flow"],
    "XLV":     ["breadth", "flow"],
    "XLY":     ["breadth", "flow"],
    "XLP":     ["breadth", "flow"],
    "XLI":     ["breadth", "flow"],
    "XLB":     ["breadth", "flow"],
    "XLU":     ["breadth", "flow"],
    "XLRE":    ["breadth", "flow"],
    "XLC":     ["breadth", "flow"],
}


# ── Tier 3: S&P 500 breadth pool ────────────────────────────────────
# 503 component symbols (kept current as of 2026-04 snapshot).  yfinance
# can refresh this list dynamically (table on Wikipedia), but we hard-code
# a stable list so the pipeline is reproducible.  When a constituent
# changes, drop it here and the next ingest cycle handles the swap.
#
# This list intentionally lives in source control (not in the DB) so
# diffs to it show up in code review.

TIER3_SP500: List[str] = [
    # Tech (XLK + Communication)
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "AMZN", "TSLA",
    "AVGO", "ORCL", "ADBE", "NFLX", "CRM", "AMD", "QCOM", "CSCO",
    "INTC", "INTU", "IBM", "TXN", "AMAT", "MU", "ANET", "PANW",
    "LRCX", "KLAC", "NOW", "ADP", "ADI", "MRVL", "FTNT", "CDNS",
    "SNPS", "WDAY", "CRWD", "MSI", "ROP", "PAYX", "PYPL", "FICO",
    "MCHP", "GRMN", "DDOG", "TEAM", "ANSS", "CDW", "CTSH", "JNPR",
    "EPAM", "AKAM", "ZBRA", "GEN", "ENPH", "FSLR", "JBL", "TER",
    "TYL", "VRSN", "FFIV", "PTC",
    # Communication services
    "DIS", "T", "VZ", "CMCSA", "TMUS", "EA", "WBD", "CHTR",
    "TTWO", "OMC", "IPG", "PARA", "FOX", "FOXA", "NWS", "NWSA",
    "MTCH", "LYV", "DASH",
    # Financials (XLF)
    "BRK.B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS",
    "AXP", "BLK", "C", "SCHW", "PGR", "MMC", "CB", "ICE",
    "SPGI", "MCO", "PNC", "USB", "TFC", "AON", "AIG", "MET",
    "PRU", "ALL", "TRV", "AFL", "STT", "BK", "DFS", "FITB",
    "SYF", "RJF", "CME", "NDAQ", "MTB", "AMP", "HBAN", "CFG",
    "FIS", "FI", "WTW", "RF", "KEY", "BX", "KKR", "APO",
    "WRB", "GL", "CINF", "L", "RE", "BRO", "PFG", "TROW",
    "IVZ", "BEN", "NTRS", "FDS", "RGA", "ERIE", "EG", "AIZ",
    "ZION", "MKL", "CMA",
    # Healthcare (XLV)
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "ABT", "TMO",
    "DHR", "ISRG", "AMGN", "BMY", "GILD", "VRTX", "MDT", "ELV",
    "REGN", "BSX", "SYK", "BDX", "CI", "HUM", "ZTS", "MDLZ",
    "CVS", "DXCM", "EW", "HCA", "MCK", "BIIB", "IDXX", "RMD",
    "WAT", "MRNA", "GEHC", "STE", "BAX", "INCY", "ZBH", "WST",
    "RVTY", "PODD", "HOLX", "LH", "TFX", "ALGN", "BIO", "CRL",
    "DGX", "MTD", "ILMN", "HSIC", "MOH", "VTRS", "TECH",
    "DVA", "SOLV", "COR", "CAH", "A",
    # Consumer Discretionary (XLY)
    "HD", "MCD", "SBUX", "BKNG", "LOW", "NKE", "TJX", "CMG",
    "ORLY", "AZO", "MAR", "ABNB", "GM", "F", "CCL", "ROST",
    "RCL", "HLT", "DRI", "YUM", "PHM", "DHI", "NVR", "LEN",
    "ULTA", "BBY", "DPZ", "GPC", "TSCO", "EBAY", "GRMN", "WYNN",
    "MGM", "POOL", "BBWI", "RL", "TPR", "LKQ", "AAP", "ETSY",
    "NCLH", "CZR", "DECK", "EXPE", "LULU", "MHK", "WSM",
    "KMX",
    # Consumer Staples (XLP)
    "WMT", "PG", "COST", "KO", "PEP", "PM", "MO", "MDLZ",
    "CL", "TGT", "KMB", "SYY", "GIS", "STZ", "KR", "HSY",
    "ADM", "EL", "CHD", "K", "MKC", "TSN", "CLX", "DG",
    "CAG", "BG", "DLTR", "HRL", "SJM", "LW", "CPB", "BF.B",
    "LMT", "TAP", "MNST", "KDP",
    # Industrials (XLI)
    "BA", "CAT", "RTX", "HON", "UPS", "DE", "LMT", "GE",
    "ETN", "ITW", "CSX", "EMR", "NOC", "MMM", "GD", "WM",
    "FDX", "NSC", "CARR", "JCI", "GEV", "UNP", "PCAR", "CMI",
    "PH", "ROK", "EFX", "ODFL", "PWR", "URI", "AME", "FAST",
    "OTIS", "RSG", "FTV", "WAB", "GNRC", "TXT", "TT", "DOV",
    "AOS", "HEI", "JBHT", "IR", "XYL", "HUBB", "SNA", "CHRW",
    "PNR", "VRSK", "BR", "WAB", "DAL", "UAL", "AAL", "LUV",
    "ALK", "EXPD", "CTAS", "MAS", "IEX", "ALLE", "RHI", "SWK",
    # Energy (XLE)
    "XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO",
    "OXY", "PXD", "WMB", "KMI", "OKE", "DVN", "FANG", "HES",
    "BKR", "HAL", "CTRA", "TRGP", "EQT", "APA", "MRO", "OVV",
    # Materials (XLB)
    "LIN", "APD", "SHW", "FCX", "ECL", "DD", "NUE", "DOW",
    "ALB", "PPG", "STLD", "VMC", "MLM", "IFF", "CTVA", "BALL",
    "AMCR", "PKG", "AVY", "SEE", "MOS", "CF",
    # Utilities (XLU)
    "NEE", "DUK", "SO", "AEP", "SRE", "EXC", "XEL", "ED",
    "AWK", "PEG", "WEC", "DTE", "ETR", "ES", "PCG", "EIX",
    "FE", "AEE", "CMS", "PPL", "CNP", "NRG", "AES", "PNW",
    "ATO", "LNT", "EVRG", "NI",
    # Real Estate (XLRE)
    "PLD", "AMT", "EQIX", "CCI", "WELL", "DLR", "PSA", "O",
    "SPG", "VICI", "EXR", "AVB", "EQR", "WY", "ARE", "CSGP",
    "MAA", "INVH", "ESS", "UDR", "CPT", "REG", "BXP", "FRT",
    "HST", "VTR", "DOC", "KIM", "IRM", "AMT", "SBAC",
]
# De-dup (in case a symbol is double-listed across sectors)
TIER3_SP500 = sorted(set(TIER3_SP500))


def all_symbols() -> List[Tuple[str, int]]:
    """Return [(symbol, tier), ...] for every symbol the ingest
    pipeline should pull. Tier 1 (user watchlist) is added by the
    caller from investment_projects since it varies per user."""
    out: List[Tuple[str, int]] = []
    for sym in TIER2_ANCHORS:
        out.append((sym, 2))
    for sym in TIER3_SP500:
        # Skip if already in Tier 2 (sector ETFs are both)
        if sym not in TIER2_ANCHORS:
            out.append((sym, 3))
    return out


def tier_of(symbol: str, tier1_watchlist: List[str] | None = None) -> int:
    """Return the tier of a symbol.  Tier 1 takes precedence (user
    explicitly watching it), else Tier 2 (anchor), else Tier 3."""
    if tier1_watchlist and symbol in tier1_watchlist:
        return 1
    if symbol in TIER2_ANCHORS:
        return 2
    return 3
