# agent/finance/telegram_bot.py
"""
NeoMind Telegram Bot — independent agent identity in Telegram groups.

Runs as a standalone Telegram bot alongside OpenClaw (or any other bot).
Both agents live in the same group, each with their own personality.

Features:
- Responds to /neo_* commands and @neomind_bot mentions
- Auto-detects financial queries in group chat
- Can @openclaw for collaboration (delegates non-finance tasks)
- Pushes alerts, digests, dashboards as Telegram messages
- Sends HTML dashboard files as document attachments
- Rate-limited to avoid Telegram API abuse

Architecture:
    Telegram Bot API (polling/webhook)
        ↓
    MessageRouter (command? mention? finance keyword? @openclaw?)
        ↓
    OpenClawFinanceSkill (reuses all 16 /stock, /crypto, etc.)
        ↓
    Reply back to Telegram group
"""

import os
import re
import json
import asyncio
import logging
import html
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("neomind.telegram")

try:
    from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, ApplicationBuilder,
        CommandHandler, MessageHandler, CallbackQueryHandler,
        ContextTypes, filters,
    )
    from telegram.constants import ParseMode, ChatAction
    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False
    # Stub types so class definitions don't break at import time
    Update = Any
    class ContextTypes:
        DEFAULT_TYPE = Any
    class ParseMode:
        HTML = "HTML"
    class ChatAction:
        TYPING = "typing"
    class filters:
        TEXT = None
        COMMAND = None
        Regex = lambda x: None


# ── Configuration ────────────────────────────────────────────────────

@dataclass
class TelegramConfig:
    """Bot configuration — all from environment variables."""
    token: str = ""                  # TELEGRAM_BOT_TOKEN (from BotFather)
    bot_username: str = ""           # @neomind_fin_bot (auto-detected)
    openclaw_username: str = ""      # @openclaw_bot (for delegation)
    allowed_groups: List[str] = field(default_factory=list)  # restrict to specific groups
    admin_users: List[int] = field(default_factory=list)      # admin user IDs
    auto_finance_detect: bool = True  # respond to financial keywords without @mention
    rate_limit_seconds: float = 1.0   # min interval between responses
    max_message_length: int = 4096    # Telegram message length limit

    @classmethod
    def from_env(cls) -> 'TelegramConfig':
        return cls(
            token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            openclaw_username=os.getenv("OPENCLAW_TELEGRAM_USERNAME", ""),
            allowed_groups=os.getenv("TELEGRAM_ALLOWED_GROUPS", "").split(",") if os.getenv("TELEGRAM_ALLOWED_GROUPS") else [],
            admin_users=[int(x) for x in os.getenv("TELEGRAM_ADMIN_USERS", "").split(",") if x.strip().isdigit()],
            auto_finance_detect=os.getenv("TELEGRAM_AUTO_DETECT", "true").lower() == "true",
        )


# ── Finance Keyword Triggers ────────────────────────────────────────

FINANCE_TRIGGERS = {
    # English
    "stock", "price", "market", "earnings", "revenue", "dividend",
    "crypto", "bitcoin", "btc", "eth", "portfolio", "invest",
    "fed", "inflation", "gdp", "rate cut", "rate hike", "bond", "yield",
    "ipo", "merger", "acquisition", "nasdaq", "s&p", "dow",
    # Chinese
    "股票", "股价", "行情", "财报", "营收", "分红",
    "加密", "比特币", "以太坊", "投资组合",
    "央行", "利率", "通胀", "降息", "加息",
    "A股", "港股", "美股", "基金",
}

# Ticker pattern: $AAPL, $BTC, etc.
TICKER_RE = re.compile(r'\$[A-Z]{1,5}\b')


# ── Message Router ───────────────────────────────────────────────────

