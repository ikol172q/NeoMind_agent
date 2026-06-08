"""Dashboard agent main loop — OpenAI-compat function calling.

Single public entry point: `await answer(chat_id, user_msg) -> AgentReply`.

Persists every turn (user / assistant / tool) to agent_chat_history so
chats survive process restarts and you can audit "what did the agent
say last time".

Returns AgentReply(text, proposals) where proposals are structured
write-actions the agent suggests (record decision / promote ticker /
quick set holdings). The Telegram bot renders proposals as inline
keyboard buttons the user can confirm with one tap.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from agent.finance.dashboard_agent.tools import TOOL_SCHEMAS, dispatch
from agent.finance.persistence import connect, ensure_schema
from agent.finance import agent_audit, fin_reward, fin_router

# Episode capture feeds the (dormant) evolution loop. Best-effort: if the
# module can't import (e.g. trimmed deploy) the agent still answers.
try:
    from agent.evolution.episode_capture import record_episode as _record_episode
except Exception:  # noqa: BLE001
    _record_episode = None

# Outcome ledger (Phase 3.1) closes the reward loop: log proposed directional
# decisions so fin_outcome.backfill() can later attach the realized forward
# return as a sparse reward. Best-effort, ZERO network on the reply path.
try:
    from agent.finance import fin_outcome as _fin_outcome
except Exception:  # noqa: BLE001
    _fin_outcome = None

logger = logging.getLogger(__name__)

_SYSTEM_MD = Path(__file__).parent / "system.md"
_MAX_TURNS_PER_CALL = 8       # bounds tool-calling loop depth
_HISTORY_WINDOW = 12          # last N turns kept verbatim
_DEFAULT_MODEL = os.getenv("DASHBOARD_AGENT_MODEL", "deepseek-v4-flash")

# 2026-05-16: dedicated SQLite file for chat history. Container (where
# this agent runs) and host (where dashboard FastAPI runs) writing to
# the SAME fin.db through different mount paths produces sporadic
# "database disk image is malformed" — SQLite WAL coordination across
# the OverlayFS / shared-volume boundary is unreliable. Putting chat
# history in its own DB inside the container's writable area removes
# the contention surface entirely.
_AGENT_DB_PATH = Path(
    os.getenv("NEOMIND_AGENT_DB",
              str(Path.home() / ".neomind" / "fin" / "agent_chat.db"))
)


def _agent_connect():
    """Open the dashboard-agent's own SQLite. Creates the schema on
    first call. Returns a context-manager connection.
    """
    import sqlite3
    _AGENT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_AGENT_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agent_chat_history (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id          TEXT NOT NULL,
            turn_idx         INTEGER NOT NULL,
            role             TEXT NOT NULL,
            content          TEXT,
            tool_call_id     TEXT,
            tool_calls_json  TEXT,
            model            TEXT,
            tokens_in        INTEGER,
            tokens_out       INTEGER,
            cost_usd         REAL,
            created_at       TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ach_chat "
        "ON agent_chat_history(chat_id, turn_idx)"
    )
    # Phase 1b: persist reasoning_content so interleaved thinking can carry
    # across user-message boundaries. Guarded ALTER for pre-existing DBs.
    try:
        conn.execute("ALTER TABLE agent_chat_history ADD COLUMN reasoning_content TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    return conn


# Marker the LLM emits to propose a write action.  Format (single line):
#   [[ACT:<kind>|<arg1>|<arg2>|...|<label>]]
# - kind: 'decision' | 'promote' | 'quickset'
# - decision   args: <ticker>|<kind: hold|trim|add|sell|watch_only|pass>|<note?>
# - promote    args: <ticker>|<tier: core|adjacent|watching>
# - quickset   args: <ticker>|<shares>
# Last arg is always the user-facing button label.
# Telegram bot regex-extracts these, replaces them with inline keyboard
# buttons. CLI prints them as numbered "[propose #N]" lines.
_ACT_RE = re.compile(r"\[\[ACT:([^\]\n]{1,300})\]\]")


@dataclass
class Proposal:
    kind:  str
    args:  Dict[str, Any]
    label: str

    def encode_callback(self) -> str:
        """Compact callback_data (Telegram limit 64 bytes)."""
        if self.kind == "decision":
            return f"dag:d:{self.args.get('ticker','')}:{self.args.get('action','')}"
        if self.kind == "promote":
            return f"dag:p:{self.args.get('ticker','')}:{self.args.get('tier','')}"
        if self.kind == "quickset":
            return f"dag:q:{self.args.get('ticker','')}:{self.args.get('shares','')}"
        return f"dag:?:{self.kind}"


@dataclass
class AgentReply:
    text:      str
    proposals: List[Proposal] = field(default_factory=list)


def _strip_pipe_tables(text: str) -> str:
    """Convert markdown pipe-tables to bullet lists.

    LLMs occasionally still emit ``| col | col |`` tables despite the
    system prompt. Telegram doesn't render those — user sees literal
    pipes. Detect a table block (a header line of pipes + at least one
    body line) and reformat as ``• <first cell>: <rest>``.
    """
    lines = text.split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # A table line starts with "|" and has at least 1 more "|".
        if line.lstrip().startswith("|") and line.count("|") >= 2:
            # Collect contiguous table lines.
            start = i
            tbl: List[str] = []
            while i < len(lines):
                ln = lines[i]
                if ln.lstrip().startswith("|") and ln.count("|") >= 2:
                    tbl.append(ln.strip())
                    i += 1
                elif ln.strip() == "":
                    break
                else:
                    break
            if len(tbl) < 2:
                # not actually a table; emit as-is
                out.extend(lines[start:i] or [line])
                if start == i:
                    i += 1
                continue
            # Skip separator line(s) like "|---|---|".
            cells_per_row = [
                [c.strip() for c in row.strip("|").split("|")]
                for row in tbl
            ]
            is_sep = lambda r: all(set(c) <= set("- :") for c in r)
            rows = [r for r in cells_per_row if not is_sep(r)]
            if not rows:
                continue
            # First row = header; rest = bullets.
            header = rows[0]
            for r in rows[1:]:
                # Pad to header width
                while len(r) < len(header):
                    r.append("")
                # First non-empty cell becomes the leading label.
                label = r[0] or header[0]
                rest_parts = []
                for j in range(1, len(header)):
                    v = r[j].strip() if j < len(r) else ""
                    if not v:
                        continue
                    rest_parts.append(f"{header[j]}: {v}" if header[j] else v)
                out.append(f"• {label} — " + " · ".join(rest_parts))
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _parse_proposals(text: str) -> AgentReply:
    """Extract [[ACT:...]] markers, return cleaned text + structured list."""
    text = _strip_pipe_tables(text)
    proposals: List[Proposal] = []
    def _replace(m: "re.Match[str]") -> str:
        body = m.group(1).strip()
        parts = [p.strip() for p in body.split("|")]
        if len(parts) < 3:
            return ""
        kind = parts[0]
        label = parts[-1]
        if kind == "decision" and len(parts) >= 4:
            p = Proposal(
                kind="decision",
                args={"ticker": parts[1].upper(),
                      "action": parts[2].lower(),
                      "note":   parts[3] if len(parts) >= 5 else ""},
                label=label,
            )
            proposals.append(p)
            return f"▶︎ {label}"
        if kind == "promote" and len(parts) >= 4:
            p = Proposal(
                kind="promote",
                args={"ticker": parts[1].upper(),
                      "tier":   parts[2].lower()},
                label=label,
            )
            proposals.append(p)
            return f"▶︎ {label}"
        if kind == "quickset" and len(parts) >= 4:
            try:
                shares = float(parts[2])
            except ValueError:
                return ""
            p = Proposal(
                kind="quickset",
                args={"ticker": parts[1].upper(), "shares": shares},
                label=label,
            )
            proposals.append(p)
            return f"▶︎ {label}"
        return ""
    cleaned = _ACT_RE.sub(_replace, text).strip()
    return AgentReply(text=cleaned, proposals=proposals)


# ── LLM call (matches agent/finance/stock_research.py pattern) ──────


async def _llm_call(messages: List[Dict[str, Any]],
                    model: str,
                    *,
                    reasoning_effort: Optional[str] = None,
                    max_tokens: int = 2000,
                    temperature: float = 0.3) -> Dict[str, Any]:
    base = (os.getenv("LLM_ROUTER_BASE_URL") or "http://127.0.0.1:8000/v1").rstrip("/")
    key = (os.getenv("LLM_ROUTER_API_KEY")
           or os.getenv("DEEPSEEK_API_KEY")
           or "dummy")
    payload: Dict[str, Any] = {
        "model":       model,
        "messages":    messages,
        "tools":       TOOL_SCHEMAS,
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }
    # DeepSeek V4 thinking budget. Valid: low/medium/high/max/xhigh (the
    # API 400s on anything else, incl. "none" — both models think by
    # default). Omit the field rather than send an unsupported value.
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as c:
        r = await c.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type":  "application/json"},
            json=payload,
        )
        r.raise_for_status()
        return r.json()


# ── persistence ──────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_history(chat_id: str) -> List[Dict[str, Any]]:
    """Load most recent _HISTORY_WINDOW turns for a chat, oldest first.

    Phase 1b — interleaved thinking: we now persist + restore
    `reasoning_content`, but keep it ONLY on the most-recent assistant
    turn (see _keep_recent_reasoning). That lets the model continue its
    prior chain of thought across a user-message boundary (V4's
    interleaved-thinking behaviour — verified the API accepts historical
    reasoning without a 400) while bounding the extra input tokens.
    """
    with _agent_connect() as conn:
        rows = conn.execute(
            "SELECT role, content, tool_call_id, tool_calls_json, reasoning_content "
            "FROM agent_chat_history "
            "WHERE chat_id = ? AND role IN ('user','assistant','tool') "
            "ORDER BY turn_idx DESC LIMIT ?",
            (chat_id, _HISTORY_WINDOW),
        ).fetchall()
    rows = list(reversed(rows))
    out: List[Dict[str, Any]] = []
    for r in rows:
        msg: Dict[str, Any] = {"role": r["role"], "content": r["content"] or ""}
        if r["tool_calls_json"]:
            try:
                msg["tool_calls"] = json.loads(r["tool_calls_json"])
            except json.JSONDecodeError:
                pass
        if r["tool_call_id"]:
            msg["tool_call_id"] = r["tool_call_id"]
        if r["reasoning_content"]:
            msg["reasoning_content"] = r["reasoning_content"]
        out.append(msg)
    out = _strip_orphan_tool_calls(out)
    _keep_recent_reasoning(out)
    return out


def _keep_recent_reasoning(msgs: List[Dict[str, Any]]) -> None:
    """Strip reasoning_content from every assistant turn except the last.

    Mutates ``msgs`` in place. Carrying every turn's reasoning would blow
    up input tokens; the most-recent assistant turn is the high-value one
    (the model's last conclusion) and is enough for continuity.
    """
    last_assistant = -1
    for i, m in enumerate(msgs):
        if m.get("role") == "assistant":
            last_assistant = i
    for i, m in enumerate(msgs):
        if m.get("role") == "assistant" and i != last_assistant:
            m.pop("reasoning_content", None)


def _strip_orphan_tool_calls(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop assistant turns whose tool_calls have no matching tool reply.

    DeepSeek 400s on malformed conversations where an assistant promises
    tool_calls but the next turn isn't `role=tool`. This can happen if
    a previous answer() crashed mid-loop.
    """
    out: List[Dict[str, Any]] = []
    i = 0
    while i < len(msgs):
        m = msgs[i]
        if m["role"] == "assistant" and m.get("tool_calls"):
            expected_ids = {tc["id"] for tc in m["tool_calls"]}
            actual_ids = set()
            j = i + 1
            while j < len(msgs) and msgs[j]["role"] == "tool":
                actual_ids.add(msgs[j].get("tool_call_id"))
                j += 1
            if expected_ids != actual_ids:
                # orphan — drop the assistant AND any partial tool replies
                i = j
                continue
        out.append(m)
        i += 1
    return out


def _next_turn_idx(chat_id: str) -> int:
    with _agent_connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(turn_idx), -1) + 1 AS n "
            "FROM agent_chat_history WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
    return int(row["n"])


