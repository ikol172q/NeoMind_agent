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

        # Persistent chat history (SQLite — survives container restarts)
        from .chat_store import ChatStore
        self._store = ChatStore()
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
        """Handle /help — grouped command reference."""
        current_mode = getattr(self, '_current_mode', 'fin')
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
        self._last_compact_notice = None
        cid = msg.chat_id
        ctype = msg.chat.type or "private"

        if thinking:
            await self._ask_llm_streaming(msg, text, chat_id=cid, chat_type=ctype)
        else:
            reply = await self._ask_llm(text, chat_id=cid, chat_type=ctype)
            if reply:
                await self._send_long_message(msg, reply)
            else:
                await msg.reply_text("⚠️ LLM 未响应，请稍后重试")

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

        Both DeepSeek and z.ai keys are checked. If both exist,
        DeepSeek is primary, z.ai is fallback.
        """
        providers = []

        ds_key = os.getenv("DEEPSEEK_API_KEY", "")
        zai_key = os.getenv("ZAI_API_KEY", "")

        if ds_key:
            providers.append({
                "api_key": ds_key,
                "base_url": "https://api.deepseek.com/chat/completions",
                "model": "deepseek-reasoner" if thinking else "deepseek-chat",
                "name": "deepseek",
            })
        if zai_key:
            providers.append({
                "api_key": zai_key,
                "base_url": "https://api.z.ai/api/paas/v4/chat/completions",
                "model": "glm-5" if thinking else "glm-4.5-flash",
                "name": "zai",
            })

        return providers

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

        messages = [{"role": "system", "content": self._get_system_prompt()}] + history

        if not api_key:
            return "⚠️ No API key configured (DEEPSEEK_API_KEY or ZAI_API_KEY)"

        # Build provider chain: primary → fallback
        providers = self._get_provider_chain(thinking=False)

        for provider in providers:
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, lambda p=provider: req.post(
                    p["base_url"],
                    headers={"Authorization": f"Bearer {p['api_key']}", "Content-Type": "application/json"},
                    json={"model": p["model"], "messages": messages, "max_tokens": 1024, "temperature": 0.7, "stream": False},
                    timeout=30,
                ))
                if response.status_code == 200:
                    reply = response.json()["choices"][0]["message"]["content"].strip()
                    self._store.add_message(chat_id, "assistant", reply, chat_type)
                    self._last_compact_notice = compact_notice
                    if provider != providers[0]:
                        reply += f"\n\n<i>⚡ via {provider['model']} (primary timed out)</i>"
                    return reply
                # Non-timeout error — try next provider
                continue
            except Exception:
                continue  # timeout or network error — try fallback

        return "⚠️ 所有 API 均超时，请稍后重试"

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
        messages = [{"role": "system", "content": self._get_system_prompt()}] + history

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
