"""定时任务巡检 digest —— 每日把**全部** scheduler job 的健康(简报 + 每任务详细)
＋ 关键数据落库状况，一条消息推到 Telegram + dashboard 铃铛。

目的：保证没有任何定时任务悄悄死掉 / 数据悄悄停更，而你却不知道。这是「所有
定时任务受监控」的兜底心跳——不是每个 job 每次跑都发(那样一天上百条刷屏)，而是
一条日报把 25 个 job 的状态一次性给全。

- 简报：N/M 正常，异常的(失败/过期/从未成功)单独列出。
- 详细：每个 job 一行(状态 emoji · 上次成功多久前 · cron)。
- 数据落库：关键 crawl 表的行数 + 24h 增量 + 最新时间，证明数据在存。

有 🔴 失败的 job → 整条按 P1；否则 P2。propose-not-dispose：只读状态，不下单、
不改数据。push_to_telegram 读 repo .env 的 token(能发)。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

JOB_NAME = "scheduler_health_digest"
# 每日 13:00 UTC (~06:00 PDT) —— 盘前巡检心跳。想更勤就把这个 cron 调密。
DEFAULT_CRON = "0 13 * * *"
DESCRIPTION = (
    "每日把全部 scheduler job 的健康(简报+每任务详细)+ 关键数据落库状况一条推 "
    "Telegram/铃铛，兜底监控所有定时任务，防止悄悄死掉/停更。"
)

# 要报告落库状况的关键 crawl/持久化表：(表名, 时间列 or None, 中文标签)
_DATA_TABLES: List[Tuple[str, Any, str]] = [
    ("signal_events",   "detected_at",  "信号事件"),
    ("raw_market_data", None,           "行情"),
    ("official_news",   "fetched_at",   "官方新闻"),
    ("recent_filings",  None,           "SEC filing"),
    ("analysis_runs",   "completed_at", "任务运行"),
]


def _age(ms: Any) -> str:
    """分钟数 → 人读的「多久前」。"""
    if ms is None:
        return "从未"
    ms = int(ms)
    if ms < 90:
        return f"{ms}m前"
    if ms < 2880:
        return f"{ms // 60}h前"
    return f"{ms // 1440}d前"


def _classify(job: Dict[str, Any], sched: Dict[str, Dict[str, Any]]) -> Tuple[str, str]:
    """(emoji, note) —— 失败优先，其次从未成功，其次过期，否则正常。"""
    s = sched.get(job["name"], {})
    fails = s.get("consecutive_failures") or 0
    status = s.get("last_run_status")
    if status == "failed" or fails > 0:
        return "🔴", f"失败{('×' + str(fails)) if fails > 1 else ''}"
    if job.get("last_success_at") is None:
        return "⚪", "从未成功"
    if job.get("is_stale"):
        return "🟡", f"{_age(job.get('minutes_since_success'))}没更新"
    return "✅", ""


async def run() -> Dict[str, Any]:
    from datetime import datetime, timezone
    from agent.finance.scheduler.api import scanner_health
    from agent.finance.scheduler.core import connect
    from agent.finance import agent_alerts

    health = scanner_health()
    jobs: List[Dict[str, Any]] = health.get("jobs", [])

    sched: Dict[str, Dict[str, Any]] = {}
    data_lines: List[str] = []
    with connect() as c:
        for r in c.execute(
            "SELECT job_name, last_run_status, consecutive_failures FROM scheduler_jobs"
        ).fetchall():
            sched[r["job_name"]] = {
                "last_run_status": r["last_run_status"],
                "consecutive_failures": r["consecutive_failures"],
            }
        for table, tcol, label in _DATA_TABLES:
            try:
                n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if tcol:
                    last = c.execute(f"SELECT MAX({tcol}) FROM {table}").fetchone()[0]
                    n24 = c.execute(
                        f"SELECT COUNT(*) FROM {table} "
                        f"WHERE {tcol} >= datetime('now','-1 day')"
                    ).fetchone()[0]
                    stamp = str(last)[11:16] if last else "—"
                    data_lines.append(f"· {label}: {n} 行 (+{n24}/24h), 最新 {stamp}")
                else:
                    data_lines.append(f"· {label}: {n} 行")
            except Exception:
                data_lines.append(f"· {label}: 查询失败")

    classified = [(*_classify(j, sched), j) for j in jobs]
    bad = [(e, note, j) for (e, note, j) in classified if e != "✅"]
    n_ok = sum(1 for (e, _, _) in classified if e == "✅")
    has_failed = any(e == "🔴" for (e, _, _) in classified)
    day = datetime.now(timezone.utc).date().isoformat()

    # ── 简报 ──
    lines: List[str] = [
        f"🔍 定时任务巡检 · {day}",
        f"✅ {n_ok}/{len(jobs)} 正常" + (f" · ⚠️ {len(bad)} 需注意" if bad else " · 全部健康"),
    ]
    if bad:
        lines.append("")
        lines.append("需注意：")
        # 🔴 失败排最前，其次 ⚪ 从未，其次 🟡 过期
        order = {"🔴": 0, "⚪": 1, "🟡": 2}
        for e, note, j in sorted(bad, key=lambda x: order.get(x[0], 9)):
            lines.append(f"{e} {j['name']} — {note}")

    # ── 详细（全部任务）──
    lines.append("")
    lines.append("—— 详细（全部任务）——")
    for e, note, j in classified:
        lines.append(f"{e} {j['name']} · {_age(j.get('minutes_since_success'))} · {j['cron']}")

    # ── 数据落库 ──
    lines.append("")
    lines.append("—— 数据落库 ——")
    lines.extend(data_lines)

    msg = "\n".join(lines)

    # dashboard 铃铛
    try:
        agent_alerts.upsert_alert(
            dedup_key=f"sched_health_{day}", source="scheduler_health", ticker="",
            severity=("P1" if has_failed else "P2"),
            title=f"定时任务巡检 {n_ok}/{len(jobs)} 正常", body=msg,
        )
    except Exception:
        logger.warning("[scheduler_health_digest] bell failed", exc_info=True)

    # Telegram（push_to_telegram 读 repo .env）
    try:
        agent_alerts.push_to_telegram(msg, dry_run=False)
    except Exception:
        logger.warning("[scheduler_health_digest] telegram failed", exc_info=True)

    summary = {"status": "completed", "n_jobs": len(jobs), "n_ok": n_ok, "n_bad": len(bad)}
    logger.info("[scheduler_health_digest] %s", summary)
    return summary