def _persist_turn(chat_id: str, turn_idx: int, msg: Dict[str, Any],
                  model: Optional[str] = None,
                  usage: Optional[Dict[str, Any]] = None) -> None:
    tokens_in = (usage or {}).get("prompt_tokens")
    tokens_out = (usage or {}).get("completion_tokens")
    cost = _approx_cost(model, tokens_in, tokens_out)
    with _agent_connect() as conn:
        conn.execute(
            "INSERT INTO agent_chat_history "
            "(chat_id, turn_idx, role, content, tool_call_id, "
            " tool_calls_json, model, tokens_in, tokens_out, cost_usd, "
            " created_at, reasoning_content) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                chat_id, turn_idx, msg["role"],
                msg.get("content") or "",
                msg.get("tool_call_id"),
                (json.dumps(msg["tool_calls"]) if msg.get("tool_calls") else None),
                model, tokens_in, tokens_out, cost, _now_iso(),
                msg.get("reasoning_content"),
            ),
        )


def _approx_cost(model: Optional[str], t_in: Optional[int],
                 t_out: Optional[int]) -> Optional[float]:
    if not model or t_in is None or t_out is None:
        return None
    # DeepSeek-v4-flash pricing (2026): ~$0.07/M in, ~$0.30/M out.
    if "v4-flash" in model:
        return round(t_in * 0.07e-6 + t_out * 0.30e-6, 6)
    if "v4" in model:
        return round(t_in * 0.27e-6 + t_out * 1.10e-6, 6)
    return None