class MessageRouter:
    """Decides whether NeoMind should respond to a group message.

    Priority:
    1. /neo_* commands → always respond
    2. Direct @mention of NeoMind bot → always respond
    3. Reply to NeoMind's previous message → always respond
    4. Financial keywords + auto_detect enabled → respond
    5. @openclaw mention in NeoMind's response → delegate to OpenClaw
    6. Everything else → ignore (let other bots handle it)
    """

    def __init__(self, bot_username: str, config: TelegramConfig):
        self.bot_username = bot_username.lower().lstrip("@")
        self.config = config

    def should_respond(self, text: str, is_reply_to_me: bool,
                       chat_id: Optional[int] = None,
                       is_private: bool = False) -> tuple:
        """Returns (should_respond: bool, reason: str).

        In private chat: always respond (user chose to talk to us).
        In group chat: only respond to commands, @mentions, and finance queries.
        """
        if not text:
            return False, ""

        text_lower = text.lower()

        # 1. Direct commands: /neo_stock, /neo_news, etc.
        if text_lower.startswith("/neo_") or text_lower.startswith("/neo "):
            return True, "command"

        # Short aliases: /stock, /crypto, /news (if in allowed context)
        fin_commands = ["/stock", "/crypto", "/news", "/digest", "/compute",
                        "/portfolio", "/predict", "/alert", "/compare",
                        "/watchlist", "/risk", "/sources", "/chart"]
        for cmd in fin_commands:
            if text_lower.startswith(cmd):
                return True, "fin_command"

        # 2. @mention
        if f"@{self.bot_username}" in text_lower:
            return True, "mention"

        # 3. Reply to my message
        if is_reply_to_me:
            return True, "reply"

        # 4. Private chat: always respond
        if is_private:
            if self._is_finance_query(text):
                return True, "private_finance"
            return True, "private_chat"

        # 5. Group auto finance detection
        if self.config.auto_finance_detect:
            if self._is_finance_query(text):
                return True, "auto_detect"

        return False, ""

    def extract_query(self, text: str, reason: str) -> str:
        """Extract the actual query from the message, stripping bot prefix."""
        if reason == "command":
            # /neo_stock AAPL → /stock AAPL
            text = re.sub(r'^/neo[_ ]', '/', text, count=1)
        elif reason == "mention":
            # @neomind_bot what is AAPL price? → what is AAPL price?
            text = re.sub(rf'@{re.escape(self.bot_username)}\s*', '', text, flags=re.IGNORECASE)
        return text.strip()

    def should_delegate_to_openclaw(self, text: str) -> Optional[str]:
        """Check if user is asking NeoMind to involve OpenClaw.

        Returns the delegation query or None.
        """
        patterns = [
            r'(?:ask|tell|ping|叫|问)\s*(?:@?\s*openclaw|oc)',
            r'@openclaw',
            r'openclaw.*(?:help|assist|check|看看|帮)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Return the rest of the message as the delegation query
                remainder = text[match.end():].strip()
                return remainder or text
        return None

    @staticmethod
    def _is_finance_query(text: str) -> bool:
        text_lower = text.lower()
        # Ticker mention
        if TICKER_RE.search(text):
            return True
        # Keyword match (need 1+ trigger)
        for trigger in FINANCE_TRIGGERS:
            if trigger in text_lower:
                return True
        return False


# ── Telegram Bot ─────────────────────────────────────────────────────

class NeoMindTelegramBot:
    """
    NeoMind's independent Telegram bot.

    Usage:
        bot = NeoMindTelegramBot(components=finance_components)
        await bot.start()  # blocking — runs polling loop

    Or in Docker:
        The docker-entrypoint handles lifecycle.
    """

    def __init__(self, components: Dict[str, Any], config: Optional[TelegramConfig] = None):
        if not HAS_TELEGRAM:
            raise ImportError(
                "python-telegram-bot not installed. "
                "Install with: pip install 'python-telegram-bot>=20.0'"
            )

        self.config = config or TelegramConfig.from_env()
        if not self.config.token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN not set. "
                "Create a bot via @BotFather and set the token in .env"
            )

        self.components = components
        self._skill = None  # lazy init
        self._current_mode = "fin"  # default personality
        self._thinking_enabled = False  # /think toggle
        self._app: Optional[Application] = None
        self._bot_id: Optional[int] = None
        self._last_response_time: Dict[int, float] = {}  # chat_id → timestamp

    async def start(self):
        """Start the Telegram bot (long polling mode)."""
        print("[bot] Building Telegram application...", flush=True)

        # Build the application
        self._app = (
            ApplicationBuilder()
            .token(self.config.token)
            .build()
        )

        # Get bot info
        print("[bot] Connecting to Telegram API...", flush=True)
        bot_info = await self._app.bot.get_me()
        self.config.bot_username = bot_info.username
        self._bot_id = bot_info.id
        print(f"[bot] Identity: @{bot_info.username} (ID: {bot_info.id})", flush=True)

        # Initialize router
        self._router = MessageRouter(bot_info.username, self.config)

        # Initialize skill adapter (reuse OpenClaw skill for command handling)
        from .openclaw_skill import OpenClawFinanceSkill
        self._skill = OpenClawFinanceSkill(components=self.components)

        # Register handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("mode", self._cmd_mode))
        self._app.add_handler(CommandHandler("think", self._cmd_think))
        # Catch all /neo_* commands
        self._app.add_handler(MessageHandler(
            filters.Regex(r'^/neo[_ ]') & ~filters.COMMAND, self._handle_message
        ))
        # Catch finance slash commands
        for cmd in ["stock", "crypto", "news", "digest", "compute", "portfolio",
                     "predict", "alert", "compare", "watchlist", "risk",
                     "sources", "chart", "calendar", "memory"]:
            self._app.add_handler(CommandHandler(cmd, self._handle_command))
        # Catch unrecognized commands (typos like /model instead of /mode)
        self._app.add_handler(MessageHandler(
            filters.COMMAND, self._handle_unknown_command
        ))
        # Catch all other messages (for @mention and auto-detect)
        self._app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._handle_message
        ))

        # Start polling
        print(f"[bot] Registering {14 + 3} command handlers...", flush=True)
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        print(f"[bot] ✅ @{bot_info.username} is LIVE — listening for messages", flush=True)

        # Keep running
        try:
            await asyncio.Event().wait()  # block forever
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await self.stop()

    async def stop(self):
        """Graceful shutdown."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        logger.info("Bot stopped")

    # ── Command Handlers ─────────────────────────────────────────────

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start — introduce the bot."""
        await update.message.reply_text(
            "👋 我是 <b>NeoMind Finance</b> — 个人金融与投资智能 Agent\n\n"
            "我能做什么：\n"
            "• <code>/stock AAPL</code> — 股票查询\n"
            "• <code>/crypto BTC</code> — 加密货币\n"
            "• <code>/news Fed rate</code> — 多源新闻搜索\n"
            "• <code>/digest</code> — 每日市场摘要\n"
            "• <code>/compute compound 10000 0.08 10</code> — 金融计算\n"
            "• 或直接用中英文问我金融问题\n\n"
            "在群里可以 @我 或使用 /neo_stock 前缀",
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help — list all commands."""
        commands = [
            ("/stock <symbol>", "股票价格和分析"),
            ("/crypto <symbol>", "加密货币行情"),
            ("/news [query]", "多源新闻搜索 (EN+ZH)"),
            ("/digest", "每日市场摘要 + Dashboard"),
            ("/compute <expr>", "金融计算 (复利/DCF/BS)"),
            ("/predict <sym> <方向> <置信度>", "记录预测"),
            ("/watchlist [add|remove] <sym>", "自选股管理"),
            ("/risk", "风险评估 (VaR/Sharpe)"),
            ("/sources", "数据源信任度排名"),
            ("/compare <sym1> <sym2>", "资产对比"),
            ("/status", "Bot 和搜索引擎状态"),
        ]
        lines = ["<b>NeoMind Finance — 命令列表</b>\n"]
        for cmd, desc in commands:
            lines.append(f"<code>{cmd}</code>\n  {desc}\n")
        lines.append("\n💡 群聊中用 <code>/neo_stock</code> 前缀避免和其他 bot 冲突")
        lines.append("💡 直接 @我 或发含 $AAPL 的消息也会触发")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status — show bot and search engine status."""
        lines = ["<b>NeoMind Status</b>\n"]

        search = self.components.get("search")
        if search:
            t1 = len(search.tier1_sources)
            t2 = len(search.tier2_sources)
            t3 = len(search.tier3_sources)
            lines.append(f"🔍 搜索引擎: {t1+t2+t3} 源 (T1:{t1} T2:{t2} T3:{t3})")
            lines.append(f"   内容提取: {'✅' if search.extractor.available else '❌'}")

        data_hub = self.components.get("data_hub")
        if data_hub:
            lines.append("📊 数据源: Finnhub, yfinance, AKShare, CoinGecko")

        memory = self.components.get("memory")
        lines.append(f"🧠 加密记忆: {'✅' if memory else '❌'}")

        sync = self.components.get("sync")
        if sync:
            lines.append(f"📱 Sync 模式: {sync._mode}")

        lines.append(f"\n🤖 Bot: @{self.config.bot_username}")
        if self.config.openclaw_username:
            lines.append(f"🤝 OpenClaw: @{self.config.openclaw_username}")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /mode — switch personality at runtime."""
        args = " ".join(context.args) if context.args else ""
        current = getattr(self, '_current_mode', 'fin')

        if not args:
            modes_text = "\n".join([
                f"• <code>/mode chat</code> — 通用对话{'（当前）' if current == 'chat' else ''}",
                f"• <code>/mode coding</code> — 编程助手{'（当前）' if current == 'coding' else ''}",
                f"• <code>/mode fin</code> — 金融智能{'（当前）' if current == 'fin' else ''}",
            ])
            await update.message.reply_text(
                f"当前人格: <b>{current}</b>\n\n"
                f"可用人格：\n{modes_text}\n\n"
                "切换后 system prompt、可用命令、行为逻辑都会变",
                parse_mode=ParseMode.HTML,
            )
            return

        target = args.lower().strip()
        if target not in ("chat", "coding", "fin"):
            await update.message.reply_text(
                f"❌ 未知人格: {args}\n可选: chat / coding / fin"
            )
            return

        if target == current:
            await update.message.reply_text(f"已经在 <b>{target}</b> 模式了", parse_mode=ParseMode.HTML)
            return

        # Switch mode
        self._current_mode = target

        # Reload finance components if switching to/from fin
        if target == "fin":
            from agent_config import AgentConfigManager
            from agent.finance import get_finance_components
            cfg = AgentConfigManager(mode='fin')
            self.components = get_finance_components(cfg)
            from .openclaw_skill import OpenClawFinanceSkill
            self._skill = OpenClawFinanceSkill(components=self.components)

        descriptions = {
            "chat": "通用对话模式 — 自由聊天、翻译、搜索",
            "coding": "编程助手模式 — 代码分析、文件操作、shell",
            "fin": "金融智能模式 — 股票、加密货币、新闻、量化分析",
        }

        await update.message.reply_text(
            f"✅ 已切换到 <b>{target}</b> 模式\n{descriptions[target]}",
            parse_mode=ParseMode.HTML,
        )

    # ── Message Handlers ─────────────────────────────────────────────

    async def _cmd_think(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /think — toggle thinking (reasoning) mode."""
        self._thinking_enabled = not self._thinking_enabled
        status = "ON" if self._thinking_enabled else "OFF"
        model = "deepseek-reasoner" if self._thinking_enabled else "deepseek-chat"
        await update.message.reply_text(
            f"🧠 Thinking mode: <b>{status}</b>\n"
            f"Model: <code>{model}</code>\n\n"
            f"{'开启后每条回复会包含思考过程（灰色字体）。回复更深入但更慢。' if self._thinking_enabled else '已关闭思考模式，回复更快。'}",
            parse_mode=ParseMode.HTML,
        )

    async def _handle_unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle unrecognized commands with helpful suggestions."""
        text = update.message.text or ""
        cmd = text.split()[0].lower() if text else ""

        # Common typos / close matches
        suggestions = {
            "/model": "/mode",
            "/modes": "/mode",
            "/switch": "/mode",
            "/stocks": "/stock",
            "/search": "/news",
            "/price": "/stock",
            "/btc": "/crypto BTC",
            "/eth": "/crypto ETH",
            "/bitcoin": "/crypto BTC",
            "/config": "/status",
            "/settings": "/status",
        }

        suggestion = suggestions.get(cmd)
        if suggestion:
            await update.message.reply_text(
                f"你是不是想说 <code>{suggestion}</code>？",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(
                f"未知命令: {cmd}\n发 <code>/help</code> 查看可用命令",
                parse_mode=ParseMode.HTML,
            )

    async def _handle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle finance slash commands (/stock, /crypto, etc.)."""
        text = update.message.text
        await self._process_and_reply(update, text, "fin_command")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle non-command messages (mentions, auto-detect, etc.)."""
        msg = update.message
        if not msg or not msg.text:
            return

        # Check if this is a reply to one of my messages
        is_reply_to_me = (
            msg.reply_to_message
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.id == self._bot_id
        )

        # Detect if this is a private (1:1) chat
        is_private = msg.chat.type == "private"

        # Route the message
        should_respond, reason = self._router.should_respond(
            msg.text, is_reply_to_me, msg.chat_id, is_private=is_private
        )

        if not should_respond:
            return

        # Rate limiting
        now = asyncio.get_event_loop().time()
        last = self._last_response_time.get(msg.chat_id, 0)
        if now - last < self.config.rate_limit_seconds:
            return
        self._last_response_time[msg.chat_id] = now

        # Extract the actual query
        query = self._router.extract_query(msg.text, reason)

        await self._process_and_reply(update, query, reason)

    async def _process_and_reply(self, update: Update, text: str, reason: str):
        """Process a query and send reply.

        For /commands (fin_command): route through finance skill.
        For everything else: send to DeepSeek LLM for a real conversation.
        When thinking is enabled: stream thinking into one message, then send response as another.
        """
        msg = update.message

        # Show typing indicator
        await msg.chat.send_action(ChatAction.TYPING)

        # 1. Explicit finance commands → skill handler (fast, no LLM call needed)
        if reason == "fin_command" and self._skill:
            from .openclaw_gateway import IncomingMessage
            incoming = IncomingMessage(
                channel="telegram",
                sender=str(msg.from_user.id) if msg.from_user else "",
                sender_name=msg.from_user.first_name if msg.from_user else "",
                text=text,
                chat_id=str(msg.chat_id),
            )
            try:
                reply = await self._skill.handle_incoming(incoming)
                if reply:
                    await self._send_long_message(msg, reply)
                    return
            except Exception as e:
                await msg.reply_text(f"⚠️ Error: {e}")
                return

        # 2. Everything else → send to DeepSeek LLM
        thinking = getattr(self, '_thinking_enabled', False)

        if thinking:
            await self._ask_llm_streaming(msg, text)
        else:
            reply = await self._ask_llm(text)
            if reply:
                await self._send_long_message(msg, reply)
            else:
                await msg.reply_text("⚠️ LLM 未响应，请稍后重试")

    # ── LLM Shared Helpers ──────────────────────────────────────────

    def _get_system_prompt(self) -> str:
        current_mode = getattr(self, '_current_mode', 'fin')
        prompts = {
            "fin": (
                "你是 NeoMind Finance，一个个人金融与投资智能助手。"
                "你在 Telegram 上运行。回复简洁、有用。"
                "用户可以问你金融问题，也可以闲聊。"
                "如果用户问金融相关的问题，尽量给出有用的分析。"
                "如果用户只是打招呼或闲聊，正常回复即可，不要强行推荐金融命令。"
                "你支持 /stock, /crypto, /news, /digest 等命令，但用户也可以用自然语言。"
                "回复用用户的语言（中文问中文答，英文问英文答）。"
            ),
            "chat": (
                "你是 NeoMind，一个通用 AI 助手。"
                "你在 Telegram 上运行。回复简洁、自然、有帮助。"
                "用户可以问你任何问题，聊天、翻译、搜索都行。"
                "回复用用户的语言。"
            ),
            "coding": (
                "你是 NeoMind，一个编程助手。"
                "你在 Telegram 上运行。回复简洁。"
                "可以帮用户分析代码、解释概念、调试问题。"
                "代码用 markdown code block 格式。"
                "回复用用户的语言。"
            ),
        }
        return prompts.get(current_mode, prompts["chat"])

    def _get_history(self) -> list:
        if not hasattr(self, '_chat_histories'):
            self._chat_histories = {}
        chat_key = "default"
        if chat_key not in self._chat_histories:
            self._chat_histories[chat_key] = []
        return self._chat_histories[chat_key]

    def _resolve_api(self, thinking: bool = False) -> tuple:
        """Returns (api_key, base_url, model) or raises."""
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = "https://api.deepseek.com/chat/completions"
        model = "deepseek-reasoner" if thinking else "deepseek-chat"

        if not api_key:
            api_key = os.getenv("ZAI_API_KEY", "")
            base_url = "https://api.z.ai/api/paas/v4/chat/completions"
            model = "glm-5" if thinking else "glm-4.5-flash"

        return api_key, base_url, model

    # ── Normal mode: simple non-streaming call ───────────────────

    async def _ask_llm(self, user_message: str) -> Optional[str]:
        """Non-streaming LLM call. Used when thinking is OFF."""
        import requests as req

        history = self._get_history()
        history.append({"role": "user", "content": user_message})
        if len(history) > 20:
            history[:] = history[-20:]

        messages = [{"role": "system", "content": self._get_system_prompt()}] + history
        api_key, base_url, model = self._resolve_api(thinking=False)

        if not api_key:
            return "⚠️ No API key configured (DEEPSEEK_API_KEY or ZAI_API_KEY)"

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: req.post(
                base_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": 1024, "temperature": 0.7, "stream": False},
                timeout=30,
            ))
            if response.status_code == 200:
                reply = response.json()["choices"][0]["message"]["content"].strip()
                history.append({"role": "assistant", "content": reply})
                return reply
            else:
                return f"⚠️ API error: {response.status_code}"
        except Exception as e:
            return f"⚠️ Request failed: {e}"

    # ── Thinking mode: streaming with live Telegram message updates ──

    async def _ask_llm_streaming(self, msg, user_message: str):
        """Streaming LLM call with thinking. Used when /think is ON.

        Flow:
        1. Send "🧠 Thinking..." placeholder message
        2. Stream API response, collecting reasoning_content chunks
        3. Edit the placeholder every ~2s with accumulated thinking text
        4. When content (final answer) starts, send it as a new message
        """
        import requests as req

        history = self._get_history()
        history.append({"role": "user", "content": user_message})
        if len(history) > 20:
            history[:] = history[-20:]

        messages = [{"role": "system", "content": self._get_system_prompt()}] + history
        api_key, base_url, model = self._resolve_api(thinking=True)

        if not api_key:
            await msg.reply_text("⚠️ No API key configured")
            return

        # Step 1: Send thinking placeholder
        thinking_msg = await msg.reply_text(
            "🧠 <b>Thinking...</b>",
            parse_mode=ParseMode.HTML,
        )

        thinking_text = ""
        response_text = ""
        last_edit_time = 0
        EDIT_INTERVAL = 2.0  # edit Telegram message at most every 2 seconds

        try:
            # Step 2: Stream the response
            response = await asyncio.get_event_loop().run_in_executor(None, lambda: req.post(
                base_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": 4096, "stream": True},
                timeout=120,
                stream=True,
            ))

            if response.status_code != 200:
                await thinking_msg.edit_text(f"⚠️ API error: {response.status_code}")
                return

            # Step 3: Process SSE stream
            for line in response.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8", errors="ignore")
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})

                    # Collect reasoning_content (thinking)
                    rc = delta.get("reasoning_content", "")
                    if rc:
                        thinking_text += rc

                    # Collect content (final answer)
                    ct = delta.get("content", "")
                    if ct:
                        response_text += ct

                    # Periodically update the thinking message
                    now = asyncio.get_event_loop().time()
                    if rc and (now - last_edit_time) >= EDIT_INTERVAL:
                        last_edit_time = now
                        display = self._format_thinking(thinking_text)
                        try:
                            await thinking_msg.edit_text(
                                display,
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception:
                            pass  # Telegram rate limit, skip this update

                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

            # Step 4: Final update of thinking message
            if thinking_text:
                display = self._format_thinking(thinking_text, final=True)
                try:
                    await thinking_msg.edit_text(display, parse_mode=ParseMode.HTML)
                except Exception:
                    pass
            else:
                try:
                    await thinking_msg.edit_text("🧠 <i>(no reasoning output)</i>", parse_mode=ParseMode.HTML)
                except Exception:
                    pass

            # Step 5: Send final response as a separate message
            if response_text.strip():
                history.append({"role": "assistant", "content": response_text.strip()})
                await self._send_long_message(msg, response_text.strip())
            else:
                await msg.reply_text("⚠️ No response generated")

        except Exception as e:
            try:
                await thinking_msg.edit_text(f"⚠️ Error: {e}")
            except Exception:
                await msg.reply_text(f"⚠️ Error: {e}")

    @staticmethod
    def _format_thinking(text: str, final: bool = False) -> str:
        """Format thinking content using Telegram's expandable blockquote.

        Uses <blockquote expandable> so the thinking is:
        - Visually indented with a left border (clearly distinct from response)
        - Collapsed by default when long (user taps to expand)
        - Italic for extra visual separation
        """
        # Truncate for Telegram's 4096 char limit (leave room for tags)
        max_len = 3800
        if len(text) > max_len:
            text = text[-max_len:]
            text = "…\n" + text

        escaped = html.escape(text)
        header = "🧠 <b>Thinking</b>" if final else "🧠 <b>Thinking...</b>"

        return (
            f"{header}\n"
            f"<blockquote expandable>{escaped}</blockquote>"
        )

    async def _send_long_message(self, msg, text: str):
        """Send a message, splitting if it exceeds Telegram's 4096 char limit."""
        # Convert markdown-style links to HTML
        text = self._md_to_html(text)

        if len(text) <= self.config.max_message_length:
            try:
                await msg.reply_text(text, parse_mode=ParseMode.HTML,
                                     disable_web_page_preview=True)
            except Exception:
                # Fallback: send without formatting
                await msg.reply_text(
                    re.sub(r'<[^>]+>', '', text),
                    disable_web_page_preview=True,
                )
        else:
            # Split into chunks
            chunks = self._split_message(text)
            for chunk in chunks:
                try:
                    await msg.reply_text(chunk, parse_mode=ParseMode.HTML,
                                         disable_web_page_preview=True)
                except Exception:
                    await msg.reply_text(
                        re.sub(r'<[^>]+>', '', chunk),
                        disable_web_page_preview=True,
                    )

    async def send_dashboard(self, chat_id: int, dashboard_html: str, caption: str = ""):
        """Send an HTML dashboard as a document attachment."""
        if not self._app:
            return

        # Save to temp file
        import tempfile
        filename = f"neomind_digest_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
        filepath = Path(tempfile.gettempdir()) / filename
        filepath.write_text(dashboard_html, encoding="utf-8")

        try:
            await self._app.bot.send_document(
                chat_id=chat_id,
                document=open(filepath, "rb"),
                filename=filename,
                caption=caption or "📊 NeoMind Finance Dashboard",
            )
        finally:
            filepath.unlink(missing_ok=True)

    async def push_alert_to_groups(self, alert: Dict):
        """Push a finance alert to all known group chats."""
        if not self._app:
            return

        symbol = alert.get("symbol", "?")
        price = alert.get("price", "?")
        condition = alert.get("condition", "")
        urgency = alert.get("urgency", "normal")
        icon = {"critical": "🚨", "high": "⚠️", "normal": "📊"}.get(urgency, "📊")

        text = f"{icon} <b>{html.escape(symbol)}</b> — ${price}\n"
        if condition:
            text += f"触发条件: {html.escape(condition)}\n"

        # Send to all allowed groups
        for group_id in self.config.allowed_groups:
            try:
                await self._app.bot.send_message(
                    chat_id=int(group_id),
                    text=text,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.warning(f"Failed to send alert to {group_id}: {e}")

    # ── Formatting Helpers ───────────────────────────────────────────

    @staticmethod
    def _md_to_html(text: str) -> str:
        """Convert simple markdown to Telegram HTML."""
        # Bold: **text** → <b>text</b>
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        # Italic: _text_ → <i>text</i>  (but not in URLs)
        text = re.sub(r'(?<!\w)_([^_]+?)_(?!\w)', r'<i>\1</i>', text)
        # Code: `text` → <code>text</code>
        text = re.sub(r'`([^`]+?)`', r'<code>\1</code>', text)
        # Links: [text](url) → <a href="url">text</a>
        text = re.sub(r'\[([^\]]+?)\]\(([^)]+?)\)', r'<a href="\2">\1</a>', text)
        return text

    @staticmethod
    def _split_message(text: str, max_len: int = 4096) -> List[str]:
        """Split a long message into chunks at paragraph boundaries."""
        if len(text) <= max_len:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break

            # Find a good split point (paragraph break, then line break)
            split_at = text.rfind("\n\n", 0, max_len)
            if split_at == -1:
                split_at = text.rfind("\n", 0, max_len)
            if split_at == -1:
                split_at = max_len

            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")

        return chunks


# ── Standalone Runner ────────────────────────────────────────────────

async def run_telegram_bot(components: Dict[str, Any]):
    """Entry point for running the Telegram bot standalone."""
    config = TelegramConfig.from_env()
    if not config.token:
        print("⚠️  TELEGRAM_BOT_TOKEN not set — Telegram bot disabled")
        print("   Create a bot via @BotFather and set the token in .env")
        return

    bot = NeoMindTelegramBot(components=components, config=config)
    await bot.start()
