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
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("neomind.telegram")


def _safe_temperature(model: str, default: float = 0.7) -> float:
    """Return a temperature value the upstream provider will accept.

    Some routed models reject anything other than 1.0 (e.g. kimi-k2.5).
    Centralised here so every chat-completion call site stays consistent.
    """
    if not model:
        return default
    m = model.lower()
    if m.startswith("kimi"):
        return 1.0
    return default

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

    def _is_command_for_me(self, update) -> bool:
        """Check if a /command in a group chat is directed at this bot.

        In group chats, bare /commands (without @bot_username suffix) are
        ambiguous when multiple bots are present. This method returns False
        for commands not directed at us, so we can silently ignore them.

        In private chats, all commands are always for us.
        """
        msg = update.message
        if not msg or not msg.text:
            return True
        # Private chat — always ours
        if msg.chat.type == "private":
            return True
        # Group chat: check if command has @username suffix
        text = msg.text.split()[0]  # e.g. "/model@your_neomind_bot"
        if "@" in text:
            # Explicit target — check if it's us
            target = text.split("@", 1)[1].lower()
            return target == (self.config.bot_username or "").lower()
        # No @suffix: only respond if we're the only bot, or if the message
        # is a reply to one of our messages
        if msg.reply_to_message and msg.reply_to_message.from_user:
            return msg.reply_to_message.from_user.id == self._bot_id
        # Bare command in group with no reply context — ignore to avoid conflicts
        return False

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

        # ── Canary user whitelist (group -1 pre-handler) ──────────────
        # When NEOMIND_CANARY=1 is set, silently drop any update whose
        # sender is NOT in the canary allow-list. Prevents random users
        # from discovering the canary bot (@your_canary_bot_example)
        # and burning LLM tokens against the owner's Moonshot/DeepSeek
        # account. The production bot (no NEOMIND_CANARY env) is
        # unaffected — it still accepts any private-chat DM per the
        # MessageRouter.should_respond() logic.
        #
        # Allow-list resolution order:
        #   1. NEOMIND_CANARY_ALLOWED_USERS — comma-separated user IDs
        #      dedicated to canary. Recommended for production use so
        #      the canary can whitelist the Telethon tester account
        #      without granting it /admin on production.
        #   2. TELEGRAM_ADMIN_USERS — fallback for simple setups.
        if os.getenv("NEOMIND_CANARY", "").strip() == "1":
            from telegram.ext import TypeHandler, ApplicationHandlerStop

            _canary_allowed_raw = os.getenv("NEOMIND_CANARY_ALLOWED_USERS", "").strip()
            if _canary_allowed_raw:
                admin_set = {
                    int(x) for x in _canary_allowed_raw.split(",")
                    if x.strip().isdigit()
                }
                _source = "NEOMIND_CANARY_ALLOWED_USERS"
            else:
                admin_set = set(self.config.admin_users)
                _source = "TELEGRAM_ADMIN_USERS (fallback)"
            if not admin_set:
                print("[bot] ⚠️ NEOMIND_CANARY=1 but no allow-list configured "
                      "— canary will reject ALL messages including yours. "
                      "Set NEOMIND_CANARY_ALLOWED_USERS or TELEGRAM_ADMIN_USERS "
                      "in .env.", flush=True)

            async def _canary_admin_gate(update, context):
                # Let internal update types (edited_message, channel_post,
                # etc.) fall through — they rarely carry useful sender info.
                msg = getattr(update, "message", None) or getattr(update, "edited_message", None)
                if msg is None or msg.from_user is None:
                    raise ApplicationHandlerStop  # drop
                user_id = msg.from_user.id
                if user_id not in admin_set:
                    # Silent drop — no reply, no log spam. Attacker
                    # discovering the bot just gets silence.
                    raise ApplicationHandlerStop
                # Admin user — allow normal handler chain to run.

            # Group -1 runs before everything else. Raising
            # ApplicationHandlerStop aborts the whole update dispatch.
            self._app.add_handler(
                TypeHandler(Update, _canary_admin_gate),
                group=-1,
            )
            print(
                f"[bot] 🛡 NEOMIND_CANARY=1: whitelist active "
                f"({len(admin_set)} user(s) from {_source})",
                flush=True,
            )

        # Register handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("mode", self._cmd_mode))
        self._app.add_handler(CommandHandler("think", self._cmd_think))
        self._app.add_handler(CommandHandler("history", self._cmd_history))
        self._app.add_handler(CommandHandler("clear", self._cmd_clear))
        self._app.add_handler(CommandHandler("admin", self._cmd_admin))
        self._app.add_handler(CommandHandler("context", self._cmd_context))
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
        self._app.add_handler(CommandHandler("evolve", self._cmd_evolve))
        # Web commands: /read, /links, /crawl
        self._app.add_handler(CommandHandler("read", self._cmd_web_read))
        self._app.add_handler(CommandHandler("links", self._cmd_web_links))
        self._app.add_handler(CommandHandler("crawl", self._cmd_web_crawl))

        # Catch all /neo_* commands
        self._app.add_handler(MessageHandler(
            filters.Regex(r'^/neo[_ ]') & ~filters.COMMAND, self._handle_message
        ))
        # Catch finance slash commands (routed to openclaw_skill or LLM agentic
        # loop). /memory removed — it had no real handler. Other loop entries
        # will be migrated to thin wrappers over finance_* tools in Phase B.
        for cmd in ["stock", "crypto", "news", "digest", "compute", "portfolio",
                     "predict", "alert", "compare", "watchlist", "risk",
                     "sources", "chart", "calendar"]:
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

        # ── Post-restart evolution verification ──────────────────────
        # If the last startup was a self-evolution restart, re-import every
        # applied module in THIS process to prove the new code loads cleanly.
        # On failure we git-reset-hard to the rollback tag and schedule
        # another supervisorctl restart BEFORE Telegram polling begins —
        # so users never see a broken version of the bot respond to a
        # message. Stash the result for _check_restart_intent to notify.
        self._evolution_verify_result: Optional[Tuple[Dict[str, Any], str]] = None
        try:
            from agent.evolution.post_restart_verify import verify_pending_evolution
            intent, verify_status = verify_pending_evolution()
            if intent is not None:
                self._evolution_verify_result = (intent, verify_status)
                if verify_status == "rolled_back":
                    logger.warning(
                        "[bot] Evolution verification FAILED; rollback scheduled. "
                        "Polling will start on the next supervised restart with original code."
                    )
                    print(
                        "[bot] ⚠️ evolution rolled back — waiting for recovery restart",
                        flush=True,
                    )
                    # Stay up briefly so the user notification can be sent,
                    # but do NOT start Telegram polling — supervisord will
                    # replace this process any moment now.
                    await asyncio.sleep(5)
                    return
                if verify_status == "rollback_failed":
                    logger.critical(
                        "[bot] Evolution verification AND rollback both failed. "
                        "Refusing to start Telegram polling — manual recovery required."
                    )
                    print(
                        "[bot] 🚨 CRITICAL: evolution + rollback both failed — "
                        "not starting polling. See /data/neomind/evolution/ for the intent file.",
                        flush=True,
                    )
                    return
                logger.info(f"[bot] Evolution verification PASSED: {intent.get('tag')}")
        except Exception as e:
            logger.error(f"[bot] Post-restart verifier crashed: {e}", exc_info=True)

        # Register command menu in Telegram (visible in autocomplete).
        # Only Tier 1 (user-facing meta) + Tier 2 (fin quick-access) are
        # shown here. Admin / advanced commands (Tier 4) still work when
        # typed but are hidden from the autocomplete to keep the menu clean.
        from telegram import BotCommand
        await self._app.bot.set_my_commands([
            # Tier 1 — universal meta
            BotCommand("mode", "切换人格 (chat/coding/fin)"),
            BotCommand("model", "查看/切换模型"),
            BotCommand("think", "开关深度思考"),
            BotCommand("status", "查看当前状态"),
            BotCommand("clear", "清空对话历史"),
            BotCommand("usage", "查看 LLM 用量和费用"),
            BotCommand("tune", "调整 NeoMind 的 prompt 和配置"),
            BotCommand("help", "查看能力和命令"),
            # Tier 2 — fin mode quick-access
            BotCommand("stock", "股票查询 (fin 模式)"),
            BotCommand("crypto", "加密货币 (fin 模式)"),
            BotCommand("news", "多源新闻搜索"),
            BotCommand("digest", "市场每日摘要"),
            BotCommand("market", "市场概览"),
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
        if not self._is_command_for_me(update):
            return
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
        if not self._is_command_for_me(update):
            return
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
        if not self._is_command_for_me(update):
            return
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

        # Provider wiring — show the LLM-Router endpoint + its health
        # status. The "litellm" state key is preserved for back-compat
        # with older state files, but the user-visible label is "Router".
        router_base, router_key = self._router_env()
        if primary == "router" and router_base and router_key:
            lines.append(f"🔌 Router: 🟢 <code>{router_base}</code>")
        else:
            state = self._state_mgr._read_state()
            # State key is still "litellm" (back-compat); display says Router.
            router_info = state.get("router") or state.get("litellm", {})
            config = self._state_mgr.get_bot_config("neomind")
            provider_mode = config.get("provider_mode", "direct")
            # Normalize legacy mode names in display
            display_mode = {
                "litellm": "router",
                "ollama": "router",
            }.get(provider_mode, provider_mode)
            health = "🟢" if router_info.get("health_ok") else "🔴"
            lines.append(
                f"🔌 Provider: <b>{display_mode}</b> | LLM-Router: {health}"
            )

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
            f"\n<code>/provider router</code> | <code>direct</code> — 切换路由"
            f"\n<i>(legacy: /provider litellm/ollama 仍接受为 router 的别名)</i>"
        )

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /mode — switch personality for THIS chat (per-chat, not global)."""
        if not self._is_command_for_me(update):
            return
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
        if not self._is_command_for_me(update):
            return
        args = " ".join(context.args).strip() if context.args else ""
        cid = update.message.chat_id
        mode = self._store.get_mode(cid)
        override = self._store.get_model_override(cid)
        _, _, active_model = self._resolve_api(thinking=False, chat_id=cid)

        # ── No args: show current + list ──
        if not args:
            from agent.services.llm_provider import PROVIDERS, check_primary_healthy

            if override:
                header = f"当前模型: <code>{override}</code>（手动选择）"
            else:
                header = f"当前模型: <code>{active_model}</code>（{mode} 默认）"

            # Get actually active providers (have API keys)
            chain = self._get_provider_chain(thinking=False, chat_id=cid)
            active_providers = {p["name"] for p in chain}
            active_provider_name = chain[0]["name"] if chain else ""

            # Router-as-single-source-of-truth: if any primary-role
            # provider (= the LLM-Router at :8000) answers /v1/models,
            # trust it as the full universe of callable models and
            # hide direct-vendor fallback entries from the UI to
            # eliminate duplicates. Fallback providers still work at
            # HTTP-call time if the router later 5xx's — this hiding
            # is purely cosmetic for the /model list.
            primary_healthy = check_primary_healthy(timeout=2.0)

            def _fetch_live_models(pconf):
                """Live /v1/models for a provider. Falls back to the
                static list on any failure."""
                models_list = pconf.get("fallback_models", [])
                models_url = pconf.get("models_url")
                if not models_url:
                    return models_list
                try:
                    import requests as _rq
                    api_key = os.getenv(pconf.get("env_key", ""), "")
                    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                    resp = _rq.get(models_url, headers=headers, timeout=3)
                    if resp.ok:
                        data = resp.json()
                        live = data.get("data") if isinstance(data, dict) else data
                        if live:
                            return live
                except Exception:
                    pass
                return models_list

            lines = [f"🤖 {header}\n"]

            if primary_healthy:
                # Clean path: show the primary's live model list.
                # The model list reflects what the router can route to,
                # which is independent of whether the user is currently
                # in provider_mode=direct or =router. In direct mode
                # the HTTP calls bypass the router at call-time, but
                # the inventory of known models is still canonical at
                # the router layer. So we do NOT gate on
                # active_providers here.
                for pname, pconf in PROVIDERS.items():
                    if pconf.get("role") != "primary":
                        continue
                    models_list = _fetch_live_models(pconf)
                    if not models_list:
                        continue
                    lines.append(f"\n🟢 <b>router</b> (all traffic proxied here):")
                    for m in models_list:
                        mid = m["id"]
                        owned = m.get("owned_by", "")
                        marker = " ← 当前" if mid == active_model else ""
                        # Group by owned_by for readability (mlx-local, deepseek, zai, moonshot)
                        lines.append(
                            f"  <code>{mid}</code>  <i>({owned})</i>{marker}"
                        )
                lines.append(
                    "\n<i>☁️ 云端 + 🍎 本地 MLX 全部经由 LLM-Router 出入。"
                    "Router 离线时会自动回落直连 vendor API。</i>"
                )
            else:
                # Router down / unreachable — fall through to the
                # expanded view with fallback providers, so the user
                # still sees callable models.
                lines.append(
                    "\n⚠️ <b>LLM-Router 无响应</b> — 使用直连 vendor fallback:"
                )
                for pname, pconf in PROVIDERS.items():
                    if pname not in active_providers:
                        continue
                    if pconf.get("role") == "primary":
                        continue  # already known to be down
                    models_list = _fetch_live_models(pconf)
                    if not models_list:
                        continue
                    emoji = "🟢" if pname == active_provider_name else "🟡"
                    lines.append(f"\n{emoji} <b>{pname}</b> <i>(direct)</i>:")
                    for m in models_list:
                        mid = m["id"]
                        marker = (
                            " ← 当前"
                            if mid == active_model and pname == active_provider_name
                            else ""
                        )
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
        if not self._is_command_for_me(update):
            return
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
        if not self._is_command_for_me(update):
            return
        # Rewrite args and forward to admin handler
        context.args = ["history"] + (list(context.args) if context.args else [])
        await self._cmd_admin(update, context)

    async def _cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clear — archive current conversation (soft-clear).

        Messages are archived (hidden from LLM), not deleted.
        LLM starts fresh, but admin can still view archived messages.
        """
        if not self._is_command_for_me(update):
            return
        cid = update.message.chat_id
        count = self._store.clear_active(cid)
        await update.message.reply_text(
            f"🗑 对话已归档（{count} 条消息）\nLLM 重新开始，旧消息已存档"
        )

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
            # Use the full provider chain (primary + router-fallback) so a
            # 429 on kimi-k2.5 falls through to deepseek-chat like the
            # main LLM paths. Previously this code used _resolve_api which
            # returned a single provider and had no retry/fallback —
            # resulting in "⚠️ LLM error: 429" being surfaced directly to
            # the user whenever the upstream org-rate-limit was hit.
            providers = self._get_provider_chain(thinking=False, chat_id=chat_id)
            if not providers:
                await msg.reply_text("⚠️ No provider available for LLM interpretation")
                return

            resp = None
            used_provider = None
            for provider in providers:
                _attempts_429 = 0
                while True:
                    try:
                        resp = await asyncio.get_event_loop().run_in_executor(
                            None, lambda p=provider: req.post(
                                p["base_url"],
                                headers={"Authorization": f"Bearer {p['api_key']}",
                                         "Content-Type": "application/json"},
                                json={
                                    "model": p["model"],
                                    "messages": [{"role": "user", "content": interpret_prompt}],
                                    "max_tokens": 200,
                                    "temperature": _safe_temperature(p["model"], 0.1),
                                },
                                timeout=15,
                            ))
                        if resp.status_code == 200:
                            used_provider = provider
                            break
                        if resp.status_code == 429 and _attempts_429 < 2:
                            retry_after = resp.headers.get("Retry-After", "")
                            try:
                                wait_s = float(retry_after) if retry_after else 3.0 * (2 ** _attempts_429)
                            except ValueError:
                                wait_s = 3.0 * (2 ** _attempts_429)
                            wait_s = min(wait_s, 15.0)
                            await asyncio.sleep(wait_s)
                            _attempts_429 += 1
                            continue
                        break  # non-retryable, advance provider
                    except Exception:
                        break
                if used_provider:
                    break

            if not resp or resp.status_code != 200:
                status = resp.status_code if resp else "all failed"
                await msg.reply_text(f"⚠️ LLM error: {status}")
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
        /provider router   — route all traffic through the LLM-Router
                             (Desktop/LLM-Router, port 8000, fans out to
                             MLX + DeepSeek + ZAI + Moonshot)
        /provider direct   — bypass router, call vendor APIs directly
        Legacy aliases accepted: litellm, local, mlx, ollama → router

        State file is shared with xbar — changes here are visible on macOS menu bar.
        """
        args = " ".join(context.args).lower() if context.args else ""

        if not args:
            # No duplicate status — point user to /status for full view
            config = self._state_mgr.get_bot_config("neomind")
            mode = config.get("provider_mode", "direct")
            await update.message.reply_text(
                f"🔌 当前路由: <b>{mode}</b>\n\n"
                f"<code>/provider router</code> — 切换到 LLM-Router (本地 MLX + 云端聚合)\n"
                f"<code>/provider direct</code> — 切换到直连 vendor API\n\n"
                f"<i>完整状态请用 /status</i>",
                parse_mode=ParseMode.HTML,
            )

        elif args in ("router", "litellm", "local", "mlx", "ollama"):
            # "router" is the canonical name. "litellm" / "local" /
            # "mlx" / "ollama" are accepted aliases for back-compat —
            # users with old habits or stored chat bindings still get
            # routed to the LLM-Router at :8000.
            if not os.getenv("LLM_ROUTER_API_KEY", "") and not os.getenv("LITELLM_API_KEY", ""):
                await update.message.reply_text(
                    "⚠️ LLM_ROUTER_API_KEY 未设置，无法启用。\n"
                    "在 .env 里加上 LLM_ROUTER_API_KEY=你的key\n"
                    "(LITELLM_API_KEY 作为 legacy 兼容仍然接受)"
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

            # Identify what the resolved chat_actual model is — if it
            # looks like a local MLX repo id or legacy alias we label
            # it as MLX-free; otherwise it's a cloud model routed via
            # the router (the cost marker would be non-zero, but we
            # don't have the per-model cost to hand here).
            is_local = (
                chat_actual.startswith("mlx-community/")
                or chat_actual in ("local", "mlx")
                or ":" in chat_actual  # legacy ollama-style alias
            )
            cost_label = "MLX, 免费" if is_local else "via router"
            await update.message.reply_text(
                f"✅ LLM-Router 已启用\n"
                f"Chain: {' → '.join(models)}\n\n"
                f"普通对话: {chat_actual} ({cost_label})\n"
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
                "用法: <code>/provider router</code> | <code>/provider direct</code>",
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

    async def _cmd_evolve(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /evolve — inspect and control the self-evolution transaction log.

        Sub-commands:
            /evolve                   → list 10 most recent transactions
            /evolve list [N]          → list N most recent (default 10)
            /evolve status <tag>      → full detail of one transaction
            /evolve last              → full detail of the most recent transaction
            /evolve revert <tag>      → git reset --hard to tag + restart agent
        """
        msg = update.message
        args = context.args if context.args else []
        sub = (args[0].lower() if args else "list")

        try:
            from agent.evolution.transaction import (
                get_transaction_log, get_pending_intent,
            )
        except ImportError as e:
            await msg.reply_text(f"⚠️ Evolution module not available: {e}")
            return

        # ── list ──
        if sub == "list":
            try:
                n = int(args[1]) if len(args) > 1 else 10
            except (ValueError, IndexError):
                n = 10
            entries = get_transaction_log(limit=n)
            if not entries:
                await msg.reply_text("📭 No evolution transactions recorded yet.")
                return

            lines = [f"📜 <b>Last {len(entries)} evolution transactions:</b>\n"]
            for e in entries:
                tag = e.get("tag", "?")
                status = e.get("status", "?")
                reason = (e.get("reason") or "")[:60]
                files_n = len(e.get("applied_files") or [])
                icon = {
                    "committed": "✅",
                    "rolled_back": "↩️",
                    "post_restart_failed": "⚠️",
                    "in_progress": "⏳",
                }.get(status, "•")
                lines.append(
                    f"{icon} <code>{tag}</code> [{files_n} files]\n"
                    f"   {reason}"
                )
            pending = get_pending_intent()
            if pending:
                lines.append(f"\n⏳ <b>Pending intent:</b> <code>{pending.tag}</code>")
            await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
            return

        # ── last ──
        if sub == "last":
            entries = get_transaction_log(limit=1)
            if not entries:
                await msg.reply_text("📭 No evolution transactions recorded yet.")
                return
            await msg.reply_text(
                self._format_evolve_detail(entries[0]),
                parse_mode=ParseMode.HTML,
            )
            return

        # ── status <tag> ──
        if sub == "status":
            if len(args) < 2:
                await msg.reply_text("Usage: <code>/evolve status &lt;tag&gt;</code>",
                                     parse_mode=ParseMode.HTML)
                return
            want = args[1]
            entries = get_transaction_log(limit=200)
            match = next((e for e in entries if e.get("tag") == want), None)
            if not match:
                await msg.reply_text(f"❌ No transaction found with tag <code>{want}</code>",
                                     parse_mode=ParseMode.HTML)
                return
            await msg.reply_text(
                self._format_evolve_detail(match),
                parse_mode=ParseMode.HTML,
            )
            return

        # ── revert <tag> ──
        if sub == "revert":
            if len(args) < 2:
                await msg.reply_text("Usage: <code>/evolve revert &lt;tag&gt;</code>",
                                     parse_mode=ParseMode.HTML)
                return
            want = args[1]
            entries = get_transaction_log(limit=500)
            match = next((e for e in entries if e.get("tag") == want), None)
            if not match:
                await msg.reply_text(
                    f"❌ Refusing to revert: no transaction log entry for "
                    f"<code>{want}</code>. List recent tags with <code>/evolve list</code>.",
                    parse_mode=ParseMode.HTML,
                )
                return

            ok, result_msg = self._execute_evolve_revert(want, reason="user /evolve revert via chat")
            await msg.reply_text(result_msg, parse_mode=ParseMode.HTML)
            return

        await msg.reply_text(
            "Usage:\n"
            "<code>/evolve list [N]</code> — recent transactions\n"
            "<code>/evolve last</code> — last transaction detail\n"
            "<code>/evolve status &lt;tag&gt;</code> — specific transaction\n"
            "<code>/evolve revert &lt;tag&gt;</code> — rollback + restart",
            parse_mode=ParseMode.HTML,
        )

    def _format_evolve_detail(self, entry: Dict[str, Any]) -> str:
        """Render a single transaction log entry as HTML for Telegram."""
        tag = entry.get("tag", "?")
        reason = entry.get("reason", "")
        status = entry.get("status", "?")
        started = (entry.get("started_at") or "")[:19]
        finished = (entry.get("finished_at") or "")[:19]
        files = entry.get("applied_files") or []
        error = entry.get("error") or ""
        timings = entry.get("stage_timings") or {}

        icon = {
            "committed": "✅",
            "rolled_back": "↩️",
            "post_restart_failed": "⚠️",
            "in_progress": "⏳",
        }.get(status, "•")

        lines = [
            f"{icon} <b>Transaction</b> <code>{tag}</code>",
            f"<b>Reason:</b> {reason}",
            f"<b>Status:</b> {status}",
            f"<b>Started:</b> {started}",
        ]
        if finished:
            lines.append(f"<b>Finished:</b> {finished}")

        if files:
            file_list = "\n".join(f"  • <code>{f}</code>" for f in files[:15])
            lines.append(f"<b>Files ({len(files)}):</b>\n{file_list}")

        if timings:
            total = sum(float(v) for v in timings.values() if isinstance(v, (int, float)))
            stages = "  ".join(f"{k}={float(v):.2f}s" for k, v in timings.items())
            lines.append(f"<b>Timings</b> (total {total:.2f}s): {stages}")

        if error:
            lines.append(f"<b>Error:</b> <code>{error[:500]}</code>")

        lines.append(f"\n<i>Revert: <code>/evolve revert {tag}</code></i>")
        return "\n".join(lines)

    def _execute_evolve_revert(self, tag: str, reason: str) -> Tuple[bool, str]:
        """Actually perform a revert: git reset --hard <tag> then supervisorctl restart."""
        try:
            from agent.evolution.self_edit import SelfEditor
            repo_dir = str(SelfEditor.REPO_DIR)
        except Exception:
            repo_dir = "/app"

        import subprocess as _sp
        try:
            result = _sp.run(
                ["git", "reset", "--hard", tag],
                cwd=repo_dir, capture_output=True, text=True, timeout=20,
            )
        except Exception as e:
            return False, f"❌ git reset failed: {e}"

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()[-400:]
            return False, f"❌ git reset --hard <code>{tag}</code> failed:\n<code>{err}</code>"

        try:
            _sp.Popen(
                ["sh", "-c", "sleep 2 && supervisorctl restart neomind-agent"],
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            )
            schedule_msg = "Agent restart scheduled in 2s."
        except Exception as e:
            schedule_msg = f"⚠️ Could not schedule restart automatically: {e}"

        return True, (
            f"↩️ <b>Reverted to</b> <code>{tag}</code>\n"
            f"<b>Reason:</b> {reason}\n"
            f"{schedule_msg}"
        )

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

    async def _handle_unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle unrecognized slash commands.

        Flow:
          1. Try to execute as a system-level command (/arch, /dashboard, /upgrade, …)
          2. If text looks like a close typo of a real command, suggest the correction
          3. Otherwise: **strip the leading `/` and treat as natural-language input**.
             This is the "graceful fallthrough" path — any deprecated or unknown
             slash is silently treated as a chat message so the LLM can respond.
             It preserves muscle memory for removed slash commands and protects
             voice/new users from cryptic "unknown command" errors.
        """
        if not self._is_command_for_me(update):
            return
        text = update.message.text or ""
        cmd = text.split()[0].lower() if text else ""

        # 1. System commands that can be executed directly (no LLM needed)
        system_result = await self._try_system_command(cmd, text)
        if system_result is not None:
            await self._send_long_message(update.message, system_result)
            return

        # 2. Common typos / close matches — still a helpful nudge
        suggestions = {
            "/models": "/model",
            "/modes": "/mode",
            "/switch": "/model",
            "/config": "/status",
            "/settings": "/status",
        }
        suggestion = suggestions.get(cmd)
        if suggestion:
            await update.message.reply_text(
                f"你是不是想说 <code>{suggestion}</code>？",
                parse_mode=ParseMode.HTML,
            )
            return

        # 3. Graceful fallthrough: strip the leading `/` from the command token
        #    so the bot treats `/foo bar baz` as the natural-language message
        #    `foo bar baz`. This keeps all deprecated commands working — the
        #    LLM (in the user's current mode) figures out what to do.
        #
        #    We preserve the `@botname` suffix stripping that real CommandHandler
        #    does for group chats: `/foo@neomindbot` → `foo`.
        stripped_cmd = cmd.lstrip("/")
        if "@" in stripped_cmd:
            stripped_cmd = stripped_cmd.split("@", 1)[0]
        rest = text[len(cmd):].lstrip()
        rewritten = f"{stripped_cmd} {rest}".strip() if rest else stripped_cmd

        # Forward to the normal natural-language processing path
        await self._process_and_reply(update, rewritten, "natural_fallthrough")

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
        if not self._is_command_for_me(update):
            return
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
        # ── Universal: any factual/informational question ──
        # Time-related (anything that needs fresh info)
        r"最近|最新|今[天日]|昨[天日]|本[周月]|上[周月]|现在|目前|当前|2024|2025|2026",
        # Explicit search intent
        r"搜[索一下]|查[一下找查]|帮我[找查看搜]|有没有|有吗",
        r"search|find|look up|what happened|any updates|how to|how do",
        # Questions about things (products, events, people, places)
        r"是什么|是多少|怎么[样用办]|多少钱|哪个好|哪[里个家]|什么时候|发布|上市|出了|教程|怎样",
        r"what is|when did|where is|how much|which|who is|release|launch|price|cost|tutorial|guide",
        # News & events
        r"新闻|消息|事件|发[生布]|公[告布]|更新|变化|动态",
        r"news|update|announce|event|happening",
        # Analysis & comparison
        r"分析|研究|比较|对比|评[测估价]|推荐|建议|区别|优缺点|值不值",
        r"compare|analyze|review|benchmark|vs|versus|difference|worth",
        # Finance-specific (kept)
        r"行情|走势|涨跌|收盘|开盘|盘[前后]|IPO|股|基金|利率",
        r"market|stock|crypto|earnings|report|dividend|yield",
        # Tech products
        r"配置|参数|规格|内存|处理器|芯片|屏幕|电池|续航",
        r"specs|memory|ram|cpu|gpu|battery|display|chip|benchmark",
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

    # Messages that should NEVER trigger search (greetings, meta, emotions)
    _SEARCH_SKIP_RE = re.compile(
        r'^(hi|hello|hey|你好|嗨|哈喽|ok|好的|谢谢|thanks|thank you|'
        r'明白|知道了|收到|嗯|对|是的|哦|哈哈|lol|666|👍|😄|'
        r'/\w+)',  # commands
        re.IGNORECASE,
    )

    # Explicit opt-out: user told us NOT to search. Honour the directive.
    _SEARCH_OPTOUT_RE = re.compile(
        r'(不要搜索|不用搜索|别搜索|不搜索|不要联网|不联网|直接(回答|告诉)|'
        r"don'?t search|do not search|no search|without search(?:ing)?|"
        r'just from your knowledge|from your knowledge only|skip the search)',
        re.IGNORECASE,
    )

    def _should_search(self, text: str, chat_id: int = 0) -> bool:
        """Decide if a user message would benefit from web search augmentation.

        Returns True for ANY informational query — not just finance.
        Returns False only for greetings, single-word responses, commands,
        when the user explicitly opted out of search, or when the current
        mode's ``auto_search.enabled`` config flag is ``false``.
        """
        # ── Per-mode gate: honour auto_search.enabled from mode YAML ──
        try:
            from agent_config import AgentConfigManager
            mode = self._store.get_mode(chat_id) if chat_id else "fin"
            mode_cfg = AgentConfigManager(mode=mode)
            if not mode_cfg.auto_search_enabled:
                return False
        except Exception:
            pass  # If config loading fails, fall through to pattern matching

        stripped = text.strip()
        # Skip very short messages
        if len(stripped) < 6:
            return False
        # Skip greetings, commands, acknowledgements
        if self._SEARCH_SKIP_RE.match(stripped):
            return False
        # Honour explicit "no search" directive
        if self._SEARCH_OPTOUT_RE.search(stripped):
            return False

        # Lazy-init the compiled regex (built once, reused)
        if not hasattr(self, '_search_trigger_re'):
            self._search_trigger_re = self._build_search_trigger_re()

        return bool(self._search_trigger_re.search(text))

    async def _llm_extract_search_queries(self, user_message: str, chat_id: int = 0) -> List[str]:
        """Use a fast LLM call to generate 2-3 good search engine queries.

        Returns a list of search queries optimized for web search engines.
        Falls back to simple keyword extraction if LLM call fails.
        """
        import aiohttp as _aiohttp
        import json as _json

        providers = self._get_provider_chain(thinking=False, chat_id=chat_id)
        if not providers:
            return [user_message]  # fallback

        provider = providers[0]
        extract_prompt = (
            "You are a search query optimizer. Given a user message, generate 2-3 concise, "
            "specific web search queries that would find the most relevant results.\n\n"
            "Rules:\n"
            "- Each query should be 3-8 words, optimized for search engines\n"
            "- Include brand names, product categories, and year when relevant\n"
            "- Generate both English and Chinese queries for better coverage\n"
            "- Do NOT include filler words like '我想知道', '帮我查', '有吗'\n"
            "- Output ONLY the queries, one per line, nothing else\n\n"
            f"User message: {user_message}\n\n"
            "Search queries:"
        )

        try:
            timeout = _aiohttp.ClientTimeout(total=8)  # Fast: 8s max
            async with _aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    provider["base_url"],
                    headers={
                        "Authorization": f"Bearer {provider['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": provider["model"],
                        "messages": [{"role": "user", "content": extract_prompt}],
                        "max_tokens": 150,
                        "temperature": _safe_temperature(provider["model"], 0.3),
                    },
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data["choices"][0]["message"]["content"].strip()
                        queries = [
                            line.strip().lstrip("0123456789.-) ")
                            for line in text.split("\n")
                            if line.strip() and len(line.strip()) > 2
                        ]
                        if queries:
                            print(f"[auto-search] LLM queries: {queries}", flush=True)
                            return queries[:3]
        except Exception as e:
            print(f"[auto-search] LLM extraction failed ({e}), using fallback", flush=True)

        # Fallback: simple keyword extraction
        import re as _re
        q = user_message.strip()
        for pattern in [r'^(我想|我要|帮我|请)', r'(知道|查一下|查查|搜索|搜搜|看看)',
                        r'(是什么|是多少|有[吗没]|吗|呢|啊)', r'[？?！!。，,：:]+']:
            q = _re.sub(pattern, ' ', q)
        q = _re.sub(r'\s+', ' ', q).strip()
        return [q] if len(q) >= 3 else [user_message]

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
            print(f"[auto-search] ⚠️ SKIPPED — search_engine is None "
                  f"(components={'None' if not self.components else list(self.components.keys())})",
                  flush=True)
            return "", ""

        try:
            # Use LLM to generate optimized search queries from user message
            search_queries = await self._llm_extract_search_queries(query, chat_id)
            primary_query = search_queries[0]
            print(f"[auto-search] Raw: {query[:60]} → Search: {primary_query[:60]}", flush=True)

            # Hard timeout: if search takes >15s, skip it and let LLM answer without it
            try:
                # Search with the primary LLM-generated query (expand_queries=False since
                # we already have multiple targeted queries from the LLM)
                result = await asyncio.wait_for(
                    search_engine.search(
                        primary_query, max_results=8, extract_content=True,
                        expand_queries=len(search_queries) == 1,  # only expand if LLM gave us just 1
                    ),
                    timeout=15.0,
                )

                # If we have additional LLM-generated queries, search those too
                if len(search_queries) > 1 and (not result or len(result.items) < 3):
                    for extra_q in search_queries[1:]:
                        try:
                            extra_result = await asyncio.wait_for(
                                search_engine.search(extra_q, max_results=5, extract_content=False, expand_queries=False),
                                timeout=10.0,
                            )
                            if extra_result and extra_result.items:
                                # Merge (dedup by URL)
                                existing_urls = {item.url for item in result.items} if result else set()
                                for item in extra_result.items:
                                    if item.url not in existing_urls:
                                        result.items.append(item)
                                        existing_urls.add(item.url)
                                result.sources_used = list(set(result.sources_used + extra_result.sources_used))
                        except Exception:
                            pass
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
                "brave": "Brave", "brave_news": "Brave", "serper": "Serper", "tavily": "Tavily",
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
                f"你拥有网络搜索能力（{sources_str}）。有两种搜索方式：\n"
                "1. 自动搜索：系统可能在你回复前自动搜索，结果以 [Web Search Results] 注入上下文\n"
                "2. 主动搜索：你可以在回复中直接输出 <tool_call> 来调用 WebSearch 工具\n\n"
                "主动搜索格式（必须严格遵守）：\n"
                '<tool_call>{"tool": "WebSearch", "params": {"query": "你的搜索关键词"}}</tool_call>\n\n'
                "示例：\n"
                '- 查新闻: <tool_call>{"tool": "WebSearch", "params": {"query": "Apple M4 Ultra latest news 2026"}}</tool_call>\n'
                '- 查价格: <tool_call>{"tool": "WebSearch", "params": {"query": "Bitcoin price today"}}</tool_call>\n'
                '- 查事件: <tool_call>{"tool": "WebSearch", "params": {"query": "OpenAI GPT-5 release date"}}</tool_call>\n\n'
                "**默认不搜索**。只在以下情况触发 WebSearch：\n"
                "  a. 用户明确要求查找实时信息、最新新闻、当前价格\n"
                "  b. 用户问的事实明显超出你训练数据的时间范围（2026 后的事件、当天的数据）\n"
                "  c. 上下文中明显缺少关键信息、必须上网才能回答准确\n\n"
                "**严禁搜索的情况**（直接用你已有知识回答）：\n"
                "  ✗ 关于你自己的元问题（\"你是谁\"、\"你用什么模型\"、\"你能做什么\"、\"你是不是 GPT\"）\n"
                "  ✗ 问候、寒暄、情感表达、确认类（\"好的\"、\"谢谢\"、\"明白了\"）\n"
                "  ✗ 概念解释、定义、基础教学（\"什么是 ETF\"、\"Python 装饰器是什么\"）\n"
                "  ✗ 数学题、逻辑题、翻译、写作、代码生成\n"
                "  ✗ 用户已经在上下文里给了你答案的问题\n\n"
                "  如果你不确定要不要搜，**就不搜** — 先直接用你的知识回答，用户觉得不够再明说。\n\n"
                "搜索时必须遵守：\n"
                "- 输出格式（严格）：\n"
                '  <tool_call>{\"tool\": \"WebSearch\", \"params\": {\"query\": \"关键词\"}}</tool_call>\n'
                "- 搜索关键词必须具体明确！包含品牌名、产品类别、年份等上下文。"
                "错误示范: 'M4 Ultra'（太模糊）。正确示范: 'Apple M4 Ultra 芯片 发布日期 2026'\n"
                "- 同一问题最多搜 1 次。若结果不相关，用已有知识回答并坦诚说\"最新数据没搜到，以下基于我的训练知识\"\n"
                "- 上下文中已有 [Web Search Results] 时优先引用搜索结果\n"
                "- 引用具体事实时标注来源（如 \"据 Reuters 报道\"）\n"
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

        # Append tool definitions from canonical agentic layer. Pass the
        # current chat's mode so finance_* tools only appear in fin mode,
        # code_* tools only in coding mode, etc. (mode-gating introduced
        # in ToolDefinition.allowed_modes per eea40a0 + Phase B.3).
        tool_prompt = ""
        try:
            agentic = self._get_agentic_loop()
            if agentic:
                tool_prompt = "\n\n" + agentic.get_tool_prompt(mode=current_mode)
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

    # ── Per-mode routing hardcoded DEFAULTS ──────────────────────
    # These are the FALLBACK values used when the mode YAML file has
    # no `routing:` block, or when the YAML can't be loaded. In normal
    # operation the source of truth is agent/config/{mode}.yaml ::
    # routing.{primary_model, thinking_model, rate_limit_fallback_model,
    # preferred_direct_provider} — see _routing_for_mode().
    _MODE_PREFERRED_PROVIDER = {
        "fin": "moonshot",      # Kimi K2.5 for financial reasoning
        "coding": "deepseek",   # DeepSeek for coding
        "chat": "deepseek",     # DeepSeek for general chat
    }

    _ROUTER_DEFAULT_MODELS = {
        "fin": "kimi-k2.5",
        "coding": "deepseek-chat",
        "chat": "deepseek-chat",
    }
    _ROUTER_THINKING_MODEL = "deepseek-reasoner"

    # Per-mode rate-limit fallback model — inserted as a SECOND router
    # entry in the chain so when the primary's upstream 429's we can
    # fall through to a different vendor (e.g. fin primary=kimi via
    # moonshot, fallback=deepseek-chat via deepseek — independent
    # rate-bucket). None means "no rate-limit fallback for this mode".
    _ROUTER_RATE_LIMIT_FALLBACK = {
        "fin": "deepseek-chat",
        "coding": "kimi-k2.5",
        "chat": "kimi-k2.5",
    }

    def _routing_for_mode(self, mode: str) -> dict:
        """Read per-mode routing config from agent/config/<mode>.yaml.

        Returns a dict with keys: primary_model, thinking_model,
        rate_limit_fallback_model, preferred_direct_provider. Missing
        fields fall back to the hardcoded class-level defaults so a
        fresh install (no YAML routing block) still works identically
        to before this refactor.
        """
        try:
            from agent_config import AgentConfigManager
            cfg = AgentConfigManager(mode=mode)
            return {
                "primary_model": cfg.get(
                    "routing.primary_model",
                    self._ROUTER_DEFAULT_MODELS.get(mode, "kimi-k2.5"),
                ),
                "thinking_model": cfg.get(
                    "routing.thinking_model",
                    self._ROUTER_THINKING_MODEL,
                ),
                "rate_limit_fallback_model": cfg.get(
                    "routing.rate_limit_fallback_model",
                    self._ROUTER_RATE_LIMIT_FALLBACK.get(mode),
                ),
                "preferred_direct_provider": cfg.get(
                    "routing.preferred_direct_provider",
                    self._MODE_PREFERRED_PROVIDER.get(mode),
                ),
            }
        except Exception as exc:
            logger.debug(
                "_routing_for_mode(%s): config load failed (%s), "
                "using hardcoded defaults", mode, exc,
            )
            return {
                "primary_model": self._ROUTER_DEFAULT_MODELS.get(mode, "kimi-k2.5"),
                "thinking_model": self._ROUTER_THINKING_MODEL,
                "rate_limit_fallback_model":
                    self._ROUTER_RATE_LIMIT_FALLBACK.get(mode),
                "preferred_direct_provider":
                    self._MODE_PREFERRED_PROVIDER.get(mode),
            }

    def _router_env(self) -> Tuple[str, str]:
        """Return (base_url, api_key) for the local LLM router, or ("","") if unset."""
        base = (os.getenv("LLM_ROUTER_BASE_URL") or "").rstrip("/")
        key = os.getenv("LLM_ROUTER_API_KEY") or ""
        return base, key

    def _build_router_provider(self, mode: str, thinking: bool = False) -> Optional[dict]:
        """Build a single 'router' provider entry for the given mode.

        The router is a local OpenAI-compatible proxy that takes a `model`
        field and forwards to the right upstream (DeepSeek, Moonshot, z.ai,
        local MLX). Returns None if LLM_ROUTER_* env vars are not set.
        """
        base, key = self._router_env()
        if not base or not key:
            return None

        # Model resolution priority:
        #   1. Persisted mode_models in provider-state.json (if real, not "?")
        #   2. agent/config/<mode>.yaml :: routing.primary_model /
        #      routing.thinking_model  (new — was hardcoded before 2026-04-19)
        #   3. Class-level hardcoded defaults as the last-resort floor
        model = None
        try:
            cfg = self._state_mgr.get_bot_config("neomind")
            persisted = cfg.get("mode_models", {}).get(mode, {})
            candidate = persisted.get("thinking_model" if thinking else "model", "")
            if candidate and candidate != "?":
                model = candidate
        except Exception:
            pass
        if not model:
            routing = self._routing_for_mode(mode)
            model = (
                routing["thinking_model"] if thinking
                else routing["primary_model"]
            )

        return {
            "name": "router",
            "api_key": key,
            "base_url": f"{base}/chat/completions",
            "model": model,
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
                from agent.coding.tools import ToolRegistry, ToolResult
                registry = ToolRegistry(working_dir="/app")

                # ── Register WebSearch tool (bridges to bot's search engine) ──
                search_engine = self.components.get("search") if self.components else None
                if search_engine:
                    from agent.coding.tool_schema import (
                        ToolDefinition, ToolParam, ParamType, PermissionLevel,
                    )

                    # Track previous search results to avoid duplicate searches per turn
                    # Stored on bot instance — cleared in _run_agentic_tool_loop before each run
                    if not hasattr(self, '_ws_seen_urls'):
                        self._ws_seen_urls = set()

                    async def _exec_web_search(query: str, max_results: int = 5) -> ToolResult:
                        """Async tool: search the web via NeoMind's multi-source engine."""
                        try:
                            logger.info(f"[WebSearch] query={query!r}")
                            print(f"[WebSearch] Executing: {query!r}", flush=True)

                            result = await asyncio.wait_for(
                                search_engine.search(
                                    query, max_results=max_results,
                                    extract_content=True, expand_queries=True,
                                ),
                                timeout=15.0,
                            )
                            if not result or not result.items:
                                print(f"[WebSearch] No results for: {query!r}", flush=True)
                                return ToolResult(True, output="No results found for this query. Try rephrasing with more specific keywords.")

                            # Filter out results we've already seen (dedup across retries)
                            new_items = []
                            for item in result.items[:max_results]:
                                if item.url not in self._ws_seen_urls:
                                    new_items.append(item)
                                    self._ws_seen_urls.add(item.url)

                            if not new_items and result.items:
                                # All results are duplicates — tell LLM to stop retrying
                                return ToolResult(
                                    True,
                                    output=(
                                        "All search results are identical to previous searches. "
                                        "No new information found. Please answer based on what you already have."
                                    ),
                                )

                            items_to_show = new_items if new_items else result.items[:max_results]
                            lines = []
                            for i, item in enumerate(items_to_show, 1):
                                tag = f"[{item.source}]" if item.source else ""
                                lines.append(f"{i}. {tag} {item.title}")
                                lines.append(f"   URL: {item.url}")
                                if item.published:
                                    lines.append(f"   Date: {item.published.strftime('%Y-%m-%d')}")
                                content = item.full_text[:600] if item.full_text else item.snippet[:300]
                                if content:
                                    lines.append(f"   {content}")
                                lines.append("")

                            print(f"[WebSearch] ✅ {len(items_to_show)} results ({len(new_items)} new) from {list(result.sources_used)}", flush=True)
                            return ToolResult(
                                True,
                                output="\n".join(lines),
                                metadata={"results_count": len(items_to_show),
                                          "new_count": len(new_items),
                                          "sources": list(result.sources_used)},
                            )
                        except asyncio.TimeoutError:
                            print(f"[WebSearch] ⏱️ Timed out for: {query!r}", flush=True)
                            return ToolResult(False, error="Search timed out (15s). Try a simpler query.")
                        except Exception as e:
                            print(f"[WebSearch] ❌ Error: {e}", flush=True)
                            return ToolResult(False, error=f"Search failed: {e}")

                    registry._tool_definitions["WebSearch"] = ToolDefinition(
                        name="WebSearch",
                        description=(
                            "Search the web for real-time information, news, prices, "
                            "and any facts that may be newer than your training data. "
                            "Always use this when the user asks about current events, "
                            "latest news, live data, or anything time-sensitive.\n"
                            "IMPORTANT: Use SPECIFIC and DESCRIPTIVE queries. "
                            "Include brand names, product categories, and context. "
                            "BAD: 'M4 Ultra' (ambiguous — could be anything). "
                            "GOOD: 'Apple M4 Ultra chip release date 2026'. "
                            "BAD: 'price today'. GOOD: 'Tesla TSLA stock price March 2026'. "
                            "If first search gives irrelevant results, DO NOT retry with similar query. "
                            "Instead, summarize what you found and answer from your knowledge."
                        ),
                        parameters=[
                            ToolParam("query", ParamType.STRING,
                                      "Search query — MUST be specific: include brand/company names, "
                                      "product category, year. E.g. 'Apple M4 Ultra chip news 2026'"),
                            ToolParam("max_results", ParamType.INTEGER,
                                      "Max results to return",
                                      required=False, default=5),
                        ],
                        permission_level=PermissionLevel.READ_ONLY,
                        execute=_exec_web_search,
                        examples=[
                            {"query": "Apple M3 Ultra Mac Studio release date"},
                            {"query": "latest AI news March 2026"},
                            {"query": "Bitcoin price today"},
                        ],
                    )
                    print("[agentic] WebSearch tool registered ✅", flush=True)
                else:
                    print("[agentic] ⚠️ WebSearch NOT registered — search_engine component is None", flush=True)
                    if not self.components:
                        print("[agentic]   → self.components is None/empty", flush=True)
                    elif "search" not in self.components:
                        print(f"[agentic]   → available components: {list(self.components.keys())}", flush=True)

                # ── Finance tools (Phase B.3): register 10 fin-mode tools ──
                # Gated by allowed_modes={"fin"} so they only appear in the
                # LLM's tool list when the user is in fin mode. Safe to call
                # even if some components (digest, quant, rag) are missing —
                # each tool checks its dependency and returns {ok: False}.
                try:
                    from agent.tools.finance_tools import register_finance_tools
                    _reg_components = {
                        "data_hub": self.components.get("data_hub") if self.components else None,
                        "quant": self.components.get("quant") if self.components else None,
                        "digest": self.components.get("digest") if self.components else None,
                        "search": self.components.get("search") if self.components else None,
                        "rag": self.components.get("rag") if self.components else None,
                        "chat_store": self._store,
                    }
                    _fin_count = register_finance_tools(registry, _reg_components)
                    print(f"[agentic] {_fin_count} finance_* tools registered (fin mode only) ✅", flush=True)
                except Exception as e:
                    print(f"[agentic] ⚠️ finance tools registration failed: {e}", flush=True)

                config = AgenticConfig(
                    max_iterations=3,    # Telegram: 搜一次最多补搜一次，不要无限循环
                    soft_limit=2,        # 第 2 次就提示收尾
                    continuation_prompt=(
                        "Based on the search results above, provide your answer now. "
                        "If the results are not relevant, say so and answer from your knowledge. "
                        "Do NOT search again with a similar query."
                    ),
                    wrapup_prompt=(
                        "STOP searching. You have already searched multiple times. "
                        "Provide your FINAL answer NOW based on whatever information you have. "
                        "Do NOT output any more <tool_call> tags."
                    ),
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

        # Determine current mode
        if chat_id:
            mode = self._store.get_mode(chat_id)
        else:
            mode = "fin"  # default for Telegram bot

        # ── LLM Router: if LLM_ROUTER_* is set, prepend a single router
        # provider for the current mode. The router is an OpenAI-compatible
        # local proxy (host.docker.internal:8000/v1) that resolves the
        # `model` field to the right upstream. Traffic goes through it
        # exclusively when configured, so the router provider is the
        # primary and any direct-upstream entries from get_provider_chain
        # become fallbacks.
        router_provider = self._build_router_provider(mode=mode, thinking=thinking)
        if router_provider:
            chain = [router_provider] + chain
            # Per-mode upstream fallback: when the primary upstream's org
            # rate-limits (HTTP 429), the router alone can't help because
            # it proxies to the same origin. Insert a SECOND router entry
            # with a different model routed to a different upstream so
            # the provider loop falls through to an independent
            # rate-bucket. Only applies to non-thinking chains.
            routing = self._routing_for_mode(mode)
            fb_model = (
                None if thinking
                else routing.get("rate_limit_fallback_model")
            )
            if fb_model and fb_model != router_provider["model"]:
                router_base, router_key = self._router_env()
                chain.insert(1, {
                    "name": "router-fallback",
                    "api_key": router_key,
                    "base_url": f"{router_base}/chat/completions",
                    "model": fb_model,
                })

        # Re-order the remainder based on per-chat mode preference (keeps
        # the router at index 0; affects only the direct-upstream fallbacks).
        preferred = self._routing_for_mode(mode).get("preferred_direct_provider")
        if preferred and len(chain) > 2:
            head, tail = chain[:1], chain[1:]
            preferred_items = [p for p in tail if p["name"] == preferred]
            others = [p for p in tail if p["name"] != preferred]
            if preferred_items:
                chain = head + preferred_items + others

        return chain

    def _publish_mode_models_to_state(self):
        """Write per-mode model routing + available providers to state file.

        Called once at startup so xbar can dynamically display model info
        without hardcoding. Re-called whenever provider config changes.

        NEVER writes literal "?" into the state file. When the provider
        chain for a given mode is empty (e.g. only LLM_ROUTER_* is set and
        no per-provider keys), fall back to _ROUTER_DEFAULT_MODELS so the
        state always reflects the model the bot will actually use.
        """
        try:
            router_base, router_key = self._router_env()
            has_router = bool(router_base and router_key)

            mode_models = {}
            for mode in ("fin", "coding", "chat"):
                routing = self._routing_for_mode(mode)
                preferred_provider = routing.get("preferred_direct_provider") or \
                    self._MODE_PREFERRED_PROVIDER.get(mode)
                normal_model = None
                think_model = None
                provider_name = preferred_provider

                if has_router:
                    # Router is primary — per-mode YAML decides which
                    # model the router dispatches this mode to.
                    normal_model = routing["primary_model"]
                    think_model = routing["thinking_model"]
                    provider_name = "router"
                else:
                    # Fall back to direct provider chain
                    chain = self._state_mgr.get_provider_chain("neomind", thinking=False)
                    think_chain = self._state_mgr.get_provider_chain("neomind", thinking=True)
                    for p in chain:
                        if p["name"] == preferred_provider:
                            normal_model = p["model"]
                            break
                    for p in think_chain:
                        if p["name"] == preferred_provider:
                            think_model = p["model"]
                            break
                    if not normal_model and chain:
                        normal_model = chain[0]["model"]
                        provider_name = chain[0]["name"]
                    if not think_model and think_chain:
                        think_model = think_chain[0]["model"]
                    # Final defensive fallback: per-mode routing config
                    # so we still publish SOMETHING real rather than "?"
                    if not normal_model:
                        normal_model = routing["primary_model"]
                    if not think_model:
                        think_model = routing["thinking_model"]

                mode_models[mode] = {
                    "provider": provider_name,
                    "model": normal_model,
                    "thinking_model": think_model,
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
        """Resolve a router model alias (e.g. 'local') to the actual
        model id (e.g. 'mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit')
        by querying the LLM-Router /v1/models endpoint. The legacy
        LiteLLM /model/info fallback still fires if someone points
        LITELLM_BASE_URL at a litellm-proxy instance. Returns the
        alias unchanged on any error.
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
        if self._should_search(user_message, chat_id):
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
                    json={"model": p["model"], "messages": messages, "max_tokens": 4096, "temperature": _safe_temperature(p["model"]), "stream": False},
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

        # If user explicitly opted out of search, tell the LLM not to call any
        # tools. Without this nudge, kimi-k2.5 in fin mode keeps emitting
        # <tool_call>WebSearch</tool_call> wrappers and the agentic loop runs
        # for >90s, blowing past the user's "answer directly" intent.
        no_tools_requested = bool(self._SEARCH_OPTOUT_RE.search(user_message))
        if no_tools_requested:
            messages.insert(-1, {
                "role": "system",
                "content": (
                    "The user has explicitly asked you NOT to search the web. "
                    "Do NOT emit any <tool_call> blocks. Do NOT call WebSearch, "
                    "Bash, or any tool. Answer directly from your training "
                    "knowledge in the user's language. Be concise."
                ),
            })

        # Auto-search augmentation: inject web results if the query warrants it
        search_footer = ""
        if self._should_search(user_message, chat_id):
            # Show visible search indicator BEFORE searching
            live_msg = await msg.reply_text("🔍 正在搜索相关信息...")
            search_ctx, search_footer = await self._augment_with_search(user_message, chat_id)
            if search_ctx:
                # Insert search context as a system message right before the user's last message
                messages.insert(-1, {"role": "system", "content": search_ctx})
                try:
                    await live_msg.edit_text("💭 正在整合搜索结果...")
                except Exception:
                    pass
            else:
                # Search didn't return results — update placeholder
                try:
                    await live_msg.edit_text("💭 ...")
                except Exception:
                    pass
        else:
            # Send placeholder
            live_msg = await msg.reply_text("💭 ...")

        response_text = ""
        last_edit_time = 0
        EDIT_INTERVAL = 2.5  # Conservative: ~24 edits/min, well under Telegram's limit

        try:
            # Try providers in order. On HTTP 429 (rate limit), retry the same
            # provider with backoff honoring Retry-After before advancing to
            # the next — important when the chain has only one entry (router).
            response = None
            used_provider = None
            for provider in providers:
                _attempts_429 = 0
                while True:
                    try:
                        print(f"[llm-stream] Trying {provider['name']}:{provider['model']} → {provider['base_url'][:80]}", flush=True)
                        _temp = _safe_temperature(provider["model"])
                        response = await asyncio.get_event_loop().run_in_executor(
                            None, lambda p=provider, t=_temp: req.post(
                                p["base_url"],
                                headers={"Authorization": f"Bearer {p['api_key']}",
                                         "Content-Type": "application/json"},
                                json={"model": p["model"], "messages": messages,
                                      "max_tokens": 4096, "temperature": t, "stream": True},
                                timeout=90,
                                stream=True,
                            ))
                        if response.status_code == 200:
                            used_provider = provider
                            break
                        if response.status_code == 429 and _attempts_429 < 2:
                            # Honor Retry-After header; fall back to exponential
                            retry_after = response.headers.get("Retry-After", "")
                            try:
                                wait_s = float(retry_after) if retry_after else 5.0 * (2 ** _attempts_429)
                            except ValueError:
                                wait_s = 5.0 * (2 ** _attempts_429)
                            wait_s = min(wait_s, 30.0)
                            print(f"[llm-stream] ⏳ {provider['name']} 429, retry-after={wait_s}s (attempt {_attempts_429+1}/2)", flush=True)
                            await asyncio.sleep(wait_s)
                            _attempts_429 += 1
                            continue  # retry same provider
                        print(f"[llm-stream] ❌ {provider['name']} returned {response.status_code}", flush=True)
                        break  # non-retryable, advance to next provider
                    except Exception as e:
                        print(f"[llm-stream] ❌ {provider['name']} error: {e}", flush=True)
                        break  # advance to next provider
                if used_provider:
                    break
                # else: advance to next provider in outer loop

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

        # User opted out of tools — strip any tool_call blocks the LLM emitted
        # anyway and re-render the cleaned text in the live message.
        if no_tools_requested and response_text and '<tool_call>' in response_text:
            import re as _re_strip
            cleaned = _re_strip.sub(
                r'<tool_call>.*?</tool_(?:call|result)>', '', response_text, flags=_re_strip.DOTALL
            ).strip()
            if not cleaned:
                cleaned = "（已按你的要求跳过搜索，但模型这次没有生成正文，请重新发送你的问题。）"
            try:
                await live_msg.edit_text(
                    self._md_to_html(cleaned),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception:
                try:
                    await live_msg.edit_text(cleaned[:4000], disable_web_page_preview=True)
                except Exception:
                    pass
            response_text = cleaned

        # ── Agentic loop: if response contains tool calls, execute them ──
        if response_text and '<tool_call>' in response_text and used_provider and not no_tools_requested:
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

            try:
                await asyncio.wait_for(
                    self._run_agentic_tool_loop(
                        msg, response_text.strip(), chat_id, chat_type, used_provider,
                    ),
                    timeout=300,  # 5 min hard cap
                )
            except asyncio.TimeoutError:
                await msg.reply_text("⚠️ 工具执行超时（5分钟），已终止")
        elif response_text and used_provider:
            # Check for "dangling intent": LLM said it will IMMEDIATELY do
            # something but didn't output a tool call. Auto-nudge it to
            # actually execute.
            stripped = response_text.strip()
            # Imminent-action keywords — these signal the LLM is ABOUT to
            # perform a specific action RIGHT NOW. Generic capability
            # statements ("我可以帮你 X", "我能 Y", "我会 Z") are NOT
            # imminent — they describe ability, not a scheduled action.
            # Removing "帮你" and "为你" because they match:
            #   "你好！我可以帮你搜索信息" — a greeting, not a dangling intent
            # which previously caused the bot to send a follow-up "继续"
            # nudge and reply twice to a single greeting.
            _intent_keywords = (
                '让我', '我来', '我去', '马上', '立刻', '现在就',
                '接下来我', '我这就', '我现在',
            )
            _action_verbs = ('搜索', '查', '检查', '执行', '读取', '创建', '打开', '获取', '分析')
            has_intent_kw = any(kw in stripped for kw in _intent_keywords)
            ends_with_intent = stripped.endswith(('：', ':', '…', '...'))
            has_action_verb = any(v in stripped for v in _action_verbs)
            # Guard against misfires on short conversational messages —
            # a greeting that happens to mention "搜索" as an ability
            # should never trigger nudging. Require the response to be
            # substantial OR end with a colon/ellipsis.
            long_enough = len(stripped) > 120 or ends_with_intent
            dangling = (
                has_intent_kw
                and long_enough
                and (ends_with_intent or (has_action_verb and '<tool_call>' not in response_text))
            )
            if dangling:
                print(f"[agentic] Detected dangling intent (no tool_call), nudging LLM", flush=True)
                import aiohttp as _aiohttp
                provider = used_provider
                history = self._store.get_recent_history(chat_id, limit=20)
                nudge_messages = (
                    [{"role": "system", "content": self._get_system_prompt(chat_id)}]
                    + history
                    + [{"role": "user", "content":
                        "继续。请立刻用 <tool_call> 执行你刚才说要做的操作。"
                        "如果你要搜索，用 WebSearch 工具。格式示例：\n"
                        '<tool_call>{"tool": "WebSearch", "params": {"query": "你的搜索词"}}</tool_call>'}]
                )
                try:
                    _timeout = _aiohttp.ClientTimeout(total=90)
                    async with _aiohttp.ClientSession(timeout=_timeout) as _session:
                        async with _session.post(
                            provider["base_url"],
                            headers={"Authorization": f"Bearer {provider['api_key']}",
                                     "Content-Type": "application/json"},
                            json={"model": provider["model"], "messages": nudge_messages,
                                  "max_tokens": 4096, "temperature": _safe_temperature(provider["model"])},
                        ) as nudge_resp:
                            if nudge_resp.status == 200:
                                nudge_data = await nudge_resp.json()
                                nudge_text = nudge_data["choices"][0]["message"]["content"]
                            else:
                                body = await nudge_resp.text()
                                raise Exception(f"Nudge API error {nudge_resp.status}: {body[:200]}")

                    if '<tool_call>' in nudge_text:
                        print(f"[agentic] Nudge produced tool_call, executing", flush=True)
                        self._store.add_message(chat_id, "assistant", nudge_text.strip(), chat_type)
                        try:
                            await asyncio.wait_for(
                                self._run_agentic_tool_loop(
                                    msg, nudge_text.strip(), chat_id, chat_type, provider,
                                ),
                                timeout=300,
                            )
                        except asyncio.TimeoutError:
                            await msg.reply_text("⚠️ 工具执行超时（5分钟），已终止")
                    else:
                        # LLM still refused to use tools — send its text response
                        nudge_clean = nudge_text.strip()
                        if nudge_clean:
                            self._store.add_message(chat_id, "assistant", nudge_clean, chat_type)
                            await self._send_long_message(msg, nudge_clean)
                except Exception as e:
                    logger.error(f"Nudge failed: {e}", exc_info=True)
                    print(f"[agentic] Nudge FAILED: {e}", flush=True)

    async def _run_agentic_tool_loop(
        self, msg, initial_response: str,
        chat_id: int, chat_type: str, provider: dict,
    ):
        """Run the canonical agentic loop when LLM response contains tool calls.

        Executes tools, feeds results back to LLM, sends new responses as
        Telegram messages. Fully async — never blocks the event loop.
        """
        import aiohttp

        agentic = self._get_agentic_loop()
        if not agentic:
            await msg.reply_text("⚠️ Agentic loop not available")
            return

        # Reset per-turn dedup state for WebSearch tool
        if hasattr(self, '_ws_seen_urls'):
            self._ws_seen_urls.clear()

        # Build messages from history
        history = self._store.get_recent_history(chat_id, limit=20)
        messages = [{"role": "system", "content": self._get_system_prompt(chat_id)}] + history

        # LLM caller: fully async, uses aiohttp streaming to collect tokens
        async def llm_caller(msgs):
            full_text = ""
            timeout = aiohttp.ClientTimeout(total=90)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    provider["base_url"],
                    headers={
                        "Authorization": f"Bearer {provider['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": provider["model"],
                        "messages": msgs,
                        "max_tokens": 4096,
                        "temperature": _safe_temperature(provider["model"]),
                        "stream": True,
                    },
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise Exception(f"LLM API error: {resp.status} — {body[:200]}")

                    async for raw_line in resp.content:
                        line = raw_line.decode("utf-8", errors="replace").strip()
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
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        provider["base_url"],
                        headers={
                            "Authorization": f"Bearer {provider['api_key']}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": provider["model"],
                            "messages": msgs,
                            "max_tokens": 4096,
                            "temperature": _safe_temperature(provider["model"]),
                        },
                    ) as resp2:
                        if resp2.status == 200:
                            data = await resp2.json()
                            full_text = data["choices"][0]["message"]["content"]

            return full_text

        # Run agentic loop
        import html as _html
        import re as _re
        try:
            _tool_status_msg = None  # Reusable status message per tool cycle
            _got_llm_response = False  # Track whether we ever showed a final answer
            _got_tool_error = False    # Track tool errors for diagnostics

            async for event in agentic.run(initial_response, messages, llm_caller):
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
                    if not event.result_success:
                        _got_tool_error = True
                        print(f"[agentic] Tool {event.tool_name} FAILED: {event.result_error}", flush=True)

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
                            _got_llm_response = True
                            await self._send_long_message(msg, _clean_llm)

                elif event.type == "error":
                    await msg.reply_text(f"⚠️ Agentic error: {event.error_message}")

                elif event.type == "done":
                    # If the loop ended without ever producing a visible LLM response,
                    # the user sees "让我搜索一下：" and then nothing. Fix: send a fallback.
                    if not _got_llm_response:
                        print(f"[agentic] Loop ended at iter={event.iteration} with NO llm_response sent to user", flush=True)
                        if _got_tool_error:
                            await msg.reply_text("⚠️ 工具执行出错，正在尝试直接回答...")
                        # Either way, call LLM one more time without tool instructions
                        # so user gets an answer
                        try:
                            fallback_msgs = messages + [{"role": "user", "content":
                                "工具执行未成功。请不要再使用任何工具，直接根据你的知识回答用户的问题。"}]
                            fallback_text = await llm_caller(fallback_msgs)
                            if fallback_text and fallback_text.strip():
                                _clean = _re.sub(r'<tool_call>.*?</tool_(?:call|result)>', '', fallback_text, flags=_re.DOTALL)
                                _clean = _re.sub(r'</?tool_(?:call|result)>', '', _clean).strip()
                                if _clean:
                                    self._store.add_message(chat_id, "assistant", _clean, chat_type)
                                    await self._send_long_message(msg, _clean)
                        except Exception as fb_err:
                            print(f"[agentic] Fallback LLM call also failed: {fb_err}", flush=True)
                            await msg.reply_text("⚠️ 无法完成请求，请稍后重试")
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
        if self._should_search(user_message, chat_id):
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
            # Step 2: Stream the response (try providers in order, with
            # per-provider 429 retry-after backoff — critical when chain
            # has only one entry like the router).
            response = None
            used_provider = None
            for provider in providers:
                _attempts_429 = 0
                while True:
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
                        if response.status_code == 429 and _attempts_429 < 2:
                            retry_after = response.headers.get("Retry-After", "")
                            try:
                                wait_s = float(retry_after) if retry_after else 5.0 * (2 ** _attempts_429)
                            except ValueError:
                                wait_s = 5.0 * (2 ** _attempts_429)
                            wait_s = min(wait_s, 30.0)
                            print(f"[llm-think] ⏳ {provider['name']} 429, retry-after={wait_s}s (attempt {_attempts_429+1}/2)", flush=True)
                            await asyncio.sleep(wait_s)
                            _attempts_429 += 1
                            continue  # retry same provider
                        print(f"[llm-think] ❌ {provider['name']} returned {response.status_code}", flush=True)
                        break  # non-retryable, advance provider
                    except Exception as e:
                        print(f"[llm-think] ❌ {provider['name']} error: {e}", flush=True)
                        break
                if used_provider:
                    break

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

                # Strip <tool_call> blocks before user-visible send so raw XML
                # never shows up as literal text in the reply.
                _clean_display = re.sub(
                    r'<tool_call>.*?</tool_(?:call|result)>', '',
                    response_text.strip(), flags=re.DOTALL,
                )
                _clean_display = re.sub(
                    r'</?tool_(?:call|result)>', '', _clean_display,
                ).strip()
                if _clean_display:
                    await self._send_long_message(
                        msg, _clean_display, html_suffix=search_footer,
                    )

                # ── Agentic loop: if the response contains tool calls, execute them ──
                # (mirrors _ask_llm_stream_normal; reasoning models like
                # deepseek-reasoner emit <tool_call> blocks in `content` too,
                # and without this path fin-mode tools never fire.)
                if '<tool_call>' in response_text and used_provider:
                    print(
                        f"[agentic] Detected <tool_call> in thinking-mode "
                        f"response ({len(response_text)} chars), starting "
                        f"agentic loop", flush=True,
                    )
                    try:
                        await asyncio.wait_for(
                            self._run_agentic_tool_loop(
                                msg, response_text.strip(), chat_id, chat_type,
                                used_provider,
                            ),
                            timeout=300,
                        )
                    except asyncio.TimeoutError:
                        await msg.reply_text(
                            "⚠️ 工具执行超时（5分钟），已终止"
                        )
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