# ── trajectory + reward (Phase 0: Fin Harness Evolution Loop) ─────────


def _finalize_turn(
    reply: AgentReply,
    *,
    chat_id: str,
    req_id: str,
    query: str,
    tool_results: List[Dict[str, Any]],
    episode_tool_calls: List[Dict[str, Any]],
    model: str,
    usage: Optional[Dict[str, Any]],
    finish_reason: str,
    iterations: int,
    t0: float,
    route: Optional[Dict[str, Any]] = None,
) -> AgentReply:
    """Close out one answer(): audit the response, compute the per-turn
    reward, and append a reward-labelled episode for the evolution loop.

    Every step is best-effort — instrumentation must never break a reply.
    Returns ``reply`` unchanged so call sites can ``return _finalize_turn(...)``.
    """
    duration_ms = int((time.monotonic() - t0) * 1000)
    decisions = [p.args for p in reply.proposals if p.kind == "decision"]

    try:
        agent_audit.audit_response(
            req_id=req_id, agent_id="dashboard-agent",
            endpoint="dashboard_agent.answer",
            content=reply.text, finish_reason=finish_reason,
            usage=usage, duration_ms=duration_ms,
        )
    except Exception:  # noqa: BLE001
        logger.debug("audit_response failed", exc_info=True)

    reward: Optional[Dict[str, Any]] = None
    try:
        reward = fin_reward.compute_reward(
            query=query, reply=reply.text, tool_results=tool_results,
            decisions=decisions, finish_reason=finish_reason,
        )
    except Exception:  # noqa: BLE001
        logger.debug("compute_reward failed", exc_info=True)

    if _fin_outcome is not None and decisions:
        try:
            _fin_outcome.record_decisions(
                decisions=decisions, req_id=req_id, chat_id=chat_id)
        except Exception:  # noqa: BLE001
            logger.debug("fin_outcome.record_decisions failed", exc_info=True)

    if _record_episode is not None:
        try:
            _record_episode(
                mode="fin", query=query, reply=reply.text,
                tool_calls=episode_tool_calls,
                signals={
                    "model": model,
                    "intent": (route or {}).get("intent"),
                    "reasoning_effort": (route or {}).get("reasoning_effort"),
                    "finish_reason": finish_reason,
                    "duration_ms": duration_ms,
                    "n_iterations": iterations,
                    "tokens_in": (usage or {}).get("prompt_tokens"),
                    "tokens_out": (usage or {}).get("completion_tokens"),
                    "reward": reward,
                },
                session_id=str(chat_id), project_id="fin-core", req_id=req_id,
            )
        except Exception:  # noqa: BLE001
            logger.debug("record_episode failed", exc_info=True)

    return reply


