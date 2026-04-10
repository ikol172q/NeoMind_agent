"""FinancePersonality — money-making mode with strongest financial analysis.

Personality core: 赚钱 (making money)
Strongest capability: financial analysis, news aggregation, quantitative reasoning,
    portfolio tracking, market intelligence.

Design principle: Finance is LASER-FOCUSED on making money.
  Every command, every response, every enhancement is oriented toward
  actionable financial intelligence. Built-in compliance checking ensures
  no unsubstantiated claims slip through.

Created: 2026-03-28 (Step 6 of architecture redesign)
Updated: 2026-03-28 (P4 — slash commands + stronger differentiation)
"""

from typing import Dict, Optional, Set

from agent.base_personality import BasePersonality
from agent.services.shared_commands import SharedCommandsMixin
from agent_config import agent_config


class FinancePersonality(BasePersonality, SharedCommandsMixin):
    """Finance mode — money-making financial intelligence.

    Unique capabilities vs other modes:
      /stock     — real-time stock analysis (price, fundamentals, news)
      /portfolio — view & analyze portfolio holdings
      /market    — market overview (indices, sectors, sentiment)
      /news      — finance-focused news digest with impact analysis
      /watchlist — manage & check a stock watchlist
      /quant     — quantitative computation (ROI, CAGR, DCF, etc.)

    Also has:
      - FinanceResponseValidator on every output (auto-disclaimers)
      - NL pattern matching for stock/market/portfolio queries
      - Finance subsystem initialization (QuantEngine, DataHub, etc.)
    """

    def __init__(self, core, services):
        super().__init__(core, services)
        self._finance_components = None
        self._finance_validator = None

    @property
    def name(self) -> str:
        return "fin"

    @property
    def display_name(self) -> str:
        return "Finance 赚钱"

    def get_command_handlers(self) -> Dict[str, tuple]:
        """Finance-UNIQUE commands — money-making toolkit."""
        return {
            "/stock": (self._fin_handle_stock_command, True),
            "/portfolio": (self._fin_handle_portfolio_command, True),
            "/market": (self._fin_handle_market_command, True),
            "/news": (self._fin_handle_news_command, True),
            "/watchlist": (self._fin_handle_watchlist_command, True),
            "/quant": (self._fin_handle_quant_command, True),
        }

    def on_activate(self) -> None:
        """Activate finance mode — load finance components, set search domain."""
        # Set search domain for financial results
        if hasattr(self.core, 'searcher') and hasattr(self.core.searcher, 'set_domain'):
            self.core.searcher.set_domain("finance")

        # Initialize finance-specific subsystems
        self._initialize_finance()

        # Re-inject vault context for finance mode
        self._inject_vault_context()

        # Re-inject shared memory context
        self._inject_memory_context()

        # Deactivate incompatible skills
        self._check_skill_compatibility()

    def on_deactivate(self) -> None:
        """Deactivate finance mode."""
        pass

    def get_search_domain(self) -> str:
        return "finance"

    def get_system_prompt(self) -> str:
        return agent_config.system_prompt or ""

    def enhance_response(self, response: str, tool_results: Optional[list] = None) -> str:
        """Run FinanceResponseValidator on every output.

        Catches missing disclaimers, unsubstantiated claims,
        and appends appropriate financial advice caveats.
        """
        if not self._finance_validator or not response:
            return response

        try:
            vr = self._finance_validator.validate(response, tool_results or [])
            if not vr.passed:
                disclaimer = self._finance_validator.build_disclaimer(vr)
                if disclaimer:
                    response += disclaimer
                # Log warning via core's evidence trail
                try:
                    self.core._log_evidence(
                        "finance_validation_warning",
                        vr.summary()[:200],
                        response[:200],
                        severity="warning",
                    )
                except Exception:
                    pass
        except Exception:
            pass  # Non-fatal: don't break user flow

        return response

    def get_nl_patterns(self) -> Optional[dict]:
        """Finance-specific natural language patterns.

        Returns patterns for stock analysis triggers,
        portfolio commands, market data queries, etc.
        """
        return {
            "stock_query": [
                r"(?:what|how).*(?:stock|share|price|ticker)\s+(\w+)",
                r"(?:analyze|check)\s+(?:stock|ticker)\s+(\w+)",
                r"\$([A-Z]{1,5})\b",  # $AAPL, $TSLA etc.
            ],
            "market_summary": [
                r"(?:market|market\s*cap|index)\s+(?:summary|overview|today)",
                r"how.*market.*(?:doing|performing|today)",
                r"(?:S&P|nasdaq|dow|hang seng|恒指|上证|沪深)\s*(?:today|now)?",
            ],
            "portfolio": [
                r"(?:my|the)\s+portfolio",
                r"(?:show|check|analyze)\s+(?:portfolio|holdings|positions)",
            ],
            "news_finance": [
                r"(?:financial|market|stock|earnings)\s+news",
                r"(?:what happened|any news).*(?:market|stock|finance)",
            ],
        }

    def get_commands_feed_to_llm(self) -> Set[str]:
        """Finance feeds money-related commands to LLM for follow-up."""
        base = super().get_commands_feed_to_llm()
        return base | {"/stock", "/portfolio", "/market", "/news", "/quant"}

    # ── Activation helpers ──────────────────────────────────────────

    def _initialize_finance(self):
        """Load finance-only components (validator, etc.)."""
        if self._finance_validator is not None:
            return  # Already initialized

        try:
            from agent.finance import get_finance_only_components
            self._finance_components = get_finance_only_components()
            self._finance_validator = self._finance_components.get('validator')
        except Exception:
            self._finance_components = {}
            self._finance_validator = None

        # Also init full finance subsystems on core (for NL routing)
        try:
            from agent.finance import get_finance_components
            from agent_config import agent_config as cfg
            if not getattr(self.core, '_finance_components', None):
                self.core._finance_components = get_finance_components(cfg)
        except Exception:
            pass

    def _get_finance_component(self, name: str):
        """Safely get a finance component by name."""
        if self._finance_components:
            return self._finance_components.get(name)
        # Fallback: try core's finance components
        core_fc = getattr(self.core, '_finance_components', None)
        if core_fc:
            return core_fc.get(name)
        return None

    def _inject_vault_context(self):
        """Re-inject vault context for this mode."""
        vault_reader = getattr(self.core, '_vault_reader', None)
        if vault_reader and vault_reader.vault_exists():
            try:
                vault_context = vault_reader.get_startup_context(mode=self.name)
                if vault_context:
                    self.core.add_to_history("system", vault_context)
            except Exception:
                pass

    def _inject_memory_context(self):
        """Re-inject shared memory context for this mode."""
        memory = getattr(self.core, '_shared_memory', None)
        if memory:
            try:
                mem_context = memory.get_context_summary(mode=self.name, max_tokens=500)
                if mem_context:
                    self.core.add_to_history("system",
                        f"# User Context (from cross-personality memory)\n\n{mem_context}")
            except Exception:
                pass

    def _check_skill_compatibility(self):
        """Deactivate skills not available in this mode."""
        active_skill = getattr(self.core, '_active_skill', None)
        if active_skill and self.name not in active_skill.modes:
            self.core._safe_print(
                f"🔴 Deactivated skill '{active_skill.name}' (not available in {self.name} mode)")
            self.core._active_skill = None

    # ── Finance-unique command handlers ──────────────────────────────

    def _fin_handle_stock_command(self, arg):
        """Analyze a stock — price, fundamentals, recent news.

        Usage: /stock <ticker> [brief|full]
        """
        if not arg or not arg.strip():
            return "Usage: /stock <ticker> [brief|full]\nExample: /stock AAPL full"

        parts = arg.strip().split()
        ticker = parts[0].upper().lstrip("$")
        detail = parts[1].lower() if len(parts) > 1 else "brief"

        # Try DataHub for real data (async → run in event loop)
        data_hub = self._get_finance_component('data_hub')
        if data_hub:
            try:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Already in async context — can't await directly
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            quote = pool.submit(
                                asyncio.run, data_hub.get_quote(ticker)
                            ).result(timeout=10)
                    else:
                        quote = loop.run_until_complete(data_hub.get_quote(ticker))
                except RuntimeError:
                    quote = asyncio.run(data_hub.get_quote(ticker))
                if quote:
                    return self._format_stock_data(ticker, quote, detail)
            except Exception:
                pass

        # Fallback: LLM-based analysis
        prompt = (
            f"Provide a {'comprehensive' if detail == 'full' else 'brief'} "
            f"analysis of stock ticker {ticker}:\n"
            f"- Current situation and recent performance\n"
            f"- Key metrics (P/E, market cap, revenue trend)\n"
            f"- Recent news and catalysts\n"
            f"- Risk factors\n"
            f"{'- Technical analysis and price targets' if detail == 'full' else ''}\n"
            f"Note: Data may not be real-time. Always verify with your broker."
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.3, max_tokens=2000)
            return f"📈 Stock Analysis: ${ticker}\n\n{response}"
        except Exception as e:
            return f"❌ Stock analysis failed: {e}"

    def _format_stock_data(self, ticker, quote, detail):
        """Format real StockQuote data from DataHub."""
        lines = [f"📈 ${ticker} — {quote.name or ticker}"]
        if quote.price:
            lines.append(f"Price: {quote.price.render()}")
        emoji = "🟢" if quote.change_pct >= 0 else "🔴"
        lines.append(f"Change: {emoji} {quote.change:+.2f} ({quote.change_pct:+.2f}%)")
        if quote.volume:
            lines.append(f"Volume: {quote.volume:,}")
        lines.append(f"Range: {quote.low:.2f} — {quote.high:.2f} (Open: {quote.open:.2f})")
        if quote.market_cap:
            cap = quote.market_cap
            if cap >= 1e12:
                lines.append(f"Market Cap: ${cap/1e12:.2f}T")
            elif cap >= 1e9:
                lines.append(f"Market Cap: ${cap/1e9:.2f}B")
            else:
                lines.append(f"Market Cap: ${cap/1e6:.0f}M")
        if quote.pe_ratio:
            lines.append(f"P/E: {quote.pe_ratio:.1f}")
        lines.append(f"Market: {quote.market_status} ({quote.currency})")
        if detail == "full":
            lines.append(f"\nPrev Close: {quote.prev_close:.2f}")
        return "\n".join(lines)

    def _fin_handle_portfolio_command(self, arg):
        """View and analyze portfolio holdings.

        Usage: /portfolio [summary|detail|risk]
        """
        sub = (arg or "").strip().lower() or "summary"

        # Try to get portfolio from secure memory
        memory = self._get_finance_component('memory')
        if not memory:
            memory = getattr(self.core, '_finance_components', {})
            if isinstance(memory, dict):
                memory = memory.get('memory')

        if memory:
            try:
                portfolio = memory.get_portfolio()
                if portfolio:
                    return self._format_portfolio(portfolio, sub)
            except Exception:
                pass

        return (
            "📊 Portfolio not configured yet.\n\n"
            "To set up portfolio tracking, tell me your holdings in natural language:\n"
            "  e.g. \"I hold 100 shares of AAPL, 50 TSLA, and 200 MSFT\"\n\n"
            "Or use /stock <ticker> to analyze individual stocks."
        )

    def _format_portfolio(self, portfolio, mode):
        """Format portfolio data."""
        lines = ["📊 Portfolio Overview"]
        total = 0
        for holding in portfolio:
            name = holding.get('ticker', holding.get('name', '?'))
            qty = holding.get('quantity', 0)
            value = holding.get('value', 0)
            total += value
            lines.append(f"  {name}: {qty} shares (${value:,.2f})")
        lines.append(f"\nTotal Value: ${total:,.2f}")
        return "\n".join(lines)

    def _fin_handle_market_command(self, arg):
        """Market overview — indices, sectors, sentiment.

        Usage: /market [us|cn|hk|global]
        """
        region = (arg or "").strip().lower() or "us"

        prompt = (
            f"Provide a market overview for {'global markets' if region == 'global' else region.upper() + ' market'}:\n"
            "- Major index performance (with numbers)\n"
            "- Sector rotation — which sectors are leading/lagging\n"
            "- Market sentiment indicator\n"
            "- Key events moving markets today\n"
            "- One-sentence outlook\n"
            "Be concise and data-driven. Note if data may not be real-time."
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.3, max_tokens=1500)
            return f"🌍 Market Overview ({region.upper()})\n\n{response}"
        except Exception as e:
            return f"❌ Market overview failed: {e}"

    def _fin_handle_news_command(self, arg):
        """Finance-focused news digest with impact analysis.

        Usage: /news [topic] — default: market-moving news
        """
        topic = (arg or "").strip() or "market-moving financial news"

        # Try NewsDigestEngine first
        digest = self._get_finance_component('digest')
        if not digest:
            core_fc = getattr(self.core, '_finance_components', {})
            if isinstance(core_fc, dict):
                digest = core_fc.get('digest')

        if digest:
            try:
                result = digest.get_digest(topic=topic, max_items=5)
                if result:
                    return f"📰 Finance News: {topic}\n\n{result}"
            except Exception:
                pass

        # Fallback: LLM-based
        prompt = (
            f"Provide a financial news digest on: {topic}\n"
            "For each news item:\n"
            "- Headline + one-sentence summary\n"
            "- Market impact: 🟢 positive / 🔴 negative / ⚪ neutral\n"
            "- Affected tickers/sectors\n\n"
            "Focus on actionable intelligence. Note if information may not be current."
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.3, max_tokens=2000)
            return f"📰 Finance News: {topic}\n\n{response}"
        except Exception as e:
            return f"❌ News digest failed: {e}"

    def _fin_handle_watchlist_command(self, arg):
        """Manage and check a stock watchlist.

        Usage:
          /watchlist          — show current watchlist
          /watchlist add AAPL — add ticker
          /watchlist rm TSLA  — remove ticker
        """
        parts = (arg or "").strip().split()
        action = parts[0].lower() if parts else "show"

        memory = self._get_finance_component('memory')
        if not memory:
            core_fc = getattr(self.core, '_finance_components', {})
            if isinstance(core_fc, dict):
                memory = core_fc.get('memory')

        if action == "add" and len(parts) > 1:
            tickers = [t.upper().lstrip("$") for t in parts[1:]]
            added = []
            for ticker in tickers:
                if memory:
                    try:
                        memory.add_to_watchlist(ticker)
                    except Exception:
                        pass
                added.append(f"${ticker}")
            if memory:
                return f"✅ Added {', '.join(added)} to watchlist."
            return f"✅ {', '.join(added)} noted. (Persistent storage not configured — will reset on restart)"

        elif action in ("rm", "remove", "del") and len(parts) > 1:
            tickers = [t.upper().lstrip("$") for t in parts[1:]]
            removed = []
            for ticker in tickers:
                if memory:
                    try:
                        memory.remove_from_watchlist(ticker)
                    except Exception:
                        pass
                removed.append(f"${ticker}")
            return f"🗑️ Removed {', '.join(removed)} from watchlist."

        else:  # show
            if memory:
                try:
                    wl = memory.get_watchlist()
                    if wl:
                        tickers = ", ".join(f"${t}" for t in wl)
                        return f"👀 Watchlist: {tickers}\n\nUse /stock <ticker> for analysis."
                except Exception:
                    pass
            return "👀 Watchlist is empty. Use /watchlist add <TICKER> to start tracking."

    def _fin_handle_quant_command(self, arg):
        """Quantitative financial computation.

        Usage: /quant <calculation>
        Examples:
          /quant CAGR 1000 to 2500 over 5 years
          /quant ROI invested 50000 returned 72000
          /quant compound 10000 at 7% for 20 years
        """
        if not arg or not arg.strip():
            return (
                "Usage: /quant <calculation>\n"
                "Examples:\n"
                "  /quant CAGR 1000 to 2500 over 5 years\n"
                "  /quant ROI invested 50000 returned 72000\n"
                "  /quant compound 10000 at 7% for 20 years\n"
                "  /quant DCF cashflow 5000 growth 10% discount 8% years 10"
            )

        # Try QuantEngine for exact computation
        quant = self._get_finance_component('quant')
        if quant:
            try:
                result = quant.compute(arg.strip())
                if result and result.value is not None:
                    output = [f"🔢 Quant Result: {result}"]
                    if result.formula:
                        output.append(f"Formula: {result.formula}")
                    if result.steps:
                        output.append("Steps:")
                        for step in result.steps:
                            output.append(f"  • {step}")
                    return "\n".join(output)
            except Exception:
                pass

        # Fallback: LLM with strict computation instruction
        prompt = (
            f"Compute the following financial calculation EXACTLY (do not estimate):\n"
            f"{arg.strip()}\n\n"
            "Show:\n"
            "1. The formula used\n"
            "2. Step-by-step calculation\n"
            "3. Final result with appropriate precision\n"
            "Use actual math, not approximations."
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            response = self.core.generate_completion(messages, temperature=0.1, max_tokens=1500)
            return f"🔢 Quant Computation:\n\n{response}"
        except Exception as e:
            return f"❌ Quant computation failed: {e}"
