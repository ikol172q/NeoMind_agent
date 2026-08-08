"""回归: backfill_eod 不许泄漏 sqlite 连接 (launchd 只有 256 个 fd)。

真事故 (2026-07-30):
`backfill_eod` 每个 ticker 都写 `with connect() as conn:` —— 但
`with <sqlite3.Connection>` **只提交事务, 不关闭连接**。690 个 ticker 的循环
因此泄漏 690 条连接, 每条在 WAL 模式下占 3 个 fd (db / -wal / -shm)。

为什么一直没被发现: 交互 shell 的 `ulimit -n` 是 **1,048,576**, 手跑永远正常。
但 **launchd 的 maxfiles 只有 256** → 定时任务每天跑到第 ~127 个 ticker 就死于
``sqlite3.OperationalError: unable to open database file`` (SQLITE_CANTOPEN),
且 launchd 只把 traceback 写进日志、没有任何告警。

实测后果 (修复当天): 690 个 symbol 里 **550 个陈旧**, 按字母序靠后的全军覆没
(QQQ 第 521 位 / SPY 579 / SSP 584 / VITL 655), 最早的陈旧位次 = 117, 与第 127
个连接失败的实测点吻合。而 `market_data_daily` 是相关性 / 回撤告警 / regime /
回测共用的价格底座。

**这条测试用真实的低 fd 上限跑, 不是 mock** —— 因为 bug 的本质就是"只在低上限下暴露"。
"""
from __future__ import annotations

import os
import resource
import subprocess
import sys
import textwrap

import pytest

# 逼近 launchd 的 maxfiles=256; 留点余量给 pytest 自己已经开着的 fd。
LAUNCHD_MAXFILES = 256


def _run_with_fd_limit(body: str, limit: int = LAUNCHD_MAXFILES) -> subprocess.CompletedProcess:
    """在**独立子进程**里压低 RLIMIT_NOFILE 后执行 body。

    必须开子进程: 压低当前 pytest 进程的 fd 上限会波及其它测试。
    """
    script = textwrap.dedent(f"""
        import resource
        resource.setrlimit(resource.RLIMIT_NOFILE, ({limit}, {limit}))
        {textwrap.indent(textwrap.dedent(body), ' ' * 8).lstrip()}
    """)
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          timeout=180, env={**os.environ})


def _hard_limit_allows(limit: int) -> bool:
    return resource.getrlimit(resource.RLIMIT_NOFILE)[1] >= limit


@pytest.mark.skipif(not _hard_limit_allows(LAUNCHD_MAXFILES),
                    reason="系统硬上限低于 launchd 的 256, 无法复现该场景")
def test_repeated_connects_survive_launchd_fd_limit():
    """修复前: 第 ~127 次 connect 抛 'unable to open database file'。"""
    r = _run_with_fd_limit("""
        from contextlib import closing
        from agent.fin_provider import fin_module
        connect = fin_module('persistence').connect
        for i in range(1, 500):
            with closing(connect()) as c, c:
                c.execute("SELECT 1")
        print("OK")
    """)
    assert "OK" in r.stdout, f"低 fd 上限下连接耗尽了:\nstdout={r.stdout}\nstderr={r.stderr[-2000:]}"
    assert "unable to open database file" not in r.stderr


def test_persistence_layer_autocloses_on_context_exit():
    """真正的防线在**另一个仓**, 这条守着它别回退。

    2026-08-07 更新: 本文件原有一条反向对照测试, 断言"旧写法(裸 `with connect()`)
    在低 fd 上限下确实会挂"。它现在**失败**了 —— 而这正是对照测试存在的意义:
    前提变了。

    变化的原因: `connect()` 已改为返回 ``_AutoClosingConnection``
    (``neomind-dashboard`` 私有仓的 ``neomind_dashboard/persistence/__init__.py``),
    其 ``__exit__`` 在提交/回滚之后**还会 close()**。所以裸 `with connect()` 不再泄漏,
    500 条连接跑完只剩个位数 fd。

    由此产生两个必须写下来的结论:

    1. ``backfill_eod`` 里的 ``closing(connect())`` 现在是**防御性冗余, 不是那个修复本身**。
       留着无害(``closing`` 二次 close 是 no-op), 但别以为删了它就等于把 bug 放回来 ——
       真正拦着 bug 的是上游那个 factory。
    2. 该 factory **不在本仓**。NeoMind 侧此前没有任何测试守着这个跨仓依赖:
       只要 dashboard 那边把 ``factory=_AutoClosingConnection`` 拿掉, 690-ticker 的
       循环会**静默**退回每天挂在第 ~127 个 ticker, 而本仓 CI 全绿。
       本条测试就是补这个缺口。
    """
    r = _run_with_fd_limit("""
        from agent.fin_provider import fin_module
        connect = fin_module('persistence').connect
        held = []
        for i in range(1, 500):
            c = connect()          # 裸 with —— 依赖 _AutoClosingConnection 兜底
            with c:
                c.execute("SELECT 1")
            held.append(c)         # 故意持有引用, 排除 GC 关闭的干扰
        print("AUTOCLOSED")
    """)
    assert "AUTOCLOSED" in r.stdout, (
        "持久层不再自动关闭连接 —— 跨仓依赖已回退。\n"
        "去 neomind-dashboard 的 persistence.connect() 确认 factory=_AutoClosingConnection 还在;\n"
        f"stdout={r.stdout}\nstderr={r.stderr[-2000:]}"
    )


def test_backfill_eod_closes_its_connection():
    """静态防线: 源码里必须用 closing() 包住 connect(), 别退回裸 `with connect()`。"""
    import agent.data_sources.eod_backfill as m
    import inspect

    src = inspect.getsource(m.backfill_eod)
    assert "closing(connect())" in src, \
        "backfill_eod 必须用 closing() 关连接 —— 裸 `with connect()` 只提交不关闭"