# ── main entry ────────────────────────────────────────────────────────


async def answer(chat_id: str, user_msg: str,
                 model: Optional[str] = None,
                 temperature: Optional[float] = None) -> AgentReply:
    """Receive a message, run the tool-calling loop, return final reply.

    Persists user message, every tool call/result, and final assistant
    reply to agent_chat_history. Bounded to _MAX_TURNS_PER_CALL LLM
    round-trips per call to prevent runaway.

    Difficulty routing (Phase 1): when ``model`` is None the query is
    classified and routed to flash/pro + a reasoning_effort. An explicit
    ``model`` (e.g. from a /model override) is honoured but still gets a
    sensible effort.
    """
    chat_id = str(chat_id)
    system_prompt = _SYSTEM_MD.read_text(encoding="utf-8")

    # Route: query → (model, reasoning_effort, max_tokens).
    route = fin_router.route(user_msg, explicit_model=model)
    model = route["model"]
    reasoning_effort = route["reasoning_effort"]
    route_max_tokens = route["max_tokens"]
    logger.info("fin route: %s", route["reason"])

    history = _load_history(chat_id)
    turn_idx = _next_turn_idx(chat_id)

    user_turn = {"role": "user", "content": user_msg}
    _persist_turn(chat_id, turn_idx, user_turn)
    turn_idx += 1

    messages = [{"role": "system", "content": system_prompt}] + history + [user_turn]

    # Trajectory instrumentation (Phase 0). req_id ties the audit request,
    # audit response, and the episode together.
    req_id = agent_audit.new_req_id()
    t0 = time.monotonic()
    iterations = 0
    last_usage: Optional[Dict[str, Any]] = None
    episode_tool_calls: List[Dict[str, Any]] = []
    tool_results_for_reward: List[Dict[str, Any]] = []
    try:
        agent_audit.audit_request(
            req_id=req_id, endpoint="dashboard_agent.answer",
            agent_id="dashboard-agent", messages=messages, model=model,
            max_tokens=route_max_tokens, temperature=0.3,
        )
    except Exception:  # noqa: BLE001
        logger.debug("audit_request failed", exc_info=True)

    for _ in range(_MAX_TURNS_PER_CALL):
        iterations += 1
        try:
            resp = await _llm_call(messages, model,
                                   reasoning_effort=reasoning_effort,
                                   max_tokens=route_max_tokens,
                                   temperature=0.3 if temperature is None else temperature)
        except httpx.HTTPError as exc:
            err = f"⚠️ LLM 调用失败 ({type(exc).__name__})。dashboard 还在，请稍后重试。"
            _persist_turn(chat_id, turn_idx, {"role": "assistant", "content": err}, model=model)
            return _finalize_turn(
                AgentReply(text=err), chat_id=chat_id, req_id=req_id,
                query=user_msg, tool_results=tool_results_for_reward,
                episode_tool_calls=episode_tool_calls, model=model,
                usage=last_usage, finish_reason="llm_error",
                iterations=iterations, t0=t0, route=route)

        choice = resp["choices"][0]
        assistant_msg = choice["message"]
        usage = resp.get("usage")
        last_usage = usage or last_usage

        # Persist the assistant turn (may include tool_calls + reasoning).
        # Phase 1b: reasoning_content is now persisted so it can carry to
        # the next answer() (interleaved thinking); _load_history keeps it
        # only on the most-recent assistant turn to bound token cost.
        persist_msg = {
            "role":    "assistant",
            "content": assistant_msg.get("content") or "",
        }
        if assistant_msg.get("tool_calls"):
            persist_msg["tool_calls"] = assistant_msg["tool_calls"]
        if assistant_msg.get("reasoning_content"):
            persist_msg["reasoning_content"] = assistant_msg["reasoning_content"]
        _persist_turn(chat_id, turn_idx, persist_msg, model=model, usage=usage)
        turn_idx += 1

        # 2026-05-16: forward reasoning_content back to DeepSeek. Without
        # this, thinking-mode models 400 with "reasoning_content in the
        # thinking mode must be passed back".
        echo: Dict[str, Any] = {
            "role":    "assistant",
            "content": assistant_msg.get("content") or "",
        }
        if assistant_msg.get("reasoning_content"):
            echo["reasoning_content"] = assistant_msg["reasoning_content"]
        if assistant_msg.get("tool_calls"):
            echo["tool_calls"] = assistant_msg["tool_calls"]
        messages.append(echo)

        tool_calls = assistant_msg.get("tool_calls") or []
        if not tool_calls:
            raw = assistant_msg.get("content") or "(空回复)"
            return _finalize_turn(
                _parse_proposals(raw), chat_id=chat_id, req_id=req_id,
                query=user_msg, tool_results=tool_results_for_reward,
                episode_tool_calls=episode_tool_calls, model=model,
                usage=last_usage, finish_reason="stop",
                iterations=iterations, t0=t0, route=route)

        # Execute each tool the LLM asked for (parallel — they're all read-only).
        async def _run_one(tc: Dict[str, Any]) -> Dict[str, Any]:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await dispatch(tc["function"]["name"], args)
            return {"tc": tc, "result": result}

        results = await asyncio.gather(*[_run_one(tc) for tc in tool_calls])

        for r in results:
            tc = r["tc"]
            try:
                _args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                _args = {}
            episode_tool_calls.append(
                {"name": tc["function"]["name"], "args": _args})
            tool_turn = {
                "role":         "tool",
                "tool_call_id": tc["id"],
                "content":      json.dumps(r["result"], ensure_ascii=False),
            }
            tool_results_for_reward.append({"content": tool_turn["content"]})
            _persist_turn(chat_id, turn_idx, tool_turn, model=model)
            turn_idx += 1
            messages.append(tool_turn)

    final = "⚠️ 推理超过 8 轮，可能 LLM 陷入循环。请重新提问，或检查 dashboard 数据是否完整。"
    _persist_turn(chat_id, turn_idx, {"role": "assistant", "content": final}, model=model)
    return _finalize_turn(
        AgentReply(text=final), chat_id=chat_id, req_id=req_id,
        query=user_msg, tool_results=tool_results_for_reward,
        episode_tool_calls=episode_tool_calls, model=model,
        usage=last_usage, finish_reason="max_turns",
        iterations=iterations, t0=t0, route=route)


def answer_sync(chat_id: str, user_msg: str,
                model: Optional[str] = None) -> AgentReply:
    """Sync wrapper for non-async callers. ``model=None`` → difficulty
    routing (Phase 1); pass a model to force it."""
    return asyncio.run(answer(chat_id, user_msg, model))
