"""IB Gateway 掉线预警 —— 网关登出/掉线时推 P1,否则你的 IBKR 真仓静默裸管.

IBKR 强制每日重启,会话每周过期 → 网关一掉,dashboard 对你 IBKR 就瞎、系统无法
跟踪真仓。launchd watchdog 负责把 app 拉起来;本 job 负责「掉了通知你去重新登录」。

每 20 分钟用一个**轻量 socket 探测**查 API 端口(4001)是否可连 —— 不走 ib_insync
(避免和 scheduler 的 async 事件循环冲突),端口拒连 = 网关掉/登出。掉线时写一条 P1
`agent_alert`(按天去重,不刷屏)并即时 push;token/chat 由 agent_alerts 自解析,
未配则优雅 no-op(alert 仍进 dashboard 铃铛)。propose-not-dispose。
"""
from __future__ import annotations

import logging
import os
import socket
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

JOB_NAME = "ibkr_gateway_health"
DEFAULT_CRON = "*/20 * * * *"   # 每 20 分钟
DESCRIPTION = (
    "每 20 分钟探测 IB Gateway API 端口;掉线/登出 → 推 P1 提醒重新登录"
    "(按天去重),否则 IBKR 真仓在 dashboard 上隐形、系统无法跟踪。"
)


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


async def run() -> Dict[str, Any]:
    from agent.finance import agent_alerts

    host = os.getenv("IB_GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("IB_GATEWAY_PORT", "4001"))

    if _port_open(host, port):
        return {"status": "completed", "connected": True, "alerted": False}

    day = datetime.now(timezone.utc).date().isoformat()
    up = agent_alerts.upsert_alert(
        dedup_key=f"ibkr_gateway_down_{day}",
        source="ibkr_gateway",
        ticker="",
        severity="P1",
        title="🔌 IB Gateway 掉线",
        body=(f"IB Gateway 连不上 ({host}:{port}) —— 你的 IBKR 真仓此刻在 dashboard "
              "上隐形、系统无法跟踪。请重新登录 IB Gateway。"
              "(watchdog 会自动拉起 app;每周会话过期需你手动登录一次。)"),
    )
    push = (agent_alerts.push_p1_now(dry_run=False)
            if up.get("is_new") else {"pushed": 0, "skip": "dedup-same-day"})
    summary = {"status": "completed", "connected": False,
               "alert_new": up.get("is_new"), "p1_push": push}
    logger.info("[ibkr_gateway_health] %s", summary)
    return summary
