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
    from telegram.error import RetryAfter
    from telegram.ext import (
        Application, ApplicationBuilder,
        CommandHandler, MessageHandler, CallbackQueryHandler,
        ContextTypes, filters,
    )
    from telegram.constants import ParseMode, ChatAction
    # ReactionTypeEmoji available in python-telegram-bot >= 20.8 (Bot API 7.0)
    try:
        from telegram import ReactionTypeEmoji
        HAS_REACTIONS = True
    except ImportError:
        HAS_REACTIONS = False
        ReactionTypeEmoji = None
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
        from agent.services.chat_store import ChatStore
        self._store = ChatStore()

        # LLM usage tracking (SQLite — survives container restarts)
        from agent.services.usage_tracker import get_usage_tracker
        self._usage = get_usage_tracker()

        # Provider state (shared with xbar — bidirectional sync)
        from agent.services.provider_state import ProviderStateManager
        self._state_mgr = ProviderStateManager()
        self._state_mgr.register_bot("neomind")
        self._publish_mode_models_to_state()
        print(f"[bot] Chat history DB: {self._store.db_path}", flush=True)

        # Config editor — allows NeoMind to edit its own prompts/config
        from agent.services.config_editor import ConfigEditor
        self._config_editor = ConfigEditor()
        overrides = self._config_editor.load()
        if overrides:
            print(f"[bot] Loaded config overrides: {list(overrides.keys())}", flush=True)

        # Web extractor — optional (for /read, /links, /crawl in Telegram)
        self._web_extractor = None
        self._web_cache = None
        self._last_links: Dict[int, Dict[int, str]] = {}  # chat_id → {num: url}
        try:
            from agent.web.extractor import WebExtractor
            from agent.web.cache import URLCache
            self._web_cache = URLCache(ttl_seconds=1800)
            self._web_extractor = WebExtractor(cache=self._web_cache)
            print("[bot] ✅ WebExtractor loaded (web commands enabled)", flush=True)
        except ImportError as e:
            logger.warning(f"WebExtractor unavailable (web commands disabled): {e}")

        # Workflow modules — optional (graceful degradation on import error)
        try:
            from agent.workflow.sprint import SprintManager
            self._sprint_mgr = SprintManager()
        except Exception as e:
            logger.warning(f"Failed to initialize SprintManager: {e}")
            self._sprint_mgr = None

        try:
            from agent.workflow.guards import SafetyGuard
            self._guard = SafetyGuard()
        except Exception as e:
            logger.warning(f"Failed to initialize SafetyGuard: {e}")
            self._guard = None

        try:
            from agent.workflow.evidence import get_evidence_trail
            self._evidence_trail = get_evidence_trail()
        except Exception as e:
            logger.warning(f"Failed to initialize EvidenceTrail: {e}")
            self._evidence_trail = None

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
        self._app.add_handler(CommandHandler("persona", self._cmd_persona))
        self._app.add_handler(CommandHandler("rag", self._cmd_rag))
        self._app.add_handler(CommandHandler("tune", self._cmd_tune))
        self._app.add_handler(CommandHandler("model", self._cmd_model))
        # System commands
        self._app.add_handler(CommandHandler("hooks", self._cmd_hooks))
        self._app.add_handler(CommandHandler("restart", self._cmd_restart))
        # Web commands: /read, /links, /crawl
        self._app.add_handler(CommandHandler("read", self._cmd_web_read))
        self._app.add_handler(CommandHandler("links", self._cmd_web_links))
        self._app.add_handler(CommandHandler("crawl", self._cmd_web_crawl))

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
        await self._app.initialize()
        await self._app.start()

        # Register command menu in Telegram (visible in autocomplete)
        from telegram import BotCommand
        await self._app.bot.set_my_commands([
            BotCommand("mode", "切换人格 (chat/coding/fin)"),
            BotCommand("model", "查看/切换模型"),
            BotCommand("think", "开关深度思考"),
            BotCommand("provider", "切换 provider (litellm/direct)"),
            BotCommand("status", "查看当前状态"),
            BotCommand("clear", "清空对话历史"),
            BotCommand("help", "查看所有命令"),
            BotCommand("stock", "股票查询 (fin 模式)"),
            BotCommand("crypto", "加密货币 (fin 模式)"),
            BotCommand("news", "多源新闻搜索"),
            BotCommand("hn", "Hacker News"),
            BotCommand("hooks", "系统诊断 (漂移/蒸馏/图谱)"),
            BotCommand("restart", "重启 agent 进程"),
        ])

        await self._app.updater.start_polling(drop_pending_updates=True)

        print(f"[bot] ✅ @{bot_info.username} is LIVE — listening for messages", flush=True)

        # Check if this is a post-self-restart boot → notify user
        asyncio.create_task(self._check_restart_intent())

        # Start background scheduler for auto-push (HN, etc.)
        asyncio.create_task(self._scheduler_loop())

        # Keep running
        try:
            await asyncio.Event().wait()  # block forever
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await self.stop()

    async def _check_restart_intent(self):
        """Check if we're resuming after a self-restart and notify user."""
        try:
            from agent.evolution.self_restart import check_restart_intent
            intent = check_restart_intent()
            if not intent:
                return

            chat_id = intent.get("notify_chat_id")
            if not chat_id:
                # Fall back: find most recent chat from store
                try:
                    import sqlite3
                    conn = sqlite3.connect(str(self._store.db_path))
                    row = conn.execute(
                        "SELECT DISTINCT chat_id FROM messages ORDER BY rowid DESC LIMIT 1"
                    ).fetchone()
                    conn.close()
                    if row:
                        chat_id = row[0]
                except Exception:
                    pass
            if not chat_id:
                logger.info("Post-restart: no chat_id to notify")
                return

            reason = intent.get("reason", "unknown")
            files = intent.get("changed_files", [])
            ts = intent.get("timestamp", "")[:19]

            msg = (
                "✅ <b>Agent 重启完成</b>\n\n"
                f"原因: {reason}\n"
            )
            if files:
                files_str = "\n".join(f"  • <code>{f}</code>" for f in files[:10])
                msg += f"\n修改的文件:\n{files_str}\n"
            msg += f"\n时间: {ts}"

            await self._app.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode=ParseMode.HTML,
            )
            logger.info(f"Post-restart notification sent to {chat_id}")

        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Post-restart notification failed: {e}")

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
            "<code>/model</code> — 查看/切换模型\n"
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
            "<code>/tune</code> — 自调优 (修改 prompt/搜索触发词)\n"
            "\n"
            "── 🌐 <b>网页</b> ──\n"
            "<code>/read</code> &lt;url&gt; — 读取网页内容\n"
            "<code>/links</code> &lt;url&gt; — 提取页面链接\n"
            "<code>/crawl</code> &lt;url&gt; — 爬取同域页面\n"
            "<code>/read N</code> — 跟读 /links 中第 N 个链接\n"
            "<i>也可直接发 URL，自动读取并分析</i>\n"
            "\n"
            "── 🔧 <b>管理</b> ──\n"
            "<code>/clear</code> — 归档对话 (LLM 重开)\n"
            "<code>/context</code> — token 使用量\n"
            "<code>/status</code> — Bot 状态\n"
            "<code>/admin</code> — 管理面板 (历史/归档/清除/统计)\n"
            "\n"
            "── 🧬 <b>自我进化</b> ──\n"
            "<code>/hooks</code> — 系统诊断 (漂移/蒸馏/图谱)\n"
            "<code>/restart</code> — 重启 agent 进程\n"
            "<code>/evolve</code> — 自我进化状态\n"
            "<code>/dashboard</code> — 生成进化指标面板\n"
            "\n"
            "<i>群聊: @我 或 /neo_stock 前缀 | 含 $AAPL 自动触发</i>",
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status — one-stop status: model, provider, search, memory."""
        cid = update.message.chat_id
        current_mode = self._store.get_mode(cid)
        thinking = "ON 🧠" if getattr(self, '_thinking_enabled', False) else "OFF"

        lines = ["<b>NeoMind Status</b>\n"]

        # ── Model & Provider ──
        api_key, base_url, model = self._resolve_api(thinking=False, chat_id=cid)
        _, _, think_model = self._resolve_api(thinking=True, chat_id=cid)
        chain = self._get_provider_chain(thinking=False, chat_id=cid)
        primary = chain[0]["name"] if chain else "none"

        lines.append(f"🧩 模式: <b>{current_mode}</b> | 思考: {thinking}")
        lines.append(f"🤖 模型: <code>{model}</code> via {primary}")
        if think_model != model:
            lines.append(f"🧠 思考模型: <code>{think_model}</code>")

        # Show full provider chain
        if len(chain) > 1:
            fallbacks = ", ".join(f"{p['name']}:{p['model']}" for p in chain[1:])
            lines.append(f"🔗 备选: {fallbacks}")

        # LiteLLM health
        state = self._state_mgr._read_state()
        litellm_info = state.get("litellm", {})
        config = self._state_mgr.get_bot_config("neomind")
        provider_mode = config.get("provider_mode", "direct")
        health = "🟢" if litellm_info.get("health_ok") else "🔴"
        lines.append(f"🔌 Provider: <b>{provider_mode}</b> | LiteLLM: {health}")

        # ── Search ──
        search = self.components.get("search")
        if search:
            t1 = len(search.tier1_sources)
            t2 = len(search.tier2_sources)
            t3 = len(search.tier3_sources)
            lines.append(f"\n🔍 搜索引擎: {t1+t2+t3} 源 (T1:{t1} T2:{t2} T3:{t3})")
            lines.append(f"   内容提取: {'✅' if search.extractor.available else '❌'}")

        # ── Data & Memory ──
        data_hub = self.components.get("data_hub")
        if data_hub:
            lines.append("📊 数据源: Finnhub, yfinance, AKShare, CoinGecko")

        memory = self.components.get("memory")
        lines.append(f"🧠 加密记忆: {'✅' if memory else '❌'}")

        sync = self.components.get("sync")
        if sync:
            lines.append(f"📱 Sync 模式: {sync._mode}")

        # ── Bot info ──
        lines.append(f"\n🤖 Bot: @{self.config.bot_username}")
        if self.config.openclaw_username:
            lines.append(f"🤝 OpenClaw: @{self.config.openclaw_username}")

        lines.append(
            f"\n<code>/provider litellm</code> | <code>direct</code> — 切换路由"
        )

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

    # ── Model Switching ───────────────────────────────────────────────

    async def _cmd_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /model — view or switch the LLM model for THIS chat.

        /model              — show current model + available list
        /model <id>         — switch to model
        /model reset        — restore personality default
        """
        args = " ".join(context.args).strip() if context.args else ""
        cid = update.message.chat_id
        mode = self._store.get_mode(cid)
        override = self._store.get_model_override(cid)
        _, _, active_model = self._resolve_api(thinking=False, chat_id=cid)

        # ── No args: show current + list ──
        if not args:
            from agent.services.llm_provider import PROVIDERS

            if override:
                header = f"当前模型: <code>{override}</code>（手动选择）"
            else:
                header = f"当前模型: <code>{active_model}</code>（{mode} 默认）"

            # Get actually active providers (have API keys)
            chain = self._get_provider_chain(thinking=False, chat_id=cid)
            active_providers = {p["name"] for p in chain}
            # The first provider in chain is the one actually being used
            active_provider_name = chain[0]["name"] if chain else ""

            lines = [f"🤖 {header}\n"]

            for pname, pconf in PROVIDERS.items():
                if pname not in active_providers:
                    continue  # skip providers without API key
                models_list = pconf.get("fallback_models", [])
                if not models_list:
                    continue
                # 🟢 active provider, 🟡 available but idle
                emoji = "🟢" if pname == active_provider_name else "🟡"
                lines.append(f"\n{emoji} <b>{pname}</b>:")
                for m in models_list:
                    mid = m["id"]
                    # Only mark "当前" on the exact model in the active provider
                    if mid == active_model and pname == active_provider_name:
                        marker = " ← 当前"
                    else:
                        marker = ""
                    lines.append(f"  <code>{mid}</code>{marker}")

            lines.append(f"\n切换: <code>/model &lt;id&gt;</code>")
            lines.append(f"恢复: <code>/model reset</code>")

            await update.message.reply_text(
                "\n".join(lines), parse_mode=ParseMode.HTML,
            )
            return

        # ── Reset to default ──
        if args.lower() in ("reset", "default", "auto"):
            self._store.set_model_override(cid, "")
            _, _, default_model = self._resolve_api(thinking=False, chat_id=cid)
            await update.message.reply_text(
                f"✅ 已恢复默认模型: <code>{default_model}</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        # ── Switch to specific model ──
        model_id = args.lower()
        found = False
        found_provider = ""
        from agent.services.llm_provider import PROVIDERS

        # First: check if input is a provider name → use its first model
        for pname, pconf in PROVIDERS.items():
            if model_id in (pname, pname.lower()):
                models_list = pconf.get("fallback_models", [])
                if models_list:
                    model_id = models_list[0]["id"]
                    found_provider = pname
                    found = True
                break

        # Also accept common aliases
        _ALIASES = {
            "kimi": ("moonshot", "kimi-k2.5"),
            "glm": ("zai", "glm-5"),
            "ds": ("deepseek", "deepseek-chat"),
            "local": ("litellm", "local"),
        }
        if not found and model_id in _ALIASES:
            alias_provider, alias_model = _ALIASES[model_id]
            if alias_provider in PROVIDERS:
                model_id = alias_model
                found_provider = alias_provider
                found = True

        # Then: exact model ID match
        if not found:
            for pname, pconf in PROVIDERS.items():
                for m in pconf.get("fallback_models", []):
                    if m["id"] == model_id:
                        found_provider = pname
                        found = True
                        break
                if found:
                    break

        # Validate API key
        if found:
            pconf = PROVIDERS.get(found_provider, {})
            env_key = pconf.get("env_key", "")
            if env_key and not os.getenv(env_key):
                await update.message.reply_text(
                    f"❌ <code>{model_id}</code> ({found_provider}) 需要 {env_key}，但未配置",
                    parse_mode=ParseMode.HTML,
                )
                return

        if not found:
            await update.message.reply_text(
                f"❌ 未知模型: <code>{args}</code>\n"
                f"发 <code>/model</code> 查看可用列表",
                parse_mode=ParseMode.HTML,
            )
            return

        self._store.set_model_override(cid, model_id)
        await update.message.reply_text(
            f"✅ 模型已切换为 <code>{model_id}</code>\n"
            f"人格: <b>{mode}</b>（不变）\n\n"
            f"<i>仅影响此对话，/model reset 恢复默认</i>",
            parse_mode=ParseMode.HTML,
        )

    # ── Message Handlers ─────────────────────────────────────────────

    async def _cmd_think(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /think — toggle thinking (reasoning) mode."""
        cid = update.message.chat_id
        self._thinking_enabled = not self._thinking_enabled
        status = "ON" if self._thinking_enabled else "OFF"
        _, _, model = self._resolve_api(thinking=self._thinking_enabled, chat_id=cid)
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
            _, _, cur_model = self._resolve_api(chat_id=cid)
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
                _, _, cur_model = self._resolve_api(chat_id=cid)
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
        _, _, model = self._resolve_api(thinking=getattr(self, '_thinking_enabled', False), chat_id=cid)
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

        /subscribe hn             — subscribe to HN push (every 4 hours, top 5, score≥100)
        /subscribe hn off         — unsubscribe
        /subscribe hn 2h          — push every 2 hours
        /subscribe hn 50          — min score 50
        /subscribe digest         — daily market digest + thesis alerts (every 12h)
        /subscribe digest 6h      — digest every 6 hours
        /subscribe digest off     — unsubscribe
        /subscribe                — show current subscriptions

        Digest push is inspired by:
            - ValueCell (https://github.com/ValueCell-ai/valuecell) — real-time alerts
            - TradingGoose (https://github.com/TradingGoose/TradingGoose.github.io) — event-driven notifications
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
        if source not in ("hn", "digest"):
            await update.message.reply_text(
                "支持:\n"
                "<code>/subscribe hn</code> — Hacker News 推送\n"
                "<code>/subscribe digest</code> — 市场摘要+论点预警",
                parse_mode=ParseMode.HTML,
            )
            return

        # Check for off/unsubscribe
        if len(args) > 1 and args[1] in ("off", "stop", "cancel", "取消"):
            subs.setdefault(str(cid), {}).pop(source, None)
            self._save_subscriptions(subs)
            label = "HN" if source == "hn" else "市场摘要"
            await update.message.reply_text(f"🔕 已取消 {label} 推送")
            return

        # Parse optional params
        interval_hours = 4 if source == "hn" else 12
        min_score = 100
        for arg in args[1:]:
            if arg.endswith("h") and arg[:-1].isdigit():
                interval_hours = max(1, int(arg[:-1]))
            elif arg.isdigit():
                min_score = int(arg)

        if source == "hn":
            subs.setdefault(str(cid), {})["hn"] = {
                "enabled": True,
                "interval_hours": interval_hours,
                "min_score": min_score,
                "limit": 5,
                "last_push": 0,
                "pushed_ids": [],
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
        elif source == "digest":
            subs.setdefault(str(cid), {})["digest"] = {
                "enabled": True,
                "interval_hours": interval_hours,
                "last_push": 0,
            }
            self._save_subscriptions(subs)
            await update.message.reply_text(
                f"📊 已订阅市场摘要推送\n\n"
                f"频率: 每 {interval_hours} 小时\n"
                f"内容: 高影响新闻 · 源头冲突 · 论点变化 · 准确率\n\n"
                f"<code>/subscribe digest off</code> 取消\n"
                f"<code>/digest</code> 立即查看",
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

            # ── Digest subscription ───────────────────────────────
            digest_cfg = chat_subs.get("digest", {})
            if digest_cfg.get("enabled"):
                d_interval = digest_cfg.get("interval_hours", 12) * 3600
                d_last = digest_cfg.get("last_push", 0)

                if now - d_last >= d_interval:
                    try:
                        text = await self._generate_digest_push()
                        if text:
                            await self._app.bot.send_message(
                                chat_id=chat_id,
                                text=text,
                                parse_mode="HTML",
                                disable_web_page_preview=True,
                            )
                            digest_cfg["last_push"] = now
                            changed = True
                            print(f"[bot] Pushed digest to {chat_id}", flush=True)
                    except Exception as e:
                        print(f"[bot] Failed to push digest to {chat_id}: {e}", flush=True)

        if changed:
            self._save_subscriptions(subs)

    async def _generate_digest_push(self) -> str:
        """Generate a compact Telegram digest summary.

        Pulls from NewsDigestEngine, highlights:
        1. Top 5 high-impact news (with dynamic probability scoring)
        2. Source conflicts detected
        3. Thesis alerts (reversals, low confidence, new checkpoints)
        4. Accuracy stats (if available)

        Inspired by:
            - ValueCell alerts: https://github.com/ValueCell-ai/valuecell
            - TradingGoose event-driven: https://github.com/TradingGoose/TradingGoose.github.io
        """
        lines = ["📊 <b>NeoMind 市场摘要</b>\n"]

        digest_engine = self.components.get("digest") if self.components else None

        # ── Section 1: Top news ──────────────────────────────────
        if digest_engine:
            try:
                digest = await digest_engine.generate_digest()

                if digest.items:
                    lines.append("📰 <b>高影响新闻</b>")
                    for item in digest.items[:5]:
                        badge = "🔴" if item.impact_score >= 6 else "🟡" if item.impact_score >= 3 else "🟢"
                        prob_str = f"{item.impact_probability:.0%}" if item.impact_probability != 0.7 else ""
                        score_str = f" [{item.impact_score:.1f}"
                        if prob_str:
                            score_str += f" p={prob_str}"
                        score_str += "]"
                        lines.append(f"{badge} {item.title}{score_str}")
                    lines.append(f"  <i>共 {len(digest.items)} 条, EN:{digest.en_count} ZH:{digest.zh_count}</i>\n")

                # ── Section 2: Conflicts ─────────────────────────
                if digest.conflicts:
                    lines.append("⚡ <b>源头冲突</b>")
                    for c in digest.conflicts[:3]:
                        lines.append(
                            f"  ⚠️ <b>{c.entity}</b>: "
                            f"{c.claim_a.get('source', '?')} vs {c.claim_b.get('source', '?')} "
                            f"[{c.severity}]"
                        )
                    lines.append("")

            except Exception as e:
                lines.append(f"<i>新闻获取失败: {str(e)[:50]}</i>\n")

        # ── Section 3: Thesis alerts ─────────────────────────────
        if digest_engine and digest_engine._theses:
            alerts = []
            for sym, thesis in digest_engine._theses.items():
                if thesis.closed:
                    continue
                if thesis.reversal_flagged:
                    alerts.append(f"🔄 <b>{sym}</b>: 反转预警! 反方证据累积超阈值")
                elif thesis.confidence < 0.4:
                    alerts.append(f"⚠️ <b>{sym}</b>: 置信度低 ({thesis.confidence:.0%})")
                elif len(thesis.counter_evidence) >= 2:
                    alerts.append(f"📉 <b>{sym}</b>: {len(thesis.counter_evidence)} 条反方证据")

            if alerts:
                lines.append("🎯 <b>论点预警</b>")
                lines.extend(alerts[:5])
                lines.append("")

        # ── Section 4: Accuracy stats ────────────────────────────
        if digest_engine:
            stats = digest_engine.get_accuracy_stats()
            if stats.get("total", 0) > 0:
                lines.append("📈 <b>决策追踪</b>")
                lines.append(
                    f"  准确率: {stats['accuracy']:.0%} "
                    f"({stats['correct']}/{stats['total']})"
                )
                if stats.get("bull_accuracy") is not None:
                    lines.append(f"  看多: {stats['bull_accuracy']:.0%}")
                if stats.get("bear_accuracy") is not None:
                    lines.append(f"  看空: {stats['bear_accuracy']:.0%}")
                lines.append("")

        # ── Footer ───────────────────────────────────────────────
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"<i>{now_str}</i>")
        lines.append("<code>/digest</code> 完整报告 | <code>/subscribe digest off</code> 取消")

        return "\n".join(lines)

    async def _cmd_persona(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /persona — multi-persona investment analysis.

        Usage:
            /persona AAPL          — all 3 personas analyze AAPL
            /persona AAPL value    — value investor only
            /persona list          — show available personas

        References:
            - AI Hedge Fund personas: https://github.com/virattt/ai-hedge-fund
            - TradingAgents roles: https://github.com/TauricResearch/TradingAgents
        """
        args = context.args if context.args else []

        if not args or args[0].lower() == "list":
            try:
                from agent.finance.investment_personas import PERSONAS
            except ImportError:
                from agent.finance.investment_personas import PERSONAS  # fallback

            lines = ["🎭 <b>投资人格分析</b>\n"]
            for key, p in PERSONAS.items():
                lines.append(f"{p.icon} <b>{p.name}</b> (<code>/persona SYMBOL {key}</code>)")
                lines.append(f"  {p.philosophy}")
                lines.append(f"  周期: {p.typical_horizon}\n")
            lines.append("用法: <code>/persona AAPL</code> (三人格同时分析)")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")
            return

        symbol = args[0].upper()
        persona_filter = args[1].lower() if len(args) > 1 else None

        digest_engine = self.components.get("digest") if self.components else None
        if not digest_engine:
            await update.message.reply_text("⚠️ Digest engine 未初始化")
            return

        # Ensure thesis exists
        if symbol not in digest_engine._theses:
            await update.message.reply_text(
                f"⚠️ {symbol} 没有活跃论点。先用 <code>/stock {symbol}</code> 建立分析。",
                parse_mode="HTML",
            )
            return

        result = digest_engine.debate_with_personas(symbol)
        if "error" in result:
            await update.message.reply_text(f"⚠️ {result['error']}")
            return

        lines = [f"🎭 <b>{symbol} 多人格分析</b>\n"]
        lines.append(f"📈 当前方向: {result['base_debate']['direction']} "
                     f"(信心: {result['base_debate']['confidence']:.0%})")
        lines.append(f"🔍 判定: <b>{result['base_debate']['verdict']}</b>\n")

        for p in result["persona_prompts"]:
            if persona_filter and persona_filter not in p["persona_name"].lower():
                continue
            lines.append(f"{p['persona_icon']} <b>{p['persona_name']}</b> ({p['horizon']})")
            lines.append(f"  理念: {p['philosophy']}")
            lines.append(f"  关注: {', '.join(p['rubric_criteria'][:4])}")
            if p["red_flags"]:
                lines.append(f"  🚩 红线: {p['red_flags'][0]}")
            lines.append("")

        lines.append(f"<i>提示: 将 persona prompt 发送给 LLM 获取完整分析</i>")
        text = "\n".join(lines)
        # Truncate for Telegram 4096 limit
        if len(text) > 4000:
            text = text[:3990] + "\n..."
        await update.message.reply_text(text, parse_mode="HTML")

    async def _cmd_rag(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /rag — financial document RAG queries.

        Usage:
            /rag query What was Apple's revenue guidance?
            /rag query AAPL earnings outlook   — filtered by symbol
            /rag stats                         — show index statistics
            /rag ingest <filepath>             — ingest a document

        References:
            - KG-RAG: https://github.com/VectorInstitute/kg-rag
            - FinanceRAG: https://github.com/nik2401/FinanceRAG-Investment-Research-Assistant
        """
        args = context.args if context.args else []

        rag = self.components.get("rag") if self.components else None

        if not args:
            lines = [
                "📚 <b>金融文档 RAG</b>\n",
                "<code>/rag stats</code> — 索引统计",
                "<code>/rag query &lt;问题&gt;</code> — 语义搜索",
                "<code>/rag ingest &lt;路径&gt;</code> — 导入文档",
            ]
            if not rag:
                lines.append("\n⚠️ RAG 未启用 (需要 faiss-cpu + sentence-transformers)")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")
            return

        subcmd = args[0].lower()

        if subcmd == "stats":
            if not rag:
                await update.message.reply_text("⚠️ RAG 未启用 (pip install faiss-cpu sentence-transformers PyPDF2)")
                return
            stats = rag.get_stats()
            lines = [
                "📚 <b>RAG 索引统计</b>\n",
                f"📄 文档数: {stats['total_documents']}",
                f"🧩 分块数: {stats['total_chunks']}",
                f"🔢 向量数: {stats['index_vectors']}",
                f"🤖 模型: {stats['model']}",
            ]
            if stats.get("doc_types"):
                lines.append(f"📂 类型: {stats['doc_types']}")
            if stats.get("symbols"):
                lines.append(f"📊 标的: {stats['symbols']}")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        elif subcmd == "query" and len(args) > 1:
            if not rag:
                await update.message.reply_text("⚠️ RAG 未启用")
                return
            question = " ".join(args[1:])
            # Check if first word after query is a symbol
            symbol = None
            if len(args) > 2 and args[1].isupper() and len(args[1]) <= 5:
                symbol = args[1]
                question = " ".join(args[2:])

            results = rag.query(question, top_k=3, symbol=symbol)
            if not results:
                await update.message.reply_text("🔍 未找到相关文档。试试 <code>/rag ingest</code> 导入文档。", parse_mode="HTML")
                return

            lines = [f"🔍 <b>查询结果</b>: {question}\n"]
            for r in results:
                meta = r.chunk.metadata
                src = meta.get("source_file", meta.get("source", "?"))
                sym = f" ({meta['symbol']})" if meta.get("symbol") else ""
                lines.append(f"<b>[{r.rank}]</b> {src}{sym} <i>(score: {r.score:.2f})</i>")
                # Show first 200 chars of chunk
                preview = r.chunk.text[:200].replace("<", "&lt;").replace(">", "&gt;")
                lines.append(f"  {preview}...\n")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        elif subcmd == "ingest" and len(args) > 1:
            if not rag:
                await update.message.reply_text("⚠️ RAG 未启用")
                return
            filepath = " ".join(args[1:])
            import os
            if not os.path.exists(filepath):
                await update.message.reply_text(f"❌ 文件不存在: {filepath}")
                return
            try:
                # Guess symbol from filename
                basename = os.path.basename(filepath).upper()
                import re
                sym_match = re.search(r'([A-Z]{1,5})', basename)
                symbol = sym_match.group(1) if sym_match else None

                n = rag.ingest_file(filepath, symbol=symbol)
                await update.message.reply_text(
                    f"✅ 已导入 <b>{os.path.basename(filepath)}</b>\n"
                    f"生成 {n} 个分块" + (f", 标的: {symbol}" if symbol else ""),
                    parse_mode="HTML",
                )
            except Exception as e:
                await update.message.reply_text(f"❌ 导入失败: {str(e)[:200]}")

        else:
            await update.message.reply_text("用法: <code>/rag stats|query|ingest</code>", parse_mode="HTML")

    async def _cmd_tune(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /tune — let NeoMind edit its own prompts and config.

        Usage:
            /tune status              — show current overrides
            /tune reset               — reset all overrides to defaults
            /tune reset fin           — reset only fin mode
            /tune prompt <text>       — append instructions to current mode's prompt
            /tune prompt.set <text>   — replace current mode's extra prompt entirely
            /tune trigger add <words> — add search trigger keywords
            /tune trigger del <words> — remove search trigger keywords
            /tune set <key> <value>   — set an arbitrary config key
            /tune <natural language>  — describe what you want changed (NeoMind figures it out)
        """
        args = context.args if context.args else []
        msg = update.message
        chat_id = msg.chat_id
        current_mode = self._store.get_mode(chat_id) if chat_id else "fin"
        editor = self._config_editor

        if not args:
            help_text = (
                "🔧 <b>/tune — 自调优</b>\n\n"
                "让 NeoMind 修改自己的 prompt 和配置：\n\n"
                "<code>/tune status</code> — 查看当前覆盖配置\n"
                "<code>/tune reset</code> — 重置所有自定义配置\n"
                "<code>/tune prompt 回复更简洁</code> — 追加 prompt 指令\n"
                "<code>/tune prompt.set 你是一个...</code> — 替换 prompt\n"
                "<code>/tune trigger add 半导体 AI芯片</code> — 加搜索触发词\n"
                "<code>/tune trigger del 半导体</code> — 删搜索触发词\n\n"
                "也可以用自然语言：\n"
                "<code>/tune 搜索科技新股相关的内容时自动搜索</code>\n"
                "<code>/tune 回复的时候少用 bullet points</code>"
            )
            await msg.reply_text(help_text, parse_mode=ParseMode.HTML)
            return

        subcmd = args[0].lower()

        # /tune status
        if subcmd == "status":
            status = editor.format_status()
            await msg.reply_text(status, parse_mode=ParseMode.HTML)
            return

        # /tune reset [mode]
        if subcmd == "reset":
            if len(args) > 1:
                mode = args[1].lower()
                editor.reset_mode(mode)
                await msg.reply_text(f"✅ 已重置 [{mode}] 模式的自定义配置")
            else:
                editor.reset_all()
                await msg.reply_text("✅ 已重置所有自定义配置，恢复默认")
            # Clear cached regex so it rebuilds
            if hasattr(self, '_search_trigger_re'):
                del self._search_trigger_re
            return

        # /tune prompt <text> — append to extra prompt
        if subcmd == "prompt" and len(args) > 1:
            text = " ".join(args[1:])
            editor.append_to_prompt(current_mode, text)
            await msg.reply_text(
                f"✅ 已追加 prompt 指令到 [{current_mode}] 模式：\n"
                f"<code>{text[:200]}</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        # /tune prompt.set <text> — replace extra prompt
        if subcmd == "prompt.set" and len(args) > 1:
            text = " ".join(args[1:])
            editor.set_extra_prompt(current_mode, text)
            await msg.reply_text(
                f"✅ 已设置 [{current_mode}] 模式额外 prompt：\n"
                f"<code>{text[:200]}</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        # /tune trigger add/del <words>
        if subcmd == "trigger" and len(args) > 2:
            action = args[1].lower()
            words = args[2:]
            if action == "add":
                editor.add_search_triggers(words, mode=current_mode)
                # Clear cached regex
                if hasattr(self, '_search_trigger_re'):
                    del self._search_trigger_re
                await msg.reply_text(
                    f"✅ 已添加搜索触发词: {', '.join(words)}\n"
                    f"模式: [{current_mode}]",
                )
                return
            elif action in ("del", "delete", "remove"):
                editor.remove_search_triggers(words, mode=current_mode)
                if hasattr(self, '_search_trigger_re'):
                    del self._search_trigger_re
                await msg.reply_text(f"✅ 已移除搜索触发词: {', '.join(words)}")
                return

        # /tune set <key> <value>
        if subcmd == "set" and len(args) > 2:
            key = args[1]
            value = " ".join(args[2:])
            # Try to parse as number/bool
            if value.lower() in ("true", "yes"):
                value = True
            elif value.lower() in ("false", "no"):
                value = False
            else:
                try:
                    value = float(value) if "." in value else int(value)
                except ValueError:
                    pass
            editor.set_setting(current_mode, key, value)
            await msg.reply_text(
                f"✅ [{current_mode}] {key} = {value}",
            )
            return

        # Fallback: natural language — use LLM to interpret and apply
        instruction = " ".join(args)
        await msg.chat.send_action(ChatAction.TYPING)

        # Ask the LLM to interpret the tune instruction
        interpret_prompt = (
            "You are NeoMind's config editor. The user wants to adjust NeoMind's behavior.\n"
            "Interpret their instruction and output EXACTLY ONE of these commands:\n\n"
            "PROMPT_APPEND|<mode>|<text>  — append text to the mode's system prompt\n"
            "TRIGGER_ADD|<mode>|<word1>,<word2>,...  — add search trigger keywords\n"
            "TRIGGER_DEL|<mode>|<word1>,<word2>,...  — remove search trigger keywords\n"
            "SET|<mode>|<key>|<value>  — set a config key\n"
            "UNKNOWN|<explanation>  — if you can't understand the instruction\n\n"
            f"Current mode: {current_mode}\n"
            f"User instruction: {instruction}\n\n"
            "Output only the command, nothing else."
        )

        try:
            import requests as req
            api_key, base_url, model = self._resolve_api(thinking=False, chat_id=chat_id)
            if not api_key:
                await msg.reply_text("⚠️ No API key for LLM interpretation")
                return

            resp = await asyncio.get_event_loop().run_in_executor(None, lambda: req.post(
                base_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": interpret_prompt}],
                    "max_tokens": 200, "temperature": 0.1,
                },
                timeout=15,
            ))

            if resp.status_code != 200:
                await msg.reply_text(f"⚠️ LLM error: {resp.status_code}")
                return

            result = resp.json()["choices"][0]["message"]["content"].strip()
            parts = result.split("|")
            cmd = parts[0] if parts else "UNKNOWN"

            if cmd == "PROMPT_APPEND" and len(parts) >= 3:
                mode, text = parts[1], "|".join(parts[2:])
                editor.append_to_prompt(mode, text)
                await msg.reply_text(
                    f"🔧 已理解并执行：\n"
                    f"追加 [{mode}] prompt：<code>{text[:300]}</code>",
                    parse_mode=ParseMode.HTML,
                )
            elif cmd == "TRIGGER_ADD" and len(parts) >= 3:
                mode, words = parts[1], parts[2].split(",")
                words = [w.strip() for w in words if w.strip()]
                editor.add_search_triggers(words, mode=mode)
                if hasattr(self, '_search_trigger_re'):
                    del self._search_trigger_re
                await msg.reply_text(f"🔧 已理解并执行：\n添加搜索触发词: {', '.join(words)}")
            elif cmd == "TRIGGER_DEL" and len(parts) >= 3:
                mode, words = parts[1], parts[2].split(",")
                words = [w.strip() for w in words if w.strip()]
                editor.remove_search_triggers(words, mode=mode)
                if hasattr(self, '_search_trigger_re'):
                    del self._search_trigger_re
                await msg.reply_text(f"🔧 已理解并执行：\n移除搜索触发词: {', '.join(words)}")
            elif cmd == "SET" and len(parts) >= 4:
                mode, key, value = parts[1], parts[2], parts[3]
                editor.set_setting(mode, key, value)
                await msg.reply_text(f"🔧 已理解并执行：\n[{mode}] {key} = {value}")
            else:
                explanation = "|".join(parts[1:]) if len(parts) > 1 else "无法理解指令"
                await msg.reply_text(
                    f"🤔 我不太确定怎么执行这个调整。\n{explanation}\n\n"
                    f"试试更具体的命令：\n"
                    f"<code>/tune prompt 你的指令</code>\n"
                    f"<code>/tune trigger add 关键词</code>",
                    parse_mode=ParseMode.HTML,
                )

        except Exception as e:
            await msg.reply_text(f"⚠️ 调优失败: {str(e)[:200]}")

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
            # No duplicate status — point user to /status for full view
            config = self._state_mgr.get_bot_config("neomind")
            mode = config.get("provider_mode", "direct")
            await update.message.reply_text(
                f"🔌 当前路由: <b>{mode}</b>\n\n"
                f"<code>/provider litellm</code> — 切换到本地 Ollama\n"
                f"<code>/provider direct</code> — 切换到直连 API\n\n"
                f"<i>完整状态请用 /status</i>",
                parse_mode=ParseMode.HTML,
            )

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
            cid = update.message.chat_id
            new_chain = self._get_provider_chain(thinking=False, chat_id=cid)
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
            self._publish_mode_models_to_state()  # sync to xbar
            if self._evidence_trail:
                self._evidence_trail.log("provider", "switch_litellm", f"Switched to LiteLLM: {chat_actual}", mode=self._store.get_mode(update.message.chat_id))

        elif args in ("direct", "off", "disable"):
            config = self._state_mgr.set_provider_mode(
                "neomind", "direct", updated_by="telegram"
            )
            cid = update.message.chat_id
            new_chain = self._get_provider_chain(thinking=False, chat_id=cid)
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
            self._publish_mode_models_to_state()  # sync to xbar
            if self._evidence_trail:
                self._evidence_trail.log("provider", "switch_direct", f"Switched to direct API", mode=self._store.get_mode(update.message.chat_id))

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
        if not self._guard:
            await update.message.reply_text("⚠️ Safety guard module not initialized")
            return

        try:
            if self._guard.state.careful_enabled:
                self._guard.disable_careful()
                await update.message.reply_text("⚪ Careful mode OFF")
                if self._evidence_trail:
                    self._evidence_trail.log("guard", "disable_careful", "Safety guard disabled", mode="fin")
            else:
                self._guard.enable_careful()
                await update.message.reply_text("🛑 Careful mode ON — will warn before destructive operations")
                if self._evidence_trail:
                    self._evidence_trail.log("guard", "enable_careful", "Safety guard enabled", mode="fin")
        except Exception as e:
            logger.error(f"Error in /careful: {e}")
            await update.message.reply_text(f"⚠️ Error: {str(e)[:100]}")

    async def _cmd_sprint(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /sprint — structured task workflow."""
        if not self._sprint_mgr:
            await update.message.reply_text("⚠️ Sprint module not initialized")
            return

        try:
            cid = update.message.chat_id
            mode = self._store.get_mode(cid)
            args = list(context.args) if context.args else []
            mgr = self._sprint_mgr

            if not args:
                await update.message.reply_text(
                    "<b>Sprint</b> — structured task workflow\n\n"
                    "<code>/sprint new Buy AAPL</code> — create sprint\n"
                    "<code>/sprint status</code> — show progress\n"
                    "<code>/sprint next</code> — advance to next phase\n"
                    "<code>/sprint done</code> — complete current phase",
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
                if self._evidence_trail:
                    self._evidence_trail.log("sprint", f"create {goal}", f"Sprint {sprint.id} created", mode=mode, sprint_id=sprint.id)
            elif subcmd in ("status", ""):
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
                        if self._evidence_trail:
                            self._evidence_trail.log("sprint", f"advance to {phase.name}", f"Advanced sprint {sid}", sprint_id=sid)
                    else:
                        await update.message.reply_text("✅ Sprint completed!")
                        if self._evidence_trail:
                            self._evidence_trail.log("sprint", "complete", f"Sprint {sid} completed", sprint_id=sid)
                    break
            elif subcmd == "done":
                for sid in list(mgr._active_sprints.keys()):
                    current = mgr._active_sprints[sid].current_phase
                    if current:
                        output = " ".join(args[1:]) if len(args) > 1 else ""
                        mgr.complete_phase(sid, output=output)
                        await update.message.reply_text(f"✅ Completed: <b>{current.name}</b>", parse_mode=ParseMode.HTML)
                        if self._evidence_trail:
                            self._evidence_trail.log("sprint", f"done {current.name}", f"Phase {current.name} completed", sprint_id=sid)
                    break
            elif subcmd == "skip":
                for sid in list(mgr._active_sprints.keys()):
                    phase = mgr.skip_phase(sid)
                    if phase:
                        await update.message.reply_text(f"⏭️ Skipped → <b>{phase.name}</b>", parse_mode=ParseMode.HTML)
                        if self._evidence_trail:
                            self._evidence_trail.log("sprint", f"skip to {phase.name}", f"Skipped to {phase.name}", sprint_id=sid)
                    break
        except Exception as e:
            logger.error(f"Error in /sprint: {e}")
            await update.message.reply_text(f"⚠️ Error: {str(e)[:100]}")

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

    # ── Web Commands (/read, /links, /crawl) ─────────────────────────

    async def _cmd_web_read(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /read <url> — extract and display webpage content."""
        msg = update.message
        args = msg.text.split(maxsplit=1)
        if len(args) < 2:
            await msg.reply_text(
                "用法: <code>/read &lt;url&gt;</code>\n"
                "示例: <code>/read https://example.com</code>\n\n"
                "也可以 <code>/read 3</code> 跟读上次 /links 结果中的第 3 个链接",
                parse_mode=ParseMode.HTML,
            )
            return

        await self._react(msg, "👀")
        await msg.chat.send_action(ChatAction.TYPING)

        url_or_num = args[1].strip()

        # Support /read N (follow link from last /links result)
        if url_or_num.isdigit():
            chat_links = self._last_links.get(msg.chat_id, {})
            num = int(url_or_num)
            if num in chat_links:
                url_or_num = chat_links[num]
            else:
                await msg.reply_text(f"⚠️ 链接 #{num} 不存在。先用 /links 提取链接列表")
                await self._react(msg, "❌")
                return

        if not self._web_extractor:
            await msg.reply_text("⚠️ WebExtractor 未加载，请安装 web 依赖: pip install 'neomind[web]'")
            await self._react(msg, "❌")
            return

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._web_extractor.extract(url_or_num, max_length=10000, include_links=True)
            )
            if not result.ok:
                await msg.reply_text(f"⚠️ 无法读取: {result.error}")
                await self._react(msg, "❌")
                return

            # Format output
            header = f"📄 <b>{html.escape(result.title or '(no title)')}</b>\n"
            header += f"🔗 {html.escape(result.url)}\n"
            header += f"📊 {result.word_count:,} words · via {result.strategy}\n\n"

            # Truncate content for Telegram (4096 char limit)
            max_content = 3500 - len(header)
            content = result.content[:max_content]
            if len(result.content) > max_content:
                content += "\n\n... (内容已截断，完整内容已注入 AI 记忆)"

            await self._send_long_message(msg, header + html.escape(content))

            # Store links for /read N follow-up
            if result.links:
                self._last_links[msg.chat_id] = {
                    i: link.href for i, link in enumerate(result.links[:50], 1)
                }

            # Inject into LLM context for follow-up questions
            self._store.add_message(
                msg.chat_id, "system",
                f"[Web page content from {result.url}]\nTitle: {result.title}\n\n{result.content[:6000]}",
                msg.chat.type or "private",
            )

            await self._react(msg, "✅")
        except Exception as e:
            logger.error(f"/read failed: {e}")
            await msg.reply_text(f"⚠️ 读取失败: {e}")
            await self._react(msg, "❌")

    async def _cmd_web_links(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /links <url> — extract and list all links from a page."""
        msg = update.message
        args = msg.text.split(maxsplit=1)

        # /links with no args → re-show last result
        if len(args) < 2:
            chat_links = self._last_links.get(msg.chat_id, {})
            if chat_links:
                lines = ["📎 <b>上次提取的链接：</b>\n"]
                for num, href in sorted(chat_links.items()):
                    lines.append(f"[{num}] {html.escape(href)}")
                await self._send_long_message(msg, "\n".join(lines))
                return
            await msg.reply_text(
                "用法: <code>/links &lt;url&gt;</code>\n"
                "示例: <code>/links https://example.com</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        await self._react(msg, "👀")
        await msg.chat.send_action(ChatAction.TYPING)

        url = args[1].strip()
        if not self._web_extractor:
            await msg.reply_text("⚠️ WebExtractor 未加载")
            await self._react(msg, "❌")
            return

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._web_extractor.extract(url, max_length=5000, include_links=True)
            )
            if not result.links:
                await msg.reply_text("⚠️ 未找到链接")
                await self._react(msg, "❌")
                return

            # Classify links
            internal = [l for l in result.links if l.is_internal]
            external = [l for l in result.links if not l.is_internal]

            lines = [f"📎 <b>{html.escape(result.title or url)}</b>\n"]
            lines.append(f"共 {len(result.links)} 个链接 (内部: {len(internal)}, 外部: {len(external)})\n")

            for i, link in enumerate(result.links[:50], 1):
                tag = "🏠" if link.is_internal else "🌐"
                text = html.escape(link.text[:50]) if link.text else "(no text)"
                lines.append(f"[{i}] {tag} {text}\n    → {html.escape(link.href)}")

            lines.append(f"\n💡 用 <code>/read N</code> 读取对应链接的内容")

            # Store for /read N
            self._last_links[msg.chat_id] = {
                i: link.href for i, link in enumerate(result.links[:50], 1)
            }

            await self._send_long_message(msg, "\n".join(lines))
            await self._react(msg, "✅")
        except Exception as e:
            logger.error(f"/links failed: {e}")
            await msg.reply_text(f"⚠️ 链接提取失败: {e}")
            await self._react(msg, "❌")

    async def _cmd_web_crawl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /crawl <url> [--depth N] [--max N] — BFS crawl a site."""
        msg = update.message
        args = msg.text.split()

        if len(args) < 2:
            await msg.reply_text(
                "用法: <code>/crawl &lt;url&gt; [--depth N] [--max N]</code>\n"
                "示例: <code>/crawl https://docs.example.com --depth 2 --max 15</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        await self._react(msg, "👀")
        await msg.chat.send_action(ChatAction.TYPING)
        await msg.reply_text("🕷️ 开始爬取，请稍候...")

        if not self._web_extractor:
            await msg.reply_text("⚠️ WebExtractor 未加载")
            await self._react(msg, "❌")
            return

        # Parse arguments
        url = args[1]
        max_depth = 1
        max_pages = 10
        for i, arg in enumerate(args):
            if arg == "--depth" and i + 1 < len(args) and args[i + 1].isdigit():
                max_depth = min(int(args[i + 1]), 3)  # Cap at 3
            if arg == "--max" and i + 1 < len(args) and args[i + 1].isdigit():
                max_pages = min(int(args[i + 1]), 30)  # Cap at 30

        try:
            from agent.web.crawler import BFSCrawler
            crawler = BFSCrawler(
                extractor=self._web_extractor,
                cache=self._web_cache,
                delay=1.0,
            )

            report = await asyncio.get_event_loop().run_in_executor(
                None, lambda: crawler.crawl(url, max_depth=max_depth, max_pages=max_pages)
            )

            summary = report.summary()
            await self._send_long_message(msg, html.escape(summary))

            # Inject crawled content into LLM memory
            all_content = report.all_content(max_chars_per_page=2000)
            if all_content:
                self._store.add_message(
                    msg.chat_id, "system",
                    f"[Crawled {len(report.ok_pages)} pages from {url}]\n\n{all_content[:12000]}",
                    msg.chat.type or "private",
                )

            await self._react(msg, "✅")
        except ImportError:
            await msg.reply_text("⚠️ crawler 模块未找到，请确认 agent/web/ 包完整")
            await self._react(msg, "❌")
        except Exception as e:
            logger.error(f"/crawl failed: {e}")
            await msg.reply_text(f"⚠️ 爬取失败: {e}")
            await self._react(msg, "❌")

    async def _cmd_hooks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /hooks — show integration hooks diagnostic dashboard."""
        msg = update.message
        args = context.args if context.args else []
        arg = " ".join(args) if args else ""

        result = self._exec_hooks_command(arg)
        await self._send_long_message(msg, result)

    async def _cmd_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /restart — request graceful agent process restart.

        Usage:
            /restart              — restart the agent process
            /restart history      — show recent restart history
        """
        msg = update.message
        args = context.args if context.args else []
        arg = " ".join(args) if args else ""

        result = self._exec_restart_command(arg)
        await self._send_long_message(msg, result)

    # ── URL Auto-detection for LLM context ─────────────────────────

    _URL_RE = re.compile(r'https?://[^\s<>"\']+')

    async def _auto_fetch_urls(self, text: str, chat_id: int, chat_type: str) -> Optional[str]:
        """If message contains URLs, auto-fetch content and return context string.

        Returns context to inject before LLM call, or None if no URLs / extractor unavailable.
        """
        if not self._web_extractor:
            return None

        urls = self._URL_RE.findall(text)
        if not urls:
            return None

        # Limit to first 2 URLs to avoid abuse
        urls = urls[:2]
        contexts = []

        for url in urls:
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda u=url: self._web_extractor.extract(u, max_length=6000, include_links=False)
                )
                if result.ok:
                    contexts.append(
                        f"[Auto-fetched web content from {result.url}]\n"
                        f"Title: {result.title}\n\n{result.content[:4000]}"
                    )
            except Exception as e:
                logger.debug(f"Auto-fetch failed for {url}: {e}")

        if contexts:
            return "\n\n---\n\n".join(contexts)
        return None

    # All commands that should be routed to the LLM for processing
    # Includes shared + personality-specific commands
    _LLM_ROUTED_COMMANDS = {
        # Shared commands (available in all modes)
        "/summarize", "/reason", "/debug", "/explain", "/refactor",
        "/translate", "/generate", "/search", "/plan", "/task",
        "/execute", "/auto", "/skill",
        "/freeze", "/unfreeze", "/guard", "/verbose",
        "/read", "/links", "/crawl", "/webmap", "/logs",
        # Chat personality — exploration
        "/deep", "/compare", "/draft", "/brainstorm", "/tldr", "/explore",
        # Finance personality — money-making
        "/stock", "/portfolio", "/market", "/news", "/watchlist", "/quant",
        # Coding personality — development
        "/code", "/write", "/edit", "/run", "/git", "/diff", "/browse",
        "/undo", "/test", "/apply", "/grep", "/find", "/fix", "/analyze",
    }

    async def _handle_unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle unrecognized commands: route shared commands or suggest fixes."""
        text = update.message.text or ""
        cmd = text.split()[0].lower() if text else ""

        # 1. System commands that can be executed directly (no LLM needed)
        system_result = await self._try_system_command(cmd, text)
        if system_result is not None:
            await self._send_long_message(update.message, system_result)
            return

        # 2. Shared commands → route through LLM (it handles them natively)
        if cmd in self._LLM_ROUTED_COMMANDS:
            await self._process_and_reply(update, text, "shared_command")
            return

        # 3. Common typos / close matches
        suggestions = {
            "/models": "/model",
            "/modes": "/mode",
            "/switch": "/model",
            "/stocks": "/stock",
            "/price": "/stock",
            "/btc": "/crypto BTC",
            "/eth": "/crypto ETH",
            "/bitcoin": "/crypto BTC",
            "/config": "/status",
            "/settings": "/status",
            "/fetch": "/read",
            "/open": "/read",
            "/visit": "/read",
            "/webpage": "/read",
            "/link": "/links",
            "/spider": "/crawl",
            "/scrape": "/crawl",
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

    async def _try_system_command(self, cmd: str, text: str) -> Optional[str]:
        """Try to execute a system command directly (no LLM needed).
        Returns result string or None if not a system command."""

        arg = text[len(cmd):].strip() if len(text) > len(cmd) else ""

        if cmd == "/arch":
            return self._exec_arch_command(arg)
        elif cmd == "/dashboard":
            return self._exec_dashboard_command()
        elif cmd == "/evolve":
            return self._exec_evolve_command(arg)
        elif cmd == "/upgrade":
            return self._exec_upgrade_command(arg)
        elif cmd == "/hooks":
            return self._exec_hooks_command(arg)
        elif cmd == "/restart":
            return self._exec_restart_command(arg)

        return None

    def _exec_arch_command(self, arg: str) -> str:
        """Generate or audit the architecture graph."""
        import subprocess
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "scripts", "gen_architecture.py")
        if not os.path.exists(script):
            return "❌ Architecture script not found at scripts/gen_architecture.py"
        cmd = ["python3", script]
        sub = (arg or "").strip().lower()
        if sub == "audit":
            cmd.append("--audit-only")
        elif sub == "json":
            cmd.append("--json")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))))
            output = result.stdout.strip()
            if result.stderr:
                output += "\n" + result.stderr.strip()
            if result.returncode != 0:
                return f"❌ Architecture generation failed:\n{output}"
            return f"📐 Architecture Graph\n\n{output}\n\nOpen plans/architecture_interactive.html to view."
        except subprocess.TimeoutExpired:
            return "❌ Architecture generation timed out."
        except Exception as e:
            return f"❌ Error: {e}"

    def _exec_dashboard_command(self) -> str:
        """Generate HTML evolution metrics dashboard."""
        try:
            from agent.evolution.dashboard import generate_dashboard
            from pathlib import Path
            dashboard_path = Path.home() / ".neomind" / "dashboard.html"
            generate_dashboard(str(dashboard_path))
            return (
                f"📊 Dashboard generated!\n"
                f"Location: {dashboard_path}\n"
                f"Size: {dashboard_path.stat().st_size / 1024:.1f} KB"
            )
        except ImportError:
            return "⚠️ Dashboard module not available."
        except Exception as e:
            return f"❌ Dashboard error: {e}"

    def _exec_hooks_command(self, arg: str) -> str:
        """Show integration hooks diagnostic dashboard."""
        try:
            from agent.services.shared_commands import _handle_hooks_diagnostic
            return _handle_hooks_diagnostic(None, arg)
        except ImportError:
            return "⚠️ Hooks diagnostic module not available."
        except Exception as e:
            return f"❌ Hooks error: {e}"

    def _exec_restart_command(self, arg: str) -> str:
        """Request a graceful agent process restart via supervisord.

        Usage:
            /restart              — restart the agent process
            /restart history      — show recent restart history
        """
        sub = (arg or "").strip().lower()

        if sub == "history":
            try:
                from agent.evolution.self_restart import get_restart_history
                history = get_restart_history(10)
                if not history:
                    return "📋 No restart history yet."
                lines = ["📋 Recent Restarts:\n"]
                for entry in history:
                    ts = entry.get("timestamp", "?")[:19]
                    reason = entry.get("reason", "?")[:80]
                    files = entry.get("changed_files", [])
                    files_str = f" ({len(files)} files)" if files else ""
                    lines.append(f"  {ts} — {reason}{files_str}")
                return "\n".join(lines)
            except Exception as e:
                return f"❌ Error reading history: {e}"

        # Actual restart request
        try:
            from agent.evolution.self_restart import request_restart, is_supervisor_managed
            if not is_supervisor_managed():
                return (
                    "⚠️ 自重启仅在 Telegram daemon 模式下可用。\n"
                    "当前未在 supervisord 下运行。"
                )

            reason = arg if arg else "Manual /restart command from Telegram"
            # Get current chat_id for post-restart notification
            chat_id = None
            if hasattr(self, '_authorized_chat_id'):
                chat_id = self._authorized_chat_id

            ok, msg = request_restart(
                reason=reason,
                notify_chat_id=chat_id,
                delay_seconds=2.0,  # give time for this response to be sent
            )
            if ok:
                return (
                    "🔄 正在重启 agent 进程...\n"
                    f"原因: {reason}\n\n"
                    "supervisord 会自动拉起新进程，约 5-10 秒后恢复。\n"
                    "其他服务（health-monitor, watchdog, data-collector）不受影响。"
                )
            else:
                return f"❌ 重启失败: {msg}"
        except ImportError:
            return "⚠️ self_restart module not available."
        except Exception as e:
            return f"❌ Restart error: {e}"

    def _exec_evolve_command(self, arg: str) -> str:
        """View self-evolution status."""
        try:
            from agent.evolution.auto_evolve import AutoEvolve
            if not isinstance(AutoEvolve, type):
                return "⚠️ Evolution module not available."
            evolve = AutoEvolve()
            sub = (arg or "").strip().lower()
            if sub == "status" or not sub:
                return evolve.get_evolution_summary()
            elif sub == "daily":
                report = evolve.run_daily_audit()
                return f"📋 Daily Audit\n\n{report}"
            elif sub == "weekly":
                report = evolve.run_weekly_retro()
                return f"📋 Weekly Retro\n\n{report}"
            elif sub == "health":
                report = evolve.run_startup_check()
                return f"🏥 Health Check\n\n{report}"
            else:
                return "Usage: /evolve [status|daily|weekly|health]"
        except ImportError:
            return "⚠️ Evolution module not available."
        except Exception as e:
            return f"❌ Evolution error: {e}"

    def _exec_upgrade_command(self, arg: str) -> str:
        """Check or perform upgrades."""
        try:
            from agent.evolution.upgrader import Upgrader
            upgrader = Upgrader()
            sub = (arg or "").strip().lower()
            if sub == "check" or not sub:
                return upgrader.check_for_updates()
            elif sub == "history":
                return upgrader.get_upgrade_history()
            else:
                return "Usage: /upgrade [check|history]"
        except ImportError:
            return "⚠️ Upgrade module not available."
        except Exception as e:
            return f"❌ Upgrade error: {e}"

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

    # ── Message Reactions (Bot API 7.0+) ────────────────────────────

    async def _react(self, msg, emoji: str) -> None:
        """Set a reaction emoji on a message (👀 processing, ✅ done, ❌ error).

        Gracefully degrades if:
        - python-telegram-bot < 20.8 (no ReactionTypeEmoji)
        - Bot lacks permission in the chat
        - Telegram API rejects the emoji
        """
        if not HAS_REACTIONS or not self._app:
            return
        try:
            await self._app.bot.set_message_reaction(
                chat_id=msg.chat_id,
                message_id=msg.message_id,
                reaction=[ReactionTypeEmoji(emoji)],
            )
        except Exception:
            pass  # Silently ignore — reactions are a nice-to-have

    async def _react_clear(self, msg) -> None:
        """Remove all reactions from a message."""
        if not HAS_REACTIONS or not self._app:
            return
        try:
            await self._app.bot.set_message_reaction(
                chat_id=msg.chat_id,
                message_id=msg.message_id,
                reaction=[],
            )
        except Exception:
            pass

    async def _process_and_reply(self, update: Update, text: str, reason: str):
        """Process a query and send reply.

        For /commands (fin_command): route through finance skill.
        For everything else: send to DeepSeek LLM for a real conversation.
        When thinking is enabled: stream thinking into one message, then send response as another.

        Reaction lifecycle:
        👀 → message received, processing
        ✅ → response sent successfully
        ❌ → error occurred
        """
        msg = update.message

        # React 👀 = "seen, processing"
        await self._react(msg, "👀")

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
                    await self._react(msg, "✅")
                    return
            except Exception as e:
                await msg.reply_text(f"⚠️ Error: {e}")
                await self._react(msg, "❌")
                return

        # 1.5 Auto-fetch URLs in message → inject as LLM context
        if self._web_extractor and self._URL_RE.search(text):
            try:
                web_ctx = await self._auto_fetch_urls(text, msg.chat_id, msg.chat.type or "private")
                if web_ctx:
                    self._store.add_message(
                        msg.chat_id, "system", web_ctx,
                        msg.chat.type or "private",
                    )
                    logger.info(f"Auto-fetched URL content injected ({len(web_ctx)} chars)")
            except Exception as e:
                logger.debug(f"Auto-fetch failed: {e}")

        # 2. Everything else → send to DeepSeek LLM (always streaming)
        thinking = getattr(self, '_thinking_enabled', False)
        self._last_compact_notice = None
        cid = msg.chat_id
        ctype = msg.chat.type or "private"

        try:
            if thinking:
                await self._ask_llm_streaming(msg, text, chat_id=cid, chat_type=ctype)
            else:
                await self._ask_llm_stream_normal(msg, text, chat_id=cid, chat_type=ctype)

            # React ✅ = "done"
            await self._react(msg, "✅")
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            await msg.reply_text(f"⚠️ LLM 调用失败: {e}")
            await self._react(msg, "❌")
            return

        # Send context notice
        notice = getattr(self, '_last_compact_notice', None)
        if notice:
            await msg.reply_text(notice)
            self._last_compact_notice = None

        # Post-response check
        _, _, cur_model = self._resolve_api(thinking=thinking, chat_id=cid)
        post_notice = self._auto_compact_if_needed_db(cid, cur_model)
        if post_notice and "Auto-compacted" in post_notice:
            await msg.reply_text(post_notice)

    # ── LLM Shared Helpers ──────────────────────────────────────────

    # ── Auto-search augmentation ────────────────────────────────────

    # Hardcoded fallback patterns (used when YAML has no auto_search config)
    # NOTE: re.IGNORECASE is set at compile time — do NOT use (?i) inline flags
    #       here, because Python 3.11+ rejects (?i) when it's not at position 0
    #       of the entire combined pattern.
    _DEFAULT_SEARCH_PATTERNS = [
        # Chinese triggers
        r"最近|最新|今[天日]|昨[天日]|本[周月]|上[周月]|现在|目前|当前",
        r"新闻|消息|行情|走势|涨跌|收盘|开盘|盘[前后]",
        r"分析|研究|调研|比较|对比|评[测估价]|推荐|建议",
        r"搜[索一下]|查[一下找]|帮我[找查看搜]|有没有",
        r"IPO|上市|发[行布]|公[告布]",
        # English triggers (case handled by re.IGNORECASE flag)
        r"latest|recent|today|yesterday|this week|current|now",
        r"news|market|price|stock|crypto|earnings|report",
        r"search|find|look up|what happened|any updates",
        r"compare|analyze|research|recommend",
    ]

    def _build_search_trigger_re(self) -> re.Pattern:
        """Build the search trigger regex, merging YAML config + hardcoded patterns.

        Reads `auto_search.triggers` from the active mode's YAML config and
        combines them with the default patterns. This means you can add new
        trigger words simply by editing fin.yaml / chat.yaml — no code changes.
        """
        patterns = list(self._DEFAULT_SEARCH_PATTERNS)

        # Load extra triggers from YAML (all modes)
        try:
            from agent_config import AgentConfigManager
            for mode in ["fin", "chat", "coding"]:
                try:
                    cfg = AgentConfigManager(mode=mode)
                    raw = cfg._active if hasattr(cfg, '_active') else {}
                    auto_search = raw.get("auto_search", {})
                    yaml_triggers = auto_search.get("triggers", [])
                    if yaml_triggers:
                        # Escape each trigger word and combine with |
                        escaped = [re.escape(str(t)) for t in yaml_triggers]
                        patterns.append("|".join(escaped))
                except Exception:
                    continue
        except ImportError:
            pass

        # Load extra triggers from /tune overrides (persistent volume)
        if hasattr(self, '_config_editor'):
            override_triggers = self._config_editor.get_extra_search_triggers()
            if override_triggers:
                escaped = [re.escape(str(t)) for t in override_triggers]
                patterns.append("|".join(escaped))

        # Use re.IGNORECASE globally — never use (?i) inline in sub-patterns
        return re.compile("|".join(patterns), re.IGNORECASE)

    def _should_search(self, text: str) -> bool:
        """Decide if a user message would benefit from web search augmentation.

        Returns True for queries that ask about recent events, market data,
        news, or anything that needs up-to-date information beyond LLM training.
        Returns False for greetings, simple commands, meta questions, etc.

        Trigger patterns come from:
        1. Hardcoded defaults (_DEFAULT_SEARCH_PATTERNS)
        2. YAML config auto_search.triggers (editable without code changes)
        """
        # Skip very short messages (greetings, etc.)
        if len(text.strip()) < 6:
            return False
        # Skip if it's a command
        if text.strip().startswith("/"):
            return False

        # Lazy-init the compiled regex (built once, reused)
        if not hasattr(self, '_search_trigger_re'):
            self._search_trigger_re = self._build_search_trigger_re()

        return bool(self._search_trigger_re.search(text))

    async def _augment_with_search(self, query: str, chat_id: int = 0) -> tuple:
        """Run web search and return (context_str, source_footer).

        Returns:
            context_str: Text to inject as a system message before the user query.
                         Empty string if search failed or unavailable.
            source_footer: HTML footer like "🔍 Sources: DDG, Brave, GNews"
                           Empty string if no search was done.
        """
        search_engine = self.components.get("search") if self.components else None
        if not search_engine:
            return "", ""

        try:
            print(f"[auto-search] Searching: {query[:80]}", flush=True)
            # Hard timeout: if search takes >15s, skip it and let LLM answer without it
            try:
                result = await asyncio.wait_for(
                    search_engine.search(
                        query, max_results=8, extract_content=True, expand_queries=True,
                    ),
                    timeout=15.0,
                )
            except asyncio.TimeoutError:
                print("[auto-search] ⏱️ Timed out (15s), skipping", flush=True)
                return "", ""

            if not result or not result.items:
                print("[auto-search] No results", flush=True)
                return "", ""

            # Format results for LLM context
            lines = [
                f"[Web Search Results — {len(result.items)} results from {', '.join(result.sources_used)}]",
                "",
            ]
            for i, item in enumerate(result.items[:8], 1):
                tag = f"[{item.source}]" if item.source else ""
                lines.append(f"{i}. {tag} {item.title}")
                lines.append(f"   URL: {item.url}")
                if item.published:
                    lines.append(f"   Date: {item.published.strftime('%Y-%m-%d')}")
                content = item.full_text[:800] if item.full_text else item.snippet[:400]
                if content:
                    lines.append(f"   {content}")
                lines.append("")

            lines.append(
                "[INSTRUCTION: Use these search results to ground your response with real data. "
                "Cite sources when referencing specific facts. Do NOT fabricate information.]"
            )

            context_str = "\n".join(lines)

            # Build source footer for Telegram display
            src_names = sorted(set(result.sources_used))
            # Make short readable names
            name_map = {
                "ddg_en": "DDG", "ddg_zh": "DDG", "duckduckgo": "DDG",
                "gnews_en": "GNews", "gnews_zh": "GNews", "google_news_rss": "GNews",
                "brave": "Brave", "serper": "Serper", "tavily": "Tavily",
                "newsapi": "NewsAPI", "jina": "Jina", "searxng": "SearXNG",
                "rss": "RSS", "exa": "Exa", "youcom": "You.com",
                "perplexity": "Perplexity",
            }
            display_names = sorted(set(
                name_map.get(s, s) for s in src_names
            ))
            rerank_tag = " · reranked" if getattr(result, "reranked", False) else ""
            footer = f"\n\n<i>🔍 Sources: {', '.join(display_names)}{rerank_tag}</i>"

            print(f"[auto-search] ✅ {len(result.items)} results from {display_names}", flush=True)
            return context_str, footer

        except Exception as e:
            print(f"[auto-search] ❌ Error: {e}", flush=True)
            return "", ""

    def _get_system_prompt(self, chat_id: int = 0) -> str:
        """Load the full system prompt from YAML config for the chat's mode.

        Uses the same first-principles prompts as the CLI — not a simplified version.
        Appends Telegram-specific instructions and active sprint context at the end.
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

        # Search awareness: tell LLM it has auto-search
        search_engine = self.components.get("search") if self.components else None
        if search_engine:
            src_names = []
            for name in list(getattr(search_engine, 'tier1_sources', {}).keys()):
                src_names.append(name)
            for name in list(getattr(search_engine, 'tier2_sources', {}).keys()):
                src_names.append(name)
            for name in list(getattr(search_engine, 'tier3_sources', {}).keys()):
                src_names.append(name)
            sources_str = ", ".join(src_names) if src_names else "web"
            telegram_context += (
                "\n\nSEARCH CAPABILITY:\n"
                f"你拥有自动网络搜索能力（{sources_str}）。"
                "当用户提问涉及实时信息、最新数据、新闻、行情、或任何你训练数据可能过时的内容时，"
                "系统会自动搜索并将结果以 [Web Search Results] 的格式注入上下文。\n"
                "规则：\n"
                "- 如果上下文中有 [Web Search Results]，优先使用搜索结果中的数据，而非训练数据\n"
                "- 引用具体事实时标注来源（如 \"据 Reuters 报道\"）\n"
                "- 如果搜索结果与你的知识冲突，以搜索结果为准并说明差异\n"
                "- 如果搜索结果不够充分，明确告知用户并给出你的推理（标注为推理而非事实）\n"
                "- 绝不编造数据、价格、日期、百分比等数值信息\n"
            )

        # Self-tuning awareness
        telegram_context += (
            "\n\nSELF-TUNING CAPABILITY:\n"
            "你拥有自调优能力。用户可以通过 /tune 命令修改你的行为，修改即时生效无需重启。\n"
            "适用场景：\n"
            "- 如果用户对你的回复风格不满意（太长、太短、格式不对），主动建议：\"你可以用 /tune prompt <指令> 来调整我的回复风格\"\n"
            "- 如果用户反复问某类话题但搜索没触发，建议：\"你可以用 /tune trigger add <关键词> 让我自动搜索这类话题\"\n"
            "- 如果用户说\"记住这个偏好\"，用 /tune 来持久化\n"
            "示例：\n"
            "  /tune prompt 回复更简洁    — 追加 prompt 指令\n"
            "  /tune trigger add 半导体   — 添加搜索触发词\n"
            "  /tune status              — 查看当前自定义配置\n"
            "  /tune reset               — 恢复默认\n"
            "注意：不要每次都提 /tune，只在用户明确表达不满或要求调整时才建议。\n"
        )

        # Append active sprint context if sprint is active
        sprint_context = ""
        if self._sprint_mgr:
            try:
                for sid in self._sprint_mgr._active_sprints:
                    sprint = self._sprint_mgr._active_sprints.get(sid)
                    if sprint and sprint.status == "active":
                        prompt = self._sprint_mgr.get_sprint_prompt(sid)
                        if prompt:
                            sprint_context = f"\n\n{prompt}"
                        break
            except Exception as e:
                logger.debug(f"Failed to append sprint context: {e}")

        # Append user-defined prompt overrides (from /tune)
        extra_prompt = ""
        if hasattr(self, '_config_editor'):
            extra = self._config_editor.get_extra_prompt(current_mode)
            if extra:
                extra_prompt = f"\n\nUSER CUSTOMIZATIONS:\n{extra}"

        # Append tool definitions from canonical agentic layer
        tool_prompt = ""
        try:
            agentic = self._get_agentic_loop()
            if agentic:
                tool_prompt = "\n\n" + agentic.get_tool_prompt()
        except Exception as e:
            logger.debug(f"Failed to generate tool prompt: {e}")

        return base_prompt + telegram_context + sprint_context + extra_prompt + tool_prompt

    # Context window limits per model
    _MODEL_CONTEXT = {
        "deepseek-chat": 128000,
        "deepseek-reasoner": 128000,
        "glm-5": 205000,
        "glm-4.5-flash": 128000,
        "kimi-k2.5": 131072,
        "moonshot-v1-128k": 131072,
    }

    def _get_history(self, chat_id: int = 0) -> list:
        """Get recent history from SQLite for a specific chat.

        Returns a mutable list (callers may modify for compact).
        """
        return self._store.get_recent_history(chat_id, limit=20)

    # ── Per-mode preferred provider mapping ──────────────────────
    # Maps agent mode → provider name that should be tried first.
    # If the preferred provider is in the chain, it gets promoted to index 0.
    _MODE_PREFERRED_PROVIDER = {
        "fin": "moonshot",      # Kimi K2.5 for financial reasoning
        "coding": "deepseek",   # DeepSeek for coding
        "chat": "deepseek",     # DeepSeek for general chat
    }

    def _resolve_api(self, thinking: bool = False, chat_id: int = 0) -> tuple:
        """Returns (api_key, base_url, model) — picks first available provider.

        When chat_id is given:
        1. Checks for per-chat model override (from /switch)
        2. Otherwise re-orders chain by mode's preferred provider
        """
        # Check per-chat model override first
        if chat_id:
            override = self._store.get_model_override(chat_id)
            if override:
                from agent.services.llm_provider import PROVIDERS
                for pname, pconf in PROVIDERS.items():
                    for m in pconf.get("fallback_models", []):
                        if m["id"] == override:
                            env_key = pconf.get("env_key", "")
                            api_key = os.getenv(env_key, "") if env_key else ""
                            if api_key:
                                return api_key, pconf["base_url"], override
                            break

        # Fallback to normal provider chain
        chain = self._get_provider_chain(thinking, chat_id=chat_id)
        if chain:
            p = chain[0]
            return p["api_key"], p["base_url"], p["model"]
        return "", "", ""

    def _get_agentic_loop(self):
        """Lazily initialize the canonical agentic loop with tool registry."""
        if not hasattr(self, '_agentic_loop') or self._agentic_loop is None:
            try:
                from agent.agentic import AgenticLoop, AgenticConfig
                from agent.coding.tools import ToolRegistry
                registry = ToolRegistry(working_dir="/app")
                config = AgenticConfig(
                    max_iterations=5,    # Conservative for Telegram
                    soft_limit=3,
                )
                self._agentic_loop = AgenticLoop(registry, config)
            except Exception as e:
                logger.warning(f"Failed to init agentic loop: {e}")
                self._agentic_loop = None
        return self._agentic_loop

    def _get_provider_chain(self, thinking: bool = False, chat_id: int = 0) -> list:
        """Build ordered list of providers to try (primary → fallback).

        Delegates to ProviderStateManager, then re-orders based on the
        chat's current mode so the preferred provider comes first.
        """
        chain = self._state_mgr.get_provider_chain("neomind", thinking=thinking)

        # Re-order chain based on per-chat mode preference
        if chat_id:
            mode = self._store.get_mode(chat_id)
        else:
            mode = "fin"  # default for Telegram bot
        preferred = self._MODE_PREFERRED_PROVIDER.get(mode)
        if preferred and len(chain) > 1:
            # Move preferred provider to front, keep rest as fallback
            preferred_items = [p for p in chain if p["name"] == preferred]
            others = [p for p in chain if p["name"] != preferred]
            if preferred_items:
                chain = preferred_items + others

        return chain

    def _publish_mode_models_to_state(self):
        """Write per-mode model routing + available providers to state file.

        Called once at startup so xbar can dynamically display model info
        without hardcoding. Re-called whenever provider config changes.
        """
        try:
            # Build mode→model mapping from _MODE_PREFERRED_PROVIDER + provider chain
            mode_models = {}
            for mode, preferred_provider in self._MODE_PREFERRED_PROVIDER.items():
                # Get the chain as if this mode were active
                chain = self._state_mgr.get_provider_chain("neomind", thinking=False)
                think_chain = self._state_mgr.get_provider_chain("neomind", thinking=True)

                # Find the preferred provider's models
                normal_model = None
                think_model = None
                for p in chain:
                    if p["name"] == preferred_provider:
                        normal_model = p["model"]
                        break
                for p in think_chain:
                    if p["name"] == preferred_provider:
                        think_model = p["model"]
                        break

                # Fallback to first in chain
                if not normal_model and chain:
                    normal_model = chain[0]["model"]
                    preferred_provider = chain[0]["name"]
                if not think_model and think_chain:
                    think_model = think_chain[0]["model"]

                mode_models[mode] = {
                    "provider": preferred_provider,
                    "model": normal_model or "?",
                    "thinking_model": think_model or "?",
                }

            self._state_mgr.update_mode_models("neomind", mode_models, updated_by="bot_startup")

            # Also publish available providers list
            all_chain = self._state_mgr.get_provider_chain("neomind", thinking=False)
            providers = [{"name": p["name"], "model": p["model"]} for p in all_chain]
            self._state_mgr.update_available_providers("neomind", providers)

            print(f"[bot] Published mode_models to state: {list(mode_models.keys())}", flush=True)
        except Exception as e:
            print(f"[bot] Warning: failed to publish mode_models: {e}", flush=True)

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
        api_key, base_url, model = self._resolve_api(thinking=False, chat_id=chat_id)
        compact_notice = self._auto_compact_if_needed_db(chat_id, model)

        messages = [{"role": "system", "content": self._get_system_prompt(chat_id)}] + history

        # Auto-search augmentation for non-streaming mode
        search_footer = ""
        if self._should_search(user_message):
            search_ctx, search_footer = await self._augment_with_search(user_message, chat_id)
            if search_ctx:
                messages.insert(-1, {"role": "system", "content": search_ctx})

        if not api_key:
            return "⚠️ No API key configured (DEEPSEEK_API_KEY, ZAI_API_KEY, or MOONSHOT_API_KEY)"

        # Build provider chain: primary → fallback (mode-aware ordering)
        providers = self._get_provider_chain(thinking=False, chat_id=chat_id)

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

                    # Log to evidence trail
                    if self._evidence_trail:
                        self._evidence_trail.log(
                            "llm_call",
                            f"{provider['model']}: {user_message[:100]}",
                            f"Generated {len(reply)} chars in {latency}ms",
                            mode=self._store.get_mode(chat_id),
                            severity="info"
                        )

                    self._store.add_message(chat_id, "assistant", reply, chat_type)
                    self._last_compact_notice = compact_notice
                    if provider != providers[0]:
                        reply += f"\n\n<i>⚡ via {provider['model']} (primary unavailable)</i>"
                    if search_footer:
                        reply += search_footer
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
        error_msg = f"⚠️ 所有 API 均失败:\n{err_summary}\n\n<i>/provider 查看配置 · /usage 查看统计</i>"

        # Log failure to evidence
        if self._evidence_trail:
            self._evidence_trail.log(
                "llm_error",
                user_message[:100],
                err_summary,
                mode=self._store.get_mode(chat_id),
                severity="critical"
            )

        return error_msg

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

        # Context management (mode-aware provider ordering)
        providers = self._get_provider_chain(thinking=False, chat_id=chat_id)
        if not providers:
            await msg.reply_text("⚠️ No API key configured")
            return

        model = providers[0]["model"]
        compact_notice = self._auto_compact_if_needed_db(chat_id, model)
        messages = [{"role": "system", "content": self._get_system_prompt(chat_id)}] + history

        if compact_notice:
            self._last_compact_notice = compact_notice

        # Auto-search augmentation: inject web results if the query warrants it
        search_footer = ""
        if self._should_search(user_message):
            search_ctx, search_footer = await self._augment_with_search(user_message, chat_id)
            if search_ctx:
                # Insert search context as a system message right before the user's last message
                messages.insert(-1, {"role": "system", "content": search_ctx})

        # Send placeholder
        live_msg = await msg.reply_text("💭 ...")

        response_text = ""
        last_edit_time = 0
        EDIT_INTERVAL = 2.5  # Conservative: ~24 edits/min, well under Telegram's limit

        try:
            # Try providers in order
            response = None
            used_provider = None
            for provider in providers:
                try:
                    print(f"[llm-stream] Trying {provider['name']}:{provider['model']} → {provider['base_url'][:80]}", flush=True)
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
                        continue  # try next provider
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

                    # Periodically edit the live message (stop editing once near limit,
                    # but KEEP collecting tokens — never break the stream loop)
                    now = asyncio.get_event_loop().time()
                    if ct and (now - last_edit_time) >= EDIT_INTERVAL and len(response_text) <= 3900:
                        last_edit_time = now
                        # Strip any partial/complete <tool_call> blocks before display
                        _display_text = re.sub(
                            r'</?tool_(?:call|result)>',  '', response_text
                        )
                        _display_text = re.sub(
                            r'<tool_call>.*?</tool_(?:call|result)>', '', _display_text, flags=re.DOTALL
                        )
                        _display_text = _display_text.strip()
                        if not _display_text:
                            _display_text = "⚙️ 正在思考..."
                        display = self._md_to_html(_display_text)
                        await self._safe_edit(
                            live_msg,
                            display + " ▍",
                            max_retries=0,  # don't retry during streaming, just skip
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )

                except (json.JSONDecodeError, IndexError, KeyError):
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

                # Small delay before final edit — avoid rate-limit from last streaming edit
                await asyncio.sleep(0.3)

                # Final update: edit the live message with complete text
                # Strip any <tool_call> blocks so raw XML never shows to user
                _final_text = re.sub(
                    r'<tool_call>.*?</tool_(?:call|result)>', '', response_text.strip(), flags=re.DOTALL
                )
                _final_text = re.sub(r'</?tool_(?:call|result)>', '', _final_text).strip()
                final_html = self._md_to_html(_final_text or "⚙️ 正在执行工具...")
                if search_footer:
                    final_html += search_footer

                # Also prepare a plain-text version (guaranteed safe for Telegram)
                plain_text = re.sub(r'<[^>]+>', '', final_html)

                if len(final_html) <= self.config.max_message_length:
                    edited_ok = False
                    try:
                        await live_msg.edit_text(
                            final_html,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )
                        edited_ok = True
                    except Exception as e:
                        logger.warning(f"Final HTML edit failed: {e}")
                        try:
                            await live_msg.edit_text(
                                plain_text[:self.config.max_message_length],
                                disable_web_page_preview=True,
                            )
                            edited_ok = True
                        except Exception as e2:
                            logger.warning(f"Final plain edit also failed: {e2}")

                    # Last resort: if edit failed, send fresh THEN delete old
                    if not edited_ok:
                        await self._send_long_message(msg, response_text.strip(), html_suffix=search_footer)
                        try:
                            await live_msg.delete()
                        except Exception:
                            pass

                elif len(plain_text) <= self.config.max_message_length:
                    # HTML is too long but plain text fits in one message
                    try:
                        await live_msg.edit_text(
                            plain_text,
                            disable_web_page_preview=True,
                        )
                    except Exception as e:
                        logger.warning(f"Plain edit failed: {e}")
                        sent = await self._safe_send(msg, plain_text, disable_web_page_preview=True)
                        if sent:
                            try:
                                await live_msg.delete()
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
                        plain_chunk = re.sub(r'<[^>]+>', '', chunks[0])
                        try:
                            await live_msg.edit_text(
                                plain_chunk[:self.config.max_message_length],
                                disable_web_page_preview=True,
                            )
                        except Exception as e:
                            logger.warning(f"Chunk[0] edit failed: {e}")
                            # Send everything as new messages THEN delete old
                            await self._send_long_message(msg, response_text.strip(), html_suffix=search_footer)
                            try:
                                await live_msg.delete()
                            except Exception:
                                pass
                            chunks = []  # Skip remaining chunk loop

                    for i, chunk in enumerate(chunks[1:], 1):
                        await asyncio.sleep(0.5)
                        try:
                            await msg.reply_text(chunk, parse_mode=ParseMode.HTML,
                                                 disable_web_page_preview=True)
                        except Exception:
                            plain_chunk = re.sub(r'<[^>]+>', '', chunk)
                            try:
                                await msg.reply_text(
                                    plain_chunk[:self.config.max_message_length],
                                    disable_web_page_preview=True,
                                )
                            except Exception as e:
                                logger.error(f"Failed to send chunk {i+1}/{len(chunks)}: {e}")
            else:
                await live_msg.edit_text("⚠️ LLM 未生成回复")

        except Exception as e:
            logger.error(f"Stream error: {e}")
            try:
                await live_msg.edit_text(f"⚠️ Error: {e}")
            except Exception:
                await msg.reply_text(f"⚠️ Error: {e}")

        # ── Agentic loop: if response contains tool calls, execute them ──
        if response_text and '<tool_call>' in response_text and used_provider:
            print(f"[agentic] Detected <tool_call> in response ({len(response_text)} chars), starting agentic loop", flush=True)
            # Clean the displayed message: strip the raw <tool_call> block
            # so the user sees only the natural language part
            import re as _re
            clean_text = _re.sub(
                r'<tool_call>.*?</tool_(?:call|result)>', '', response_text, flags=_re.DOTALL
            ).strip()
            if clean_text:
                try:
                    await live_msg.edit_text(
                        self._md_to_html(clean_text),
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                except Exception:
                    try:
                        await live_msg.edit_text(clean_text[:4000], disable_web_page_preview=True)
                    except Exception:
                        pass
            else:
                try:
                    await live_msg.edit_text("⚙️ 正在执行工具...")
                except Exception:
                    pass

            await self._run_agentic_tool_loop(
                msg, response_text.strip(), chat_id, chat_type, used_provider,
            )
        elif response_text and used_provider:
            # Check for "dangling intent": LLM said it would do something but didn't
            # output a tool call. Auto-nudge it to actually execute.
            stripped = response_text.strip()
            dangling = stripped.endswith(('：', ':', '…', '...')) and any(
                kw in stripped for kw in ('让我', '我来', '检查', '查看', '创建', '执行', '读取')
            )
            if dangling:
                print(f"[agentic] Detected dangling intent (no tool_call), nudging LLM", flush=True)
                import requests as _req
                provider = used_provider
                history = self._store.get_recent_history(chat_id, limit=20)
                nudge_messages = (
                    [{"role": "system", "content": self._get_system_prompt(chat_id)}]
                    + history
                    + [{"role": "user", "content": "继续。请直接用 <tool_call> 执行你刚才说要做的操作。"}]
                )
                try:
                    nudge_resp = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: _req.post(
                            provider["base_url"],
                            headers={"Authorization": f"Bearer {provider['api_key']}",
                                     "Content-Type": "application/json"},
                            json={"model": provider["model"], "messages": nudge_messages,
                                  "max_tokens": 4096, "temperature": 0.7},
                            timeout=90,
                        ))
                    if nudge_resp.status_code == 200:
                        nudge_text = nudge_resp.json()["choices"][0]["message"]["content"]
                        if '<tool_call>' in nudge_text:
                            print(f"[agentic] Nudge produced tool_call, executing", flush=True)
                            self._store.add_message(chat_id, "assistant", nudge_text.strip(), chat_type)
                            await self._run_agentic_tool_loop(
                                msg, nudge_text.strip(), chat_id, chat_type, provider,
                            )
                        else:
                            # LLM still refused to use tools — send its text response
                            nudge_clean = nudge_text.strip()
                            if nudge_clean:
                                self._store.add_message(chat_id, "assistant", nudge_clean, chat_type)
                                await self._send_long_message(msg, nudge_clean)
                except Exception as e:
                    logger.debug(f"Nudge failed: {e}")

    async def _run_agentic_tool_loop(
        self, msg, initial_response: str,
        chat_id: int, chat_type: str, provider: dict,
    ):
        """Run the canonical agentic loop when LLM response contains tool calls.

        Executes tools, feeds results back to LLM, sends new responses as
        Telegram messages. This makes NeoMind's tool calling work across
        all frontends, not just CLI.
        """
        import requests as req

        agentic = self._get_agentic_loop()
        if not agentic:
            await msg.reply_text("⚠️ Agentic loop not available")
            return

        # Build messages from history
        history = self._store.get_recent_history(chat_id, limit=20)
        messages = [{"role": "system", "content": self._get_system_prompt(chat_id)}] + history

        # LLM caller: synchronous, uses streaming API to collect tokens faster
        # but does NOT do real-time Telegram edits (avoids thread/event-loop deadlock).
        def llm_caller(msgs):
            full_text = ""
            resp = req.post(
                provider["base_url"],
                headers={
                    "Authorization": f"Bearer {provider['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": provider["model"],
                    "messages": msgs,
                    "max_tokens": 4096,
                    "temperature": 0.7,
                    "stream": True,
                },
                timeout=90,
                stream=True,
            )
            if resp.status_code != 200:
                raise Exception(f"LLM API error: {resp.status_code}")

            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    ct = delta.get("content", "")
                    if ct:
                        full_text += ct
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

            if not full_text.strip():
                # Fallback to non-streaming if stream returned empty
                resp2 = req.post(
                    provider["base_url"],
                    headers={
                        "Authorization": f"Bearer {provider['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": provider["model"],
                        "messages": msgs,
                        "max_tokens": 4096,
                        "temperature": 0.7,
                    },
                    timeout=90,
                )
                if resp2.status_code == 200:
                    full_text = resp2.json()["choices"][0]["message"]["content"]

            return full_text

        # Run agentic loop
        import html as _html
        import re as _re
        try:
            _tool_status_msg = None  # Reusable status message per tool cycle

            for event in agentic.run(initial_response, messages, llm_caller):
                if event.type == "tool_start":
                    # Send a live status message — will be edited when result arrives
                    tool_label = _html.escape(event.tool_preview or event.tool_name or "tool")
                    status_html = f"⏳ <b>{tool_label}</b>  运行中…"
                    try:
                        _tool_status_msg = await msg.reply_text(
                            status_html, parse_mode=ParseMode.HTML,
                        )
                    except Exception:
                        _tool_status_msg = await msg.reply_text(
                            f"⏳ {event.tool_preview or event.tool_name}  运行中…"
                        )

                elif event.type == "tool_result":
                    full_output = event.result_output or ""

                    if event.result_success:
                        icon = "✅"
                        name = _html.escape(event.tool_name or "tool")

                        if not full_output.strip():
                            # Empty output — just show success
                            result_html = f"{icon} <b>{name}</b>: done"
                        elif len(full_output) <= 80:
                            # Very short — show inline
                            result_html = f"{icon} <b>{name}</b>: {_html.escape(full_output)}"
                        else:
                            # Longer output — foldable blockquote
                            escaped = _html.escape(full_output[:3500])
                            result_html = (
                                f"{icon} <b>{name}</b>\n"
                                f"<blockquote expandable>{escaped}</blockquote>"
                            )
                    else:
                        icon = "❌"
                        name = _html.escape(event.tool_name or "tool")
                        err = _html.escape((event.result_error or "failed")[:500])
                        result_html = f"{icon} <b>{name}</b>: {err}"

                    # Try to edit the status message in-place; fall back to new message
                    sent = False
                    if _tool_status_msg:
                        try:
                            await _tool_status_msg.edit_text(
                                result_html, parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True,
                            )
                            sent = True
                        except Exception:
                            pass  # edit failed, send new message below

                    if not sent:
                        try:
                            await msg.reply_text(
                                result_html, parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True,
                            )
                        except Exception:
                            # Last resort: plain text
                            preview = (full_output or event.result_error or "done")[:300]
                            await msg.reply_text(f"{'✅' if event.result_success else '❌'} {event.tool_name}: {preview}"[:4000])

                    _tool_status_msg = None  # Reset for next tool cycle

                    # Persist tool feedback to store
                    if event.feedback_message:
                        self._store.add_message(chat_id, "user", event.feedback_message, chat_type)

                elif event.type == "llm_response":
                    if event.llm_text:
                        self._store.add_message(chat_id, "assistant", event.llm_text.strip(), chat_type)
                        # Strip <tool_call> blocks before sending to user
                        _clean_llm = _re.sub(
                            r'<tool_call>.*?</tool_(?:call|result)>', '', event.llm_text.strip(), flags=_re.DOTALL
                        )
                        _clean_llm = _re.sub(r'</?tool_(?:call|result)>', '', _clean_llm).strip()
                        if _clean_llm:
                            await self._send_long_message(msg, _clean_llm)

                elif event.type == "error":
                    await msg.reply_text(f"⚠️ Agentic error: {event.error_message}")

                elif event.type == "done":
                    break

        except Exception as e:
            logger.error(f"Agentic loop error: {e}", exc_info=True)
            await msg.reply_text(f"⚠️ Tool execution error: {e}")

    # ── Thinking mode: streaming with live Telegram message updates ──

    async def _ask_llm_streaming(self, msg, user_message: str,
                                 chat_id: int = 0, chat_type: str = "private"):
        """Streaming LLM call with thinking. Used when /think is ON."""
        import requests as req

        # Save user message to persistent store
        self._store.add_message(chat_id, "user", user_message, chat_type)

        # Load recent history from DB
        history = self._store.get_recent_history(chat_id, limit=20)

        # Context management (mode-aware provider ordering)
        providers = self._get_provider_chain(thinking=True, chat_id=chat_id)
        if not providers:
            await msg.reply_text("⚠️ No API key configured")
            return

        model = providers[0]["model"]
        compact_notice = self._auto_compact_if_needed_db(chat_id, model)
        messages = [{"role": "system", "content": self._get_system_prompt(chat_id)}] + history

        # Auto-search augmentation for thinking mode
        search_footer = ""
        if self._should_search(user_message):
            search_ctx, search_footer = await self._augment_with_search(user_message, chat_id)
            if search_ctx:
                messages.insert(-1, {"role": "system", "content": search_ctx})

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
        EDIT_INTERVAL = 2.5  # Conservative: ~24 edits/min, well under Telegram's limit

        try:
            # Step 2: Stream the response (try providers in order)
            response = None
            used_provider = None
            for provider in providers:
                try:
                    print(f"[llm-think] Trying {provider['name']}:{provider['model']} → {provider['base_url'][:50]}", flush=True)
                    response = await asyncio.get_event_loop().run_in_executor(None, lambda p=provider: req.post(
                        p["base_url"],
                        headers={"Authorization": f"Bearer {p['api_key']}", "Content-Type": "application/json"},
                        json={"model": p["model"], "messages": messages, "max_tokens": 4096, "stream": True},
                        timeout=120,
                        stream=True,
                    ))
                    if response.status_code == 200:
                        used_provider = provider
                        print(f"[llm-think] ✅ Connected to {provider['name']}:{provider['model']}", flush=True)
                        break
                    else:
                        print(f"[llm-think] ❌ {provider['name']} returned {response.status_code}", flush=True)
                        continue  # try next provider
                except Exception as e:
                    print(f"[llm-think] ❌ {provider['name']} error: {e}", flush=True)
                    continue  # try next provider

            if not response or response.status_code != 200:
                status = response.status_code if response else "all timed out"
                await thinking_msg.edit_text(f"⚠️ API error: {status}")
                return

            # Step 3: Process SSE stream via queue (non-blocking)
            # iter_lines() is synchronous and blocks the event loop,
            # so we run it in a thread and feed chunks through a queue.
            queue = asyncio.Queue()

            def _stream_reader(resp, q):
                """Read SSE lines in a thread, push parsed deltas to queue."""
                try:
                    for raw_line in resp.iter_lines():
                        if not raw_line:
                            continue
                        line = raw_line.decode("utf-8", errors="ignore")
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            rc = delta.get("reasoning_content", "")
                            ct = delta.get("content", "")
                            if rc or ct:
                                q.put_nowait(("chunk", rc, ct))
                        except (json.JSONDecodeError, IndexError, KeyError):
                            continue
                except Exception:
                    pass
                q.put_nowait(("done", "", ""))

            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, _stream_reader, response, queue)

            # Consume chunks from queue, update Telegram message periodically
            while True:
                try:
                    kind, rc, ct = await asyncio.wait_for(queue.get(), timeout=120)
                except asyncio.TimeoutError:
                    break
                if kind == "done":
                    break
                if rc:
                    thinking_text += rc
                if ct:
                    response_text += ct

                # Periodically update the thinking message
                now = time.time()
                if rc and (now - last_edit_time) >= EDIT_INTERVAL:
                    last_edit_time = now
                    display = self._format_thinking(thinking_text)
                    await self._safe_edit(
                        thinking_msg,
                        display,
                        max_retries=0,  # don't retry during streaming, just skip
                        parse_mode=ParseMode.HTML,
                    )

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

            # Log completion
            pname = used_provider['name'] if used_provider else '?'
            pmodel = used_provider['model'] if used_provider else '?'
            print(f"[llm-think] ✅ {pname}:{pmodel} done (think:{len(thinking_text)} chars, reply:{len(response_text)} chars)", flush=True)

            # Step 5: Send final response as a separate message
            if response_text.strip():
                self._store.add_message(
                    chat_id, "assistant", response_text.strip(), chat_type,
                    thinking=thinking_text,
                )
                await self._send_long_message(msg, response_text.strip(),
                                               html_suffix=search_footer)
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

        During streaming (final=False): shows the last 3800 chars (live preview).
        Final message (final=True): keeps full text — caller is responsible for
        splitting into multiple messages if the result exceeds 4096 chars.
        """
        header = "🧠 <b>Thinking</b>" if final else "🧠 <b>Thinking...</b>"

        if not final:
            # Live preview: truncate to tail (only most recent thinking matters)
            max_len = 3800
            if len(text) > max_len:
                text = text[-max_len:]
                text = "…\n" + text

        escaped = html.escape(text)
        result = f"{header}\n<blockquote expandable>{escaped}</blockquote>"

        if final and len(result) > 4096:
            # Telegram limit: truncate to last N chars that fit
            # Overhead = header + tags ≈ 80 chars
            overhead = len(header) + len("\n<blockquote expandable>") + len("</blockquote>")
            usable = 4096 - overhead - 10  # 10 chars safety margin
            if usable > 0:
                truncated = text[-usable:]
                truncated = "…(thinking truncated)\n" + truncated
                escaped = html.escape(truncated)
                result = f"{header}\n<blockquote expandable>{escaped}</blockquote>"

        return result

    @staticmethod
    async def _safe_edit(message, text: str, max_retries: int = 2, **kwargs):
        """Edit a message with RetryAfter handling. Returns True on success."""
        for attempt in range(max_retries + 1):
            try:
                await message.edit_text(text, **kwargs)
                return True
            except RetryAfter as e:
                if attempt < max_retries:
                    wait = min(e.retry_after + 1, 30)
                    logger.info(f"Telegram rate limit, waiting {wait}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait)
                else:
                    logger.warning(f"RetryAfter exhausted after {max_retries} retries")
                    return False
            except Exception as e:
                logger.warning(f"Edit failed: {e}")
                return False
        return False

    @staticmethod
    async def _safe_send(msg, text: str, max_retries: int = 2, **kwargs):
        """Send a message with RetryAfter handling. Returns the sent message or None."""
        for attempt in range(max_retries + 1):
            try:
                return await msg.reply_text(text, **kwargs)
            except RetryAfter as e:
                if attempt < max_retries:
                    wait = min(e.retry_after + 1, 30)
                    logger.info(f"Telegram rate limit, waiting {wait}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait)
                else:
                    logger.warning(f"RetryAfter exhausted after {max_retries} retries")
                    return None
            except Exception as e:
                logger.warning(f"Send failed: {e}")
                return None
        return None

    async def _send_long_message(self, msg, text: str, html_suffix: str = ""):
        """Send a message, splitting if it exceeds Telegram's 4096 char limit.

        - Converts markdown to Telegram HTML (with proper escaping)
        - Splits long messages at safe boundaries
        - Falls back to plain text per-chunk if HTML fails
        - Adds small delay between chunks to avoid Telegram rate limits

        Args:
            html_suffix: Pre-formatted HTML to append AFTER md→html conversion
                         (e.g., search source footer). Won't be escaped.
        """
        # Convert markdown-style links to HTML
        text = self._md_to_html(text)
        if html_suffix:
            text += html_suffix

        if len(text) <= self.config.max_message_length:
            sent = await self._safe_send(
                msg, text, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            if not sent:
                logger.warning("HTML send failed, retrying as plain text")
                plain = re.sub(r'<[^>]+>', '', text)
                await self._safe_send(msg, plain, disable_web_page_preview=True)
        else:
            # Split into chunks
            chunks = self._split_message(text)
            for i, chunk in enumerate(chunks):
                sent = await self._safe_send(
                    msg, chunk, parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                if not sent:
                    logger.warning(f"HTML chunk {i+1}/{len(chunks)} failed, sending plain")
                    plain = re.sub(r'<[^>]+>', '', chunk)
                    await self._safe_send(msg, plain, disable_web_page_preview=True)
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
