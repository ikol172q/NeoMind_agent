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
import time
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
        # Mode is per-chat, stored in SQLite (see ChatStore.get_mode/set_mode)
        self._thinking_enabled = False  # /think toggle
        self._app: Optional[Application] = None
        self._bot_id: Optional[int] = None
        self._last_response_time: Dict[int, float] = {}  # chat_id → timestamp

        # Persistent chat history (SQLite — survives container restarts)
        from .chat_store import ChatStore
        self._store = ChatStore()

        # LLM usage tracking (SQLite — survives container restarts)
        from .usage_tracker import get_usage_tracker
        self._usage = get_usage_tracker()

        # Provider state (shared with xbar — bidirectional sync)
        from .provider_state import ProviderStateManager
        self._state_mgr = ProviderStateManager()
        self._state_mgr.register_bot("neomind")
        print(f"[bot] Chat history DB: {self._store.db_path}", flush=True)

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
        self._app.add_handler(CommandHandler("history", self._cmd_history))
        self._app.add_handler(CommandHandler("clear", self._cmd_clear))
        self._app.add_handler(CommandHandler("archive", self._cmd_archive))
        self._app.add_handler(CommandHandler("purge", self._cmd_purge))
        self._app.add_handler(CommandHandler("admin", self._cmd_admin))
        self._app.add_handler(CommandHandler("context", self._cmd_context))
        self._app.add_handler(CommandHandler("setctx", self._cmd_setctx))
        self._app.add_handler(CommandHandler("hn", self._cmd_hn))
        self._app.add_handler(CommandHandler("subscribe", self._cmd_subscribe))
        self._app.add_handler(CommandHandler("skills", self._cmd_skills))
        self._app.add_handler(CommandHandler("careful", self._cmd_careful))
        self._app.add_handler(CommandHandler("sprint", self._cmd_sprint))
        self._app.add_handler(CommandHandler("evidence", self._cmd_evidence))
        self._app.add_handler(CommandHandler("provider", self._cmd_provider))
        self._app.add_handler(CommandHandler("usage", self._cmd_usage))
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

        # Start background scheduler for auto-push (HN, etc.)
        asyncio.create_task(self._scheduler_loop())

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
        """Handle /help — grouped command reference."""
        current_mode = self._store.get_mode(update.message.chat_id)
        thinking = "ON 🧠" if getattr(self, '_thinking_enabled', False) else "OFF"

        await update.message.reply_text(
            f"📋 <b>NeoMind 命令 (mode: {current_mode}, think: {thinking})</b>\n"
            "\n"
            "── 💬 <b>对话</b> ──\n"
            "直接打字即可对话，无需命令\n"
            "<code>/think</code> — 开关深度思考模式\n"
            "<code>/mode</code> <code>chat</code>|<code>fin</code>|<code>coding</code> — 切换人格\n"
            "\n"
            "── 📈 <b>金融 (fin 模式)</b> ──\n"
            "<code>/stock</code> AAPL — 股票\n"
            "<code>/crypto</code> BTC — 加密货币\n"
            "<code>/news</code> 央行降息 — 多源新闻\n"
            "<code>/digest</code> — 每日市场摘要\n"
            "<code>/compute</code> compound 10000 0.08 10 — 金融计算\n"
            "<code>/predict</code> NVDA bullish 0.8 — 记录预测\n"
            "<code>/compare</code> AAPL MSFT — 资产对比\n"
            "<code>/sources</code> — 数据源信任度\n"
            "\n"
            "── 📡 <b>资讯</b> ──\n"
            "<code>/hn</code> top|best|new|ask|show — Hacker News\n"
            "<code>/subscribe hn</code> — 订阅 HN 定时推送\n"
            "\n"
            "── ⚙️ <b>工作流</b> ──\n"
            "<code>/skills</code> — 查看当前模式可用 skills\n"
            "<code>/sprint new [goal]</code> — 结构化任务流程\n"
            "<code>/careful</code> — 开关安全护栏\n"
            "<code>/evidence</code> — 操作审计日志\n"
            "\n"
            "── 🔧 <b>管理</b> ──\n"
            "<code>/clear</code> — 归档对话 (LLM 重开)\n"
            "<code>/context</code> — token 使用量\n"
            "<code>/status</code> — Bot 状态\n"
            "<code>/admin</code> — 管理面板 (历史/归档/清除/统计)\n"
            "\n"
            "<i>群聊: @我 或 /neo_stock 前缀 | 含 $AAPL 自动触发</i>",
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
        """Handle /mode — switch personality for THIS chat (per-chat, not global)."""
        args = " ".join(context.args) if context.args else ""
        cid = update.message.chat_id
        current = self._store.get_mode(cid)

        if not args:
            modes_text = "\n".join([
                f"• <code>/mode chat</code> — 通用对话{'（当前）' if current == 'chat' else ''}",
                f"• <code>/mode coding</code> — 编程助手{'（当前）' if current == 'coding' else ''}",
                f"• <code>/mode fin</code> — 金融智能{'（当前）' if current == 'fin' else ''}",
            ])
            await update.message.reply_text(
                f"当前人格: <b>{current}</b>（仅此对话）\n\n"
                f"可用人格：\n{modes_text}\n\n"
                "每个对话的人格独立，互不影响",
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

        # Switch mode for this chat
        self._store.set_mode(cid, target)

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

    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /history — alias for /admin history."""
        # Rewrite args and forward to admin handler
        context.args = ["history"] + (list(context.args) if context.args else [])
        await self._cmd_admin(update, context)

    async def _cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clear — archive current conversation (soft-clear).

        Messages are archived (hidden from LLM), not deleted.
        LLM starts fresh, but admin can still view archived messages.
        """
        cid = update.message.chat_id
        count = self._store.clear_active(cid)
        await update.message.reply_text(
            f"🗑 对话已归档（{count} 条消息）\nLLM 重新开始，旧消息已存档"
        )

    async def _cmd_archive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Alias: /archive → /clear."""
        await self._cmd_clear(update, context)

    async def _cmd_purge(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Alias: /purge → /admin purge."""
        context.args = ["purge"] + (list(context.args) if context.args else [])
        await self._cmd_admin(update, context)

    async def _cmd_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin — unified admin panel.

        /admin              — show help
        /admin stats        — DB statistics
        /admin history [N] [full] — active messages (with optional thinking)
        /admin archived [N] — archived messages
        /admin chats        — list all chats
        """
        parts = list(context.args) if context.args else []
        subcmd = parts[0] if parts else ""
        rest = parts[1:] if len(parts) > 1 else []
        cid = update.message.chat_id

        if subcmd == "stats":
            stats = self._store.get_stats()
            await update.message.reply_text(
                f"📊 <b>Chat Store Stats</b>\n\n"
                f"Active chats: {stats['active_chats']}\n"
                f"Total chats: {stats['total_chats']}\n"
                f"Active messages: {stats['active_messages']:,}\n"
                f"Archived messages: {stats['archived_messages']:,}\n"
                f"DB size: {stats['db_size_kb']} KB\n"
                f"DB path: <code>{stats['db_path']}</code>",
                parse_mode=ParseMode.HTML,
            )

        elif subcmd == "history":
            rest_str = " ".join(rest)
            show_thinking = "full" in rest_str or "think" in rest_str
            try:
                limit = int(rest[0]) if rest and rest[0].isdigit() else 10
            except (ValueError, IndexError):
                limit = 10

            messages = self._store.get_history(cid, limit=limit, include_thinking=show_thinking)
            if not messages:
                await update.message.reply_text("没有对话记录")
                return

            lines = [f"📜 <b>对话历史</b> ({len(messages)} 条)\n"]
            for msg in messages:
                role = "👤" if msg["role"] == "user" else "🤖"
                content = msg["content"][:150]
                ts = msg.get("created_at", "")[:16]
                lines.append(f"{role} <i>{ts}</i>\n{html.escape(content)}")
                if show_thinking and msg.get("thinking"):
                    preview = msg["thinking"][:300]
                    lines.append(f"<blockquote expandable>💭 {html.escape(preview)}</blockquote>")
                lines.append("")

            lines.append("<i>/admin history 20 | /admin history full</i>")
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:3950] + "\n\n... (用 /admin history 5 看更少)"
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)

        elif subcmd == "archived":
            try:
                limit = int(rest[0]) if rest and rest[0].isdigit() else 20
            except (ValueError, IndexError):
                limit = 20
            show_thinking = "full" in " ".join(rest)

            archived = self._store.get_archived(cid, limit=limit)
            if not archived:
                await update.message.reply_text("没有归档消息")
                return
            lines = [f"📦 <b>归档消息</b> ({len(archived)} 条)\n"]
            for msg in archived[-15:]:
                role = "👤" if msg["role"] == "user" else "🤖"
                content = msg["content"][:120]
                ts = msg.get("created_at", "")[:16]
                lines.append(f"{role} <i>{ts}</i>\n{html.escape(content)}")
                if show_thinking and msg.get("thinking"):
                    preview = msg["thinking"][:200]
                    lines.append(f"<blockquote expandable>💭 {html.escape(preview)}</blockquote>")
            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

        elif subcmd == "chats":
            chats = self._store.list_chats(include_archived=True)
            if not chats:
                await update.message.reply_text("没有聊天记录")
                return
            lines = ["📋 <b>All Chats</b>\n"]
            for c in chats[:15]:
                status = "📦" if c["archived"] else "💬"
                lines.append(
                    f"{status} {c['chat_id']} ({c['chat_type']}) — {c['message_count']} msgs"
                )
            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

        elif subcmd == "compact":
            # Force compact: halve the context if >50%, refuse if <30%
            _, _, cur_model = self._resolve_api()
            max_ctx = self._MODEL_CONTEXT.get(cur_model, 128000)
            active_count = self._store.count_messages(cid, include_archived=False)
            history = self._store.get_recent_history(cid, limit=200)
            used = self._estimate_history_tokens(history)
            pct = used / max_ctx

            if pct < 0.3:
                await update.message.reply_text(
                    f"✅ Context 只有 {pct:.0%}（{used:,}/{max_ctx:,}），不需要 compact",
                )
            elif active_count <= 2:
                await update.message.reply_text(
                    f"⚠️ 只有 {active_count} 条消息，无法再压缩",
                )
            else:
                # Target: halve current usage
                target_msgs = max(2, active_count // 2)
                archived, remaining = self._store.compact(cid, keep_recent=target_msgs)

                new_history = self._store.get_recent_history(cid, limit=200)
                new_used = self._estimate_history_tokens(new_history)
                new_pct = new_used / max_ctx

                await update.message.reply_text(
                    f"📦 <b>Compact 完成</b>\n\n"
                    f"归档: {archived} 条消息\n"
                    f"保留: {remaining} 条\n"
                    f"Tokens: {used:,} → {new_used:,} ({pct:.0%} → {new_pct:.0%})",
                    parse_mode=ParseMode.HTML,
                )

        elif subcmd == "purge":
            # Moved from standalone /purge command
            purge_args = " ".join(rest)
            if purge_args != "confirm":
                count = self._store.count_messages(cid, include_archived=True)
                await update.message.reply_text(
                    f"⚠️ 即将永久删除 <b>所有</b> 消息（{count} 条，含归档）\n"
                    f"此操作<b>不可恢复</b>！\n"
                    f"确认: <code>/admin purge confirm</code>",
                    parse_mode=ParseMode.HTML,
                )
            else:
                count = self._store.purge(cid)
                await update.message.reply_text(f"🔥 已永久删除 {count} 条消息")

        elif subcmd == "setctx":
            # Moved from standalone /setctx command
            val = rest[0] if rest else ""
            if not val:
                _, _, cur_model = self._resolve_api()
                current = self._MODEL_CONTEXT.get(cur_model, 128000)
                await update.message.reply_text(
                    f"当前 context 上限: <b>{current:,}</b> tokens\n"
                    f"<code>/admin setctx 2000</code> — 测试 compact\n"
                    f"<code>/admin setctx reset</code> — 恢复默认",
                    parse_mode=ParseMode.HTML,
                )
            elif val == "reset":
                self._MODEL_CONTEXT.update({
                    "deepseek-chat": 128000, "deepseek-reasoner": 128000,
                    "glm-5": 205000, "glm-4.5-flash": 128000,
                })
                await update.message.reply_text("✅ Context 上限已恢复默认值")
            else:
                try:
                    new_limit = int(val)
                    for m in list(self._MODEL_CONTEXT.keys()):
                        self._MODEL_CONTEXT[m] = new_limit
                    await update.message.reply_text(f"✅ Context 上限已设为 <b>{new_limit:,}</b>", parse_mode=ParseMode.HTML)
                except ValueError:
                    await update.message.reply_text("请输入数字")

        else:
            await update.message.reply_text(
                "📋 <b>Admin Panel</b>\n\n"
                "── 📜 查看 ──\n"
                "<code>/admin history</code> — 活跃消息\n"
                "<code>/admin history full</code> — 含思考过程\n"
                "<code>/admin archived</code> — 归档消息\n"
                "<code>/admin chats</code> — 所有聊天\n"
                "<code>/admin stats</code> — DB 统计\n"
                "\n── 🗑 清理 ──\n"
                "<code>/admin compact</code> — 强制压缩 (砍半, &gt;50%才可用)\n"
                "<code>/admin purge confirm</code> — 永久删除\n"
                "\n── 🔧 调试 ──\n"
                "<code>/admin setctx 2000</code> — 改 context 上限\n"
                "<code>/admin setctx reset</code> — 恢复默认\n"
                "\n<i>快捷: /history = /admin history</i>",
                parse_mode=ParseMode.HTML,
            )

    async def _cmd_context(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /context — show context window usage."""
        cid = update.message.chat_id
        history = self._store.get_recent_history(cid, limit=100)
        _, _, model = self._resolve_api(thinking=getattr(self, '_thinking_enabled', False))
        max_ctx = self._MODEL_CONTEXT.get(model, 128000)
        used = self._estimate_history_tokens(history)
        total_count = self._store.count_messages(cid, include_archived=True)
        active_count = self._store.count_messages(cid, include_archived=False)
        pct = used / max_ctx * 100

        if pct >= 80:
            bar = "🔴"
        elif pct >= 60:
            bar = "🟡"
        else:
            bar = "🟢"

        await update.message.reply_text(
            f"{bar} <b>Context Window</b>\n\n"
            f"Model: <code>{model}</code>\n"
            f"Active messages: {active_count} (total: {total_count})\n"
            f"Tokens: ~{used:,} / {max_ctx:,} ({pct:.0f}%)\n"
            f"Storage: SQLite (persistent)\n\n"
            f"{'⚠️ 接近上限，建议 /clear 归档' if pct >= 60 else '✅ 充足'}",
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_setctx(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Alias: /setctx → /admin setctx."""
        context.args = ["setctx"] + (list(context.args) if context.args else [])
        await self._cmd_admin(update, context)

    async def _cmd_hn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /hn — fetch Hacker News stories.

        /hn          — top 10
        /hn more     — next 10 (page 2, 3, ...)
        /hn best     — best stories
        /hn new      — newest
        /hn ask      — Ask HN
        /hn show     — Show HN
        /hn 20       — top 20
        /hn best 5   — best 5
        """
        from .hackernews import fetch_top_stories, format_stories_telegram

        args = list(context.args) if context.args else []
        cid = update.message.chat_id
        category = "top"
        limit = 10

        # Track pagination state per chat
        if not hasattr(self, '_hn_page'):
            self._hn_page = {}

        is_more = "more" in args or "下一页" in args or "next" in args

        for arg in args:
            if arg in ("top", "best", "new", "ask", "show", "job"):
                category = arg
            elif arg.isdigit():
                limit = min(int(arg), 30)

        if is_more:
            # Increment page
            prev = self._hn_page.get(cid, {"category": category, "offset": 0})
            category = prev["category"]
            offset = prev["offset"] + limit
        else:
            offset = 0

        self._hn_page[cid] = {"category": category, "offset": offset}

        await update.message.chat.send_action(ChatAction.TYPING)

        # Fetch extra stories and slice for pagination
        stories = await fetch_top_stories(category=category, limit=offset + limit, min_score=0)
        page_stories = stories[offset:offset + limit]

        if not page_stories and offset > 0:
            await update.message.reply_text("没有更多了，已经到底了 🏁")
            self._hn_page[cid] = {"category": category, "offset": 0}
            return

        page_num = (offset // limit) + 1
        title = f"Hacker News ({category}) · 第 {page_num} 页" if page_num > 1 else f"Hacker News ({category})"
        text = format_stories_telegram(page_stories, title=title)

        await self._send_long_message(update.message, text)

    async def _cmd_subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /subscribe — manage auto-push subscriptions for this chat.

        /subscribe hn          — subscribe to HN push (every 4 hours, top 5, score≥100)
        /subscribe hn off      — unsubscribe
        /subscribe hn 2h       — push every 2 hours
        /subscribe hn 50       — min score 50
        /subscribe             — show current subscriptions
        """
        cid = update.message.chat_id
        args = list(context.args) if context.args else []

        # Load subscriptions from DB
        subs = self._load_subscriptions()

        if not args:
            # Show current subscriptions
            chat_subs = subs.get(str(cid), {})
            if not chat_subs:
                await update.message.reply_text(
                    "没有订阅。\n\n"
                    "<code>/subscribe hn</code> — 订阅 Hacker News 推送\n"
                    "<code>/subscribe hn off</code> — 取消",
                    parse_mode=ParseMode.HTML,
                )
            else:
                lines = ["📡 <b>当前订阅</b>\n"]
                for source, cfg in chat_subs.items():
                    if cfg.get("enabled"):
                        interval = cfg.get("interval_hours", 4)
                        min_score = cfg.get("min_score", 100)
                        lines.append(f"🔶 {source}: 每 {interval}h, 最低分 {min_score}")
                await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
            return

        source = args[0].lower()
        if source != "hn":
            await update.message.reply_text("目前支持: <code>/subscribe hn</code>", parse_mode=ParseMode.HTML)
            return

        # Check for off/unsubscribe
        if len(args) > 1 and args[1] in ("off", "stop", "cancel", "取消"):
            subs.setdefault(str(cid), {}).pop("hn", None)
            self._save_subscriptions(subs)
            await update.message.reply_text("🔕 已取消 HN 推送")
            return

        # Parse optional params
        interval_hours = 4
        min_score = 100
        for arg in args[1:]:
            if arg.endswith("h") and arg[:-1].isdigit():
                interval_hours = max(1, int(arg[:-1]))
            elif arg.isdigit():
                min_score = int(arg)

        subs.setdefault(str(cid), {})["hn"] = {
            "enabled": True,
            "interval_hours": interval_hours,
            "min_score": min_score,
            "limit": 5,
            "last_push": 0,
            "pushed_ids": [],  # track to avoid duplicates
        }
        self._save_subscriptions(subs)

        await update.message.reply_text(
            f"🔔 已订阅 Hacker News 推送\n\n"
            f"频率: 每 {interval_hours} 小时\n"
            f"最低分: {min_score}\n"
            f"每次: 5 条\n\n"
            f"<code>/subscribe hn off</code> 取消\n"
            f"<code>/hn</code> 立即查看",
            parse_mode=ParseMode.HTML,
        )

    # ── Subscription Storage ─────────────────────────────────────

    def _load_subscriptions(self) -> dict:
        """Load subscriptions from a JSON file in the data dir."""
        sub_path = Path(os.getenv("HOME", "/data")) / ".neomind" / "subscriptions.json"
        try:
            if sub_path.exists():
                return json.loads(sub_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Try backup
            bak = sub_path.with_suffix(".json.bak")
            if bak.exists():
                try:
                    return json.loads(bak.read_text(encoding="utf-8"))
                except Exception:
                    pass
        except Exception:
            pass
        return {}

    def _save_subscriptions(self, subs: dict):
        """Save subscriptions atomically (write .tmp → rename)."""
        sub_path = Path(os.getenv("HOME", "/data")) / ".neomind" / "subscriptions.json"
        try:
            sub_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = sub_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(subs, indent=2), encoding="utf-8")
            tmp.rename(sub_path)
        except Exception:
            pass

    # ── Background Scheduler ─────────────────────────────────────

    async def _scheduler_loop(self):
        """Background loop that checks subscriptions and pushes content."""
        await asyncio.sleep(30)  # wait 30s after startup before first check
        print("[bot] Scheduler started", flush=True)

        while True:
            try:
                await self._process_subscriptions()
            except Exception as e:
                print(f"[bot] Scheduler error: {e}", flush=True)
            await asyncio.sleep(300)  # check every 5 minutes

    async def _process_subscriptions(self):
        """Check all subscriptions and push if interval elapsed."""
        from .hackernews import fetch_top_stories, format_stories_telegram

        subs = self._load_subscriptions()
        now = time.time()
        changed = False

        for chat_id_str, chat_subs in subs.items():
            chat_id = int(chat_id_str)

            # HN subscription
            hn = chat_subs.get("hn", {})
            if not hn.get("enabled"):
                continue

            interval = hn.get("interval_hours", 4) * 3600
            last_push = hn.get("last_push", 0)

            if now - last_push < interval:
                continue  # not time yet

            # Time to push!
            min_score = hn.get("min_score", 100)
            limit = hn.get("limit", 5)
            pushed_ids = set(hn.get("pushed_ids", [])[-200:])  # keep last 200

            stories = await fetch_top_stories(category="top", limit=limit * 3, min_score=min_score)

            # Filter out already-pushed stories
            new_stories = [s for s in stories if s.id not in pushed_ids][:limit]

            if new_stories:
                text = format_stories_telegram(new_stories, title="Hacker News 推送")
                try:
                    await self._app.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    # Update state
                    hn["last_push"] = now
                    for s in new_stories:
                        pushed_ids.add(s.id)
                    hn["pushed_ids"] = list(pushed_ids)[-200:]
                    changed = True
                    print(f"[bot] Pushed {len(new_stories)} HN stories to {chat_id}", flush=True)
                except Exception as e:
                    print(f"[bot] Failed to push HN to {chat_id}: {e}", flush=True)

        if changed:
            self._save_subscriptions(subs)

    async def _cmd_usage(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /usage — show LLM usage statistics."""
        args = " ".join(context.args).lower() if context.args else ""

        if args in ("week", "7d"):
            data = self._usage.get_range(7)
            period = "最近 7 天"
        elif args in ("month", "30d"):
            data = self._usage.get_range(30)
            period = "最近 30 天"
        else:
            data = self._usage.get_today()
            period = "今日"

        model_lines = "\n".join(
            f"  {m}: {c} 次" for m, c in data["by_model"].items()
        ) if data["by_model"] else "  无"

        cost_str = f"${data['cost']:.4f}" if data["cost"] > 0 else "$0 (本地模型)"

        error_lines = ""
        if data["recent_errors"]:
            error_lines = "\n\n⚠️ 最近错误:\n" + "\n".join(
                f"  • {e[:60]}" for e in data["recent_errors"]
            )

        await update.message.reply_text(
            f"📊 <b>LLM 用量 ({period})</b>\n\n"
            f"调用: {data['calls']} 次 (成功 {data['success']}, 失败 {data['failed']})\n"
            f"Tokens: ~{data['tokens']:,}\n"
            f"费用: {cost_str}\n"
            f"平均延迟: {data['avg_latency_ms']}ms\n\n"
            f"模型分布:\n{model_lines}"
            f"{error_lines}\n\n"
            f"<i>/usage week — 7天 | /usage month — 30天</i>",
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_provider(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /provider — show or switch LLM provider.

        /provider          — show current provider chain (reads from state file)
        /provider litellm  — switch to LiteLLM (writes to state file)
        /provider direct   — switch to direct API (writes to state file)

        State file is shared with xbar — changes here are visible on macOS menu bar.
        """
        args = " ".join(context.args).lower() if context.args else ""

        if not args:
            # Build status with resolved model names
            config = self._state_mgr.get_bot_config("neomind")
            mode = config.get("provider_mode", "direct")
            chain = self._get_provider_chain(thinking=False)

            lines = [f"🔌 <b>LLM Provider (neomind)</b>\n"]
            lines.append(f"Mode: <b>{mode}</b>")
            lines.append(f"Updated: {config.get('updated_at', '?')} by {config.get('updated_by', '?')}\n")

            lines.append("Provider chain:")
            for i, p in enumerate(chain):
                arrow = "▶" if i == 0 else "→"
                actual = self._resolve_litellm_model(p['model']) if p['name'] == 'litellm' else p['model']
                lines.append(f"  {arrow} {p['name']}: <code>{actual}</code>")

            state = self._state_mgr._read_state()
            litellm_info = state.get("litellm", {})
            health = "🟢" if litellm_info.get("health_ok") else "🔴"
            lines.append(f"\nLiteLLM: {health} {litellm_info.get('base_url', '?')}")

            if mode == "litellm":
                chat_actual = self._resolve_litellm_model(config.get('litellm_model', 'local'))
                think_actual = self._resolve_litellm_model(config.get('thinking_model', 'deepseek-reasoner'))
                lines.append(f"\n普通对话: <b>{chat_actual}</b> (Ollama, 免费)")
                lines.append(f"Thinking: <b>{think_actual}</b>")

            lines.append(
                f"\n<code>/provider litellm</code> — 本地 Ollama\n"
                f"<code>/provider direct</code> — 直连 API"
            )

            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

        elif args in ("litellm", "local", "ollama"):
            # Check if LITELLM_API_KEY is set
            if not os.getenv("LITELLM_API_KEY", ""):
                await update.message.reply_text(
                    "⚠️ LITELLM_API_KEY 未设置，无法启用。\n"
                    "在 .env 里加上 LITELLM_API_KEY=你的key"
                )
                return

            config = self._state_mgr.set_provider_mode(
                "neomind", "litellm", updated_by="telegram"
            )
            new_chain = self._get_provider_chain(thinking=False)
            models = [
                f"{p['name']}:{self._resolve_litellm_model(p['model']) if p['name'] == 'litellm' else p['model']}"
                for p in new_chain
            ]

            # Resolve alias → actual model name via LiteLLM API
            chat_alias = config.get('litellm_model', 'local')
            think_alias = config.get('thinking_model', 'deepseek-reasoner')
            chat_actual = self._resolve_litellm_model(chat_alias)
            think_actual = self._resolve_litellm_model(think_alias)

            await update.message.reply_text(
                f"✅ LiteLLM 已启用\n"
                f"Chain: {' → '.join(models)}\n\n"
                f"普通对话: {chat_actual} (Ollama, 免费)\n"
                f"Thinking: {think_actual}\n\n"
                f"<i>此更改已同步到 xbar 菜单栏</i>",
                parse_mode=ParseMode.HTML,
            )

        elif args in ("direct", "off", "disable"):
            config = self._state_mgr.set_provider_mode(
                "neomind", "direct", updated_by="telegram"
            )
            new_chain = self._get_provider_chain(thinking=False)
            models = [
                f"{p['name']}:{self._resolve_litellm_model(p['model']) if p['name'] == 'litellm' else p['model']}"
                for p in new_chain
            ]
            await update.message.reply_text(
                f"✅ 已切换到直连 API\n"
                f"Chain: {' → '.join(models)}\n\n"
                f"<i>此更改已同步到 xbar 菜单栏</i>",
                parse_mode=ParseMode.HTML,
            )

        else:
            await update.message.reply_text(
                "用法: <code>/provider litellm</code> | <code>/provider direct</code>",
                parse_mode=ParseMode.HTML,
            )

    async def _cmd_skills(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /skills — list available skills for this chat's mode."""
        from agent.skills import get_skill_loader
        cid = update.message.chat_id
        mode = self._store.get_mode(cid)
        loader = get_skill_loader()

        args = " ".join(context.args) if context.args else ""
        if args:
            # Show specific skill detail
            skill = loader.get(args)
            if skill:
                await update.message.reply_text(
                    f"<b>/{skill.name}</b> — {skill.description}\n"
                    f"Modes: {', '.join(skill.modes)} | v{skill.version}\n\n"
                    f"<blockquote expandable>{html.escape(skill.body[:800])}</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await update.message.reply_text(f"Skill not found: {args}")
        else:
            output = loader.format_skill_list(mode=mode)
            await update.message.reply_text(
                f"<b>Skills (mode: {mode})</b>\n<pre>{html.escape(output)}</pre>",
                parse_mode=ParseMode.HTML,
            )

    async def _cmd_careful(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /careful — toggle safety guard."""
        from agent.workflow.guards import get_guard
        guard = get_guard()
        if guard.state.careful_enabled:
            guard.disable_careful()
            await update.message.reply_text("⚪ Careful mode OFF")
        else:
            guard.enable_careful()
            await update.message.reply_text("🛑 Careful mode ON — will warn before destructive operations")

    async def _cmd_sprint(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /sprint — structured task workflow."""
        from agent.workflow.sprint import SprintManager
        cid = update.message.chat_id
        mode = self._store.get_mode(cid)
        args = list(context.args) if context.args else []
        # Singleton — persist across commands
        if not hasattr(self, '_sprint_mgr'):
            self._sprint_mgr = SprintManager()
        mgr = self._sprint_mgr

        if not args:
            await update.message.reply_text(
                "<b>Sprint</b> — structured task workflow\n\n"
                "<code>/sprint new Buy AAPL</code> — create sprint\n"
                "<code>/sprint status</code> — show progress\n"
                "<code>/sprint next</code> — advance to next phase\n"
                "<code>/sprint skip</code> — skip current phase",
                parse_mode=ParseMode.HTML,
            )
            return

        subcmd = args[0]
        if subcmd == "new" and len(args) > 1:
            goal = " ".join(args[1:])
            sprint = mgr.create(goal, mode=mode)
            await update.message.reply_text(
                f"✅ Sprint: {sprint.id}\n\n{mgr.format_status(sprint.id)}"
            )
        elif subcmd == "status":
            found = False
            for sid in mgr._active_sprints:
                await update.message.reply_text(mgr.format_status(sid))
                found = True
            if not found:
                await update.message.reply_text("No active sprints. /sprint new [goal]")
        elif subcmd == "next":
            for sid in list(mgr._active_sprints.keys()):
                phase = mgr.advance(sid)
                if phase:
                    await update.message.reply_text(f"▶️ Now: <b>{phase.name}</b>", parse_mode=ParseMode.HTML)
                else:
                    await update.message.reply_text("✅ Sprint completed!")
                break
        elif subcmd == "skip":
            for sid in list(mgr._active_sprints.keys()):
                phase = mgr.skip_phase(sid)
                if phase:
                    await update.message.reply_text(f"⏭️ Skipped → <b>{phase.name}</b>", parse_mode=ParseMode.HTML)
                break

    async def _cmd_evidence(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /evidence — view audit trail."""
        from agent.workflow.evidence import get_evidence_trail
        trail = get_evidence_trail()
        args = " ".join(context.args) if context.args else ""

        if args == "stats":
            stats = trail.get_stats()
            await update.message.reply_text(
                f"📋 <b>Evidence Trail</b>\n\n"
                f"Total entries: {stats.get('total', 0)}\n"
                f"Log size: {stats.get('log_size_kb', 0)} KB\n"
                f"By action: {stats.get('by_action', {})}",
                parse_mode=ParseMode.HTML,
            )
        else:
            output = trail.format_recent(10)
            await update.message.reply_text(output)

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

        # 0. Check for remote provider change (xbar → bot sync)
        change_notice = self._state_mgr.detect_external_change("neomind")
        if change_notice:
            await msg.reply_text(change_notice, parse_mode=ParseMode.HTML)

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

        # 2. Everything else → send to DeepSeek LLM (always streaming)
        thinking = getattr(self, '_thinking_enabled', False)
        self._last_compact_notice = None
        cid = msg.chat_id
        ctype = msg.chat.type or "private"

        if thinking:
            await self._ask_llm_streaming(msg, text, chat_id=cid, chat_type=ctype)
        else:
            await self._ask_llm_stream_normal(msg, text, chat_id=cid, chat_type=ctype)

        # Send context notice
        notice = getattr(self, '_last_compact_notice', None)
        if notice:
            await msg.reply_text(notice)
            self._last_compact_notice = None

        # Post-response check
        _, _, cur_model = self._resolve_api(thinking=thinking)
        post_notice = self._auto_compact_if_needed_db(cid, cur_model)
        if post_notice and "Auto-compacted" in post_notice:
            await msg.reply_text(post_notice)

    # ── LLM Shared Helpers ──────────────────────────────────────────

    def _get_system_prompt(self, chat_id: int = 0) -> str:
        """Load the full system prompt from YAML config for the chat's mode.

        Uses the same first-principles prompts as the CLI — not a simplified version.
        Appends Telegram-specific instructions at the end.
        """
        current_mode = self._store.get_mode(chat_id) if chat_id else "fin"

        # Load from YAML config (same prompts CLI uses)
        try:
            from agent_config import AgentConfigManager
            cfg = AgentConfigManager(mode=current_mode)
            base_prompt = cfg.system_prompt or ""
        except Exception:
            base_prompt = ""

        # Append Telegram-specific context
        telegram_context = (
            "\n\nTELEGRAM CONTEXT:\n"
            "你在 Telegram 上运行。回复简洁但有深度。"
            "回复用用户的语言（中文问中文答，英文问英文答）。"
            "如果用户只是打招呼或闲聊，正常回复，不要强行推荐命令。"
            "用户可以用 /help 查看命令列表。"
        )

        return base_prompt + telegram_context

    # Context window limits per model
    _MODEL_CONTEXT = {
        "deepseek-chat": 128000,
        "deepseek-reasoner": 128000,
        "glm-5": 205000,
        "glm-4.5-flash": 128000,
    }

    def _get_history(self, chat_id: int = 0) -> list:
        """Get recent history from SQLite for a specific chat.

        Returns a mutable list (callers may modify for compact).
        """
        return self._store.get_recent_history(chat_id, limit=20)

    def _resolve_api(self, thinking: bool = False) -> tuple:
        """Returns (api_key, base_url, model) — picks first available provider."""
        chain = self._get_provider_chain(thinking)
        if chain:
            p = chain[0]
            return p["api_key"], p["base_url"], p["model"]
        return "", "", ""

    def _get_provider_chain(self, thinking: bool = False) -> list:
        """Build ordered list of providers to try (primary → fallback).

        Delegates to ProviderStateManager which reads mode from
        provider-state.json and API keys from os.environ.
        """
        return self._state_mgr.get_provider_chain("neomind", thinking=thinking)

    def _resolve_litellm_model(self, alias: str) -> str:
        """Resolve a LiteLLM model alias (e.g. 'local') to the actual model
        (e.g. 'ollama_chat/qwen3:14b') by querying the LiteLLM /model/info endpoint.
        Falls back to the alias itself on any error.
        """
        try:
            import requests as req
            state = self._state_mgr._read_state()
            base = state.get("litellm", {}).get(
                "base_url",
                os.getenv("LITELLM_BASE_URL", "http://host.docker.internal:4000/v1")
            )
            # Strip /v1 suffix to get base URL for /model/info
            api_base = base.rstrip("/").removesuffix("/v1")
            key = os.getenv("LITELLM_API_KEY", "")
            resp = req.get(
                f"{api_base}/v1/model/info",
                headers={"Authorization": f"Bearer {key}"},
                timeout=3,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                for m in data:
                    if m.get("model_name") == alias:
                        # Always use litellm_params.model — the configured model string
                        return m.get("litellm_params", {}).get("model", alias)
        except Exception:
            pass
        return alias

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate: ~1.5 tokens per Chinese char, ~0.75 per English word."""
        cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        en_words = len(re.findall(r'[a-zA-Z]+', text))
        return int(cn_chars * 1.5 + en_words * 0.75 + len(text) * 0.1)

    def _estimate_history_tokens(self, history: list) -> int:
        """Estimate total tokens in conversation history."""
        total = 0
        for msg in history:
            total += self._estimate_tokens(msg.get("content", "")) + 4  # msg overhead
        return total

    def _auto_compact_if_needed_db(self, chat_id: int, model: str) -> Optional[str]:
        """DB-backed version of auto-compact. Archives old messages in SQLite."""
        max_ctx = self._MODEL_CONTEXT.get(model, 128000)
        history = self._store.get_recent_history(chat_id, limit=100)
        used = self._estimate_history_tokens(history)
        pct = used / max_ctx

        if pct >= 0.9 and len(history) > 4:
            target_tokens = int(max_ctx * 0.3)
            # Figure out how many recent messages to keep
            keep = len(history)
            running = 0
            for i in range(len(history) - 1, -1, -1):
                running += self._estimate_tokens(history[i].get("content", "")) + 4
                if running > target_tokens:
                    keep = len(history) - i - 1
                    break

            keep = max(keep, 2)  # always keep at least 2
            archived, remaining = self._store.compact(chat_id, keep_recent=keep)
            if archived > 0:
                new_used = self._estimate_history_tokens(
                    self._store.get_recent_history(chat_id, limit=100)
                )
                return (
                    f"📦 Auto-compacted: archived {archived} msgs, "
                    f"kept {remaining}, ~{new_used:,}/{max_ctx:,} tokens"
                )

        if pct >= 0.6:
            return f"⚠️ Context: {pct:.0%} ({used:,}/{max_ctx:,}). 接近上限，发 /clear 清空"

        return None

    # ── Normal mode: simple non-streaming call ───────────────────

    async def _ask_llm(self, user_message: str, chat_id: int = 0,
                       chat_type: str = "private") -> Optional[str]:
        """Non-streaming LLM call with auto-fallback between providers."""
        import requests as req

        # Save user message to persistent store
        self._store.add_message(chat_id, "user", user_message, chat_type)

        # Load recent history from DB
        history = self._store.get_recent_history(chat_id, limit=20)

        # Context management
        api_key, base_url, model = self._resolve_api(thinking=False)
        compact_notice = self._auto_compact_if_needed_db(chat_id, model)

        messages = [{"role": "system", "content": self._get_system_prompt(chat_id)}] + history

        if not api_key:
            return "⚠️ No API key configured (DEEPSEEK_API_KEY or ZAI_API_KEY)"

        # Build provider chain: primary → fallback
        providers = self._get_provider_chain(thinking=False)

        errors = []
        for provider in providers:
            try:
                print(f"[llm] Trying {provider['name']}:{provider['model']} → {provider['base_url'][:50]}", flush=True)
                loop = asyncio.get_event_loop()
                # Longer timeout for longer generation (4096 tokens ≈ 20-40s)
                timeout = 90 if provider["name"] == "litellm" else 60
                t_start = time.time()
                response = await loop.run_in_executor(None, lambda p=provider, t=timeout: req.post(
                    p["base_url"],
                    headers={"Authorization": f"Bearer {p['api_key']}", "Content-Type": "application/json"},
                    json={"model": p["model"], "messages": messages, "max_tokens": 4096, "temperature": 0.7, "stream": False},
                    timeout=t,
                ))
                latency = int((time.time() - t_start) * 1000)

                if response.status_code == 200:
                    reply = response.json()["choices"][0]["message"]["content"].strip()
                    tokens_est = len(reply) * 2  # rough: 1 char ≈ 2 tokens for CJK
                    print(f"[llm] ✅ {provider['name']}:{provider['model']} responded ({len(reply)} chars, {latency}ms)", flush=True)

                    # Track usage
                    self._usage.record(
                        provider=provider["name"], model=provider["model"],
                        tokens=tokens_est, latency_ms=latency,
                        success=True, chat_id=chat_id,
                    )

                    self._store.add_message(chat_id, "assistant", reply, chat_type)
                    self._last_compact_notice = compact_notice
                    if provider != providers[0]:
                        reply += f"\n\n<i>⚡ via {provider['model']} (primary unavailable)</i>"
                    return reply

                err_detail = f"{provider['name']}:{provider['model']} HTTP {response.status_code}"
                try:
                    err_body = response.json().get("error", {}).get("message", "")[:80]
                    if err_body:
                        err_detail += f" — {err_body}"
                except Exception:
                    pass
                print(f"[llm] ❌ {err_detail}", flush=True)
                errors.append(err_detail)
                self._usage.record(
                    provider=provider["name"], model=provider["model"],
                    latency_ms=int((time.time() - t_start) * 1000),
                    success=False, chat_id=chat_id, error=f"HTTP {response.status_code}",
                )
                continue
            except req.exceptions.Timeout:
                err_msg = f"{provider['name']}:{provider['model']} timeout ({timeout}s)"
                print(f"[llm] ⏱️ {err_msg}", flush=True)
                errors.append(err_msg)
                self._usage.record(
                    provider=provider["name"], model=provider["model"],
                    success=False, chat_id=chat_id, error="timeout",
                )
                continue
            except req.exceptions.ConnectionError as e:
                err_msg = f"{provider['name']} connection failed"
                print(f"[llm] 🔌 {err_msg}: {e}", flush=True)
                errors.append(err_msg)
                self._usage.record(
                    provider=provider["name"], model=provider["model"],
                    success=False, chat_id=chat_id, error=str(e)[:100],
                )
                continue
            except Exception as e:
                err_msg = f"{provider['name']} error: {type(e).__name__}"
                print(f"[llm] ❌ {err_msg}: {e}", flush=True)
                errors.append(err_msg)
                self._usage.record(
                    provider=provider["name"], model=provider["model"],
                    success=False, chat_id=chat_id, error=str(e)[:100],
                )
                continue

        # Show specific error so user knows what went wrong
        err_summary = "\n".join(f"• {e}" for e in errors) if errors else "未知错误"
        return f"⚠️ 所有 API 均失败:\n{err_summary}\n\n<i>/provider 查看配置 · /usage 查看统计</i>"

    # ── Normal streaming: live message updates without thinking ────

    async def _ask_llm_stream_normal(self, msg, user_message: str,
                                     chat_id: int = 0, chat_type: str = "private"):
        """Streaming LLM call for normal mode — edits message in-place as tokens arrive.

        Flow:
        1. Send placeholder "💭..."
        2. Stream tokens, edit the message every ~1.5s
        3. Final edit with complete text
        4. If text exceeds 4096 chars, stop editing and send remaining as new message(s)
        """
        import requests as req

        # Save user message to persistent store
        self._store.add_message(chat_id, "user", user_message, chat_type)

        # Load recent history from DB
        history = self._store.get_recent_history(chat_id, limit=20)

        # Context management
        providers = self._get_provider_chain(thinking=False)
        if not providers:
            await msg.reply_text("⚠️ No API key configured")
            return

        model = providers[0]["model"]
        compact_notice = self._auto_compact_if_needed_db(chat_id, model)
        messages = [{"role": "system", "content": self._get_system_prompt(chat_id)}] + history

        if compact_notice:
            self._last_compact_notice = compact_notice

        # Send placeholder
        live_msg = await msg.reply_text("💭 ...")

        response_text = ""
        last_edit_time = 0
        EDIT_INTERVAL = 1.5  # Telegram allows ~30 edits/min, this stays well under

        try:
            # Try providers in order
            response = None
            used_provider = None
            for provider in providers:
                try:
                    response = await asyncio.get_event_loop().run_in_executor(
                        None, lambda p=provider: req.post(
                            p["base_url"],
                            headers={"Authorization": f"Bearer {p['api_key']}",
                                     "Content-Type": "application/json"},
                            json={"model": p["model"], "messages": messages,
                                  "max_tokens": 4096, "temperature": 0.7, "stream": True},
                            timeout=90,
                            stream=True,
                        ))
                    if response.status_code == 200:
                        used_provider = provider
                        break
                    else:
                        print(f"[llm-stream] ❌ {provider['name']} returned {response.status_code}", flush=True)
                except Exception as e:
                    print(f"[llm-stream] ❌ {provider['name']} error: {e}", flush=True)
                    continue

            if not response or response.status_code != 200:
                status = response.status_code if response else "all failed"
                await live_msg.edit_text(f"⚠️ API error: {status}")
                return

            # Process SSE stream
            t_start = time.time()
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
                    ct = delta.get("content", "")
                    if ct:
                        response_text += ct

                    # Periodically edit the live message
                    now = asyncio.get_event_loop().time()
                    if ct and (now - last_edit_time) >= EDIT_INTERVAL:
                        last_edit_time = now
                        # Only edit if within Telegram's limit
                        display = response_text
                        if len(display) > 3900:
                            # Approaching limit — stop editing, will send rest as new msg
                            break
                        display = self._md_to_html(display)
                        try:
                            await live_msg.edit_text(
                                display + " ▍",
                                parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True,
                            )
                        except Exception:
                            pass  # Telegram rate limit, skip this update

                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

            # Drain remaining tokens if we broke out early due to length
            if response_text and len(response_text) <= 3900:
                pass  # already got everything
            else:
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
                        ct = delta.get("content", "")
                        if ct:
                            response_text += ct
                    except Exception:
                        continue

            latency = int((time.time() - t_start) * 1000)

            if response_text.strip():
                # Track usage
                if used_provider:
                    self._usage.record(
                        provider=used_provider["name"], model=used_provider["model"],
                        tokens=len(response_text) * 2, latency_ms=latency,
                        success=True, chat_id=chat_id,
                    )
                    print(f"[llm-stream] ✅ {used_provider['name']}:{used_provider['model']} "
                          f"({len(response_text)} chars, {latency}ms)", flush=True)

                self._store.add_message(chat_id, "assistant", response_text.strip(), chat_type)

                # Final update: edit the live message with complete text
                final_html = self._md_to_html(response_text.strip())
                if len(final_html) <= self.config.max_message_length:
                    try:
                        await live_msg.edit_text(
                            final_html,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )
                    except Exception:
                        try:
                            await live_msg.edit_text(
                                re.sub(r'<[^>]+>', '', final_html),
                                disable_web_page_preview=True,
                            )
                        except Exception:
                            pass
                else:
                    # Text exceeds one message — edit first chunk, send rest as new messages
                    chunks = self._split_message(final_html)
                    try:
                        await live_msg.edit_text(
                            chunks[0],
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )
                    except Exception:
                        await live_msg.edit_text(
                            re.sub(r'<[^>]+>', '', chunks[0]),
                            disable_web_page_preview=True,
                        )
                    for i, chunk in enumerate(chunks[1:], 1):
                        await asyncio.sleep(0.5)
                        try:
                            await msg.reply_text(chunk, parse_mode=ParseMode.HTML,
                                                 disable_web_page_preview=True)
                        except Exception:
                            await msg.reply_text(
                                re.sub(r'<[^>]+>', '', chunk),
                                disable_web_page_preview=True,
                            )
            else:
                await live_msg.edit_text("⚠️ LLM 未生成回复")

        except Exception as e:
            logger.error(f"Stream error: {e}")
            try:
                await live_msg.edit_text(f"⚠️ Error: {e}")
            except Exception:
                await msg.reply_text(f"⚠️ Error: {e}")

    # ── Thinking mode: streaming with live Telegram message updates ──

    async def _ask_llm_streaming(self, msg, user_message: str,
                                 chat_id: int = 0, chat_type: str = "private"):
        """Streaming LLM call with thinking. Used when /think is ON."""
        import requests as req

        # Save user message to persistent store
        self._store.add_message(chat_id, "user", user_message, chat_type)

        # Load recent history from DB
        history = self._store.get_recent_history(chat_id, limit=20)

        # Context management
        providers = self._get_provider_chain(thinking=True)
        if not providers:
            await msg.reply_text("⚠️ No API key configured")
            return

        model = providers[0]["model"]
        compact_notice = self._auto_compact_if_needed_db(chat_id, model)
        messages = [{"role": "system", "content": self._get_system_prompt(chat_id)}] + history

        # Show compact notice if triggered
        if compact_notice:
            await msg.reply_text(compact_notice)

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
            # Step 2: Stream the response (try providers in order)
            response = None
            used_provider = None
            for provider in providers:
                try:
                    response = await asyncio.get_event_loop().run_in_executor(None, lambda p=provider: req.post(
                        p["base_url"],
                        headers={"Authorization": f"Bearer {p['api_key']}", "Content-Type": "application/json"},
                        json={"model": p["model"], "messages": messages, "max_tokens": 4096, "stream": True},
                        timeout=120,
                        stream=True,
                    ))
                    if response.status_code == 200:
                        used_provider = provider
                        break
                except Exception:
                    continue  # try next provider

            if not response or response.status_code != 200:
                status = response.status_code if response else "all timed out"
                await thinking_msg.edit_text(f"⚠️ API error: {status}")
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
                self._store.add_message(
                    chat_id, "assistant", response_text.strip(), chat_type,
                    thinking=thinking_text,
                )
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
        """Send a message, splitting if it exceeds Telegram's 4096 char limit.

        - Converts markdown to Telegram HTML (with proper escaping)
        - Splits long messages at safe boundaries
        - Falls back to plain text per-chunk if HTML fails
        - Adds small delay between chunks to avoid Telegram rate limits
        """
        # Convert markdown-style links to HTML
        text = self._md_to_html(text)

        if len(text) <= self.config.max_message_length:
            try:
                await msg.reply_text(text, parse_mode=ParseMode.HTML,
                                     disable_web_page_preview=True)
            except Exception as e:
                logger.warning(f"HTML send failed ({e}), retrying as plain text")
                # Fallback: send without formatting
                plain = re.sub(r'<[^>]+>', '', text)
                await msg.reply_text(plain, disable_web_page_preview=True)
        else:
            # Split into chunks
            chunks = self._split_message(text)
            for i, chunk in enumerate(chunks):
                try:
                    await msg.reply_text(chunk, parse_mode=ParseMode.HTML,
                                         disable_web_page_preview=True)
                except Exception as e:
                    logger.warning(f"HTML chunk {i+1}/{len(chunks)} failed ({e}), sending plain")
                    plain = re.sub(r'<[^>]+>', '', chunk)
                    await msg.reply_text(plain, disable_web_page_preview=True)
                # Small delay between chunks to respect Telegram rate limits
                if i < len(chunks) - 1:
                    await asyncio.sleep(0.5)

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
        """Convert simple markdown to Telegram HTML.

        Strategy: extract markdown tokens first, escape everything else,
        then re-insert the HTML tags. This prevents raw <, >, & in LLM
        output from breaking Telegram's HTML parser.
        """
        # Step 1: Extract code blocks and inline code BEFORE escaping
        # so their contents stay literal.
        code_blocks = []
        def _save_code_block(m):
            code_blocks.append(m.group(1))
            return f"\x00CB{len(code_blocks)-1}\x00"
        # ```...``` fenced code blocks
        text = re.sub(r'```(?:\w*\n)?(.*?)```', _save_code_block, text, flags=re.DOTALL)

        inline_codes = []
        def _save_inline_code(m):
            inline_codes.append(m.group(1))
            return f"\x00IC{len(inline_codes)-1}\x00"
        text = re.sub(r'`([^`]+?)`', _save_inline_code, text)

        # Step 2: Extract markdown links before escaping
        links = []
        def _save_link(m):
            links.append((m.group(1), m.group(2)))
            return f"\x00LK{len(links)-1}\x00"
        text = re.sub(r'\[([^\]]+?)\]\(([^)]+?)\)', _save_link, text)

        # Step 3: Escape HTML entities in the remaining text
        text = html.escape(text)

        # Step 4: Convert markdown formatting to HTML
        # Bold: **text** → <b>text</b>
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        # Italic: _text_ → <i>text</i>  (but not in URLs / underscored_words)
        text = re.sub(r'(?<!\w)_([^_]+?)_(?!\w)', r'<i>\1</i>', text)

        # Step 5: Restore extracted tokens with proper HTML
        for i, (link_text, url) in enumerate(links):
            text = text.replace(f"\x00LK{i}\x00",
                                f'<a href="{html.escape(url)}">{html.escape(link_text)}</a>')
        for i, code in enumerate(inline_codes):
            text = text.replace(f"\x00IC{i}\x00", f'<code>{html.escape(code)}</code>')
        for i, code in enumerate(code_blocks):
            text = text.replace(f"\x00CB{i}\x00", f'<pre>{html.escape(code)}</pre>')

        return text

    @staticmethod
    def _split_message(text: str, max_len: int = 4096) -> List[str]:
        """Split a long message into chunks at safe boundaries.

        Respects:
        - Paragraph / line breaks as preferred split points
        - HTML tag boundaries (won't cut inside <a href="...">, <b>, etc.)
        - Closes any open tags at chunk end and re-opens them at next chunk start
        """
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
                # Last resort: split at space boundary
                split_at = text.rfind(" ", 0, max_len)
            if split_at == -1:
                split_at = max_len

            # Safety: don't split inside an HTML tag (< ... >)
            # Check if we're inside an unclosed '<'
            chunk_candidate = text[:split_at]
            last_open = chunk_candidate.rfind("<")
            last_close = chunk_candidate.rfind(">")
            if last_open > last_close:
                # We're inside a tag — move split point before the tag
                split_at = last_open

            chunk = text[:split_at]

            # Close any open HTML tags in this chunk and re-open in next
            open_tags = re.findall(r'<(b|i|code|pre|a|blockquote)\b[^>]*>', chunk)
            close_tags = re.findall(r'</(b|i|code|pre|a|blockquote)>', chunk)
            # Track net open tags
            tag_stack = []
            for tag in open_tags:
                tag_stack.append(tag)
            for tag in close_tags:
                if tag_stack and tag_stack[-1] == tag:
                    tag_stack.pop()

            # Close unclosed tags at chunk end
            if tag_stack:
                for tag in reversed(tag_stack):
                    chunk += f"</{tag}>"

            chunks.append(chunk)

            text = text[split_at:].lstrip("\n")

            # Re-open tags at start of next chunk
            if tag_stack and text:
                reopen = ""
                for tag in tag_stack:
                    reopen += f"<{tag}>"
                text = reopen + text

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
