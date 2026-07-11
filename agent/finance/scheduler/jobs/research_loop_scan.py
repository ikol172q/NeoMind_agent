"""纪律化 IC 深研 loop — 每工作日自动扫新的低覆盖小盘 insider 集群触发，深研
(anchored 10-K crux facts)→ 出机制 + 保守 conviction → 自动 sizing → 产纪律
thesis(机制/认知缺口/Invalidation/退役/Sizing)。

「机器自己筛」：让前向验证的 thesis 组合(breadth = 并行前向时钟)不靠手动跑就增长。
edge 稀缺、大多数候选是 pass 是正常的——loop 的价值是持续筛出那极少数真高 IC 的。

有界(limit)因 anchored 深研慢(~90s/名)；用 to_thread 跑阻塞代码不阻塞事件循环；
graceful：某名字抓不到 crux / synthesize 无机制则 skip，不崩。只 POST thesis，永不下单。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

JOB_NAME = "research_loop_scan"
DEFAULT_CRON = "0 19 * * 1-5"   # 工作日 19:00 — 在 eod 刷新 + 当日 insider 数据之后
DESCRIPTION = (
    "每工作日扫新的低覆盖小盘 insider 集群触发 → anchored 深研 → 纪律 IC thesis"
    "(机制/认知缺口/Invalidation/退役/Sizing)。机器自己筛、产 breadth，propose-not-dispose。"
)


async def run() -> Dict[str, Any]:
    from agent.finance import research_loop
    # research_loop.run 是同步阻塞(HTTP + anchored ~90s/名)，丢到线程池跑，别阻塞事件循环。
    out = await asyncio.to_thread(research_loop.run, 2)
    summary = {"status": "completed", "n_theses": len(out or []),
               "theses": [{"ticker": r.get("ticker"), "conviction": r.get("conviction"),
                           "thesis_id": r.get("thesis_id")} for r in (out or [])]}
    logger.info("[research_loop_scan] %s", summary)
    return summary
