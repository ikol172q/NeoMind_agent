# 2026-08-09 — 整套测试从来没跑完过（两处挂死，性质不同）

## 起因

交接记录里写的是「py3.14 偶发 pytest 清理阶段 Too many open files，不算硬 blocker」。

实测：**这个描述本身是错的**。套件不是偶发告警，是**跑到 54% 必然挂死、永不返回**。
所有历史上记录的 "313 passed + 93 passed" 之类数字，**全是子集成绩**——
这个仓在任何一个解释器上都不存在过一次完整的全量运行。

## 挂死点 1（已修）：mock 了 `get`，代码调的是 `get_nowait`

`tests/test_persistent_bash_full.py` 五个测试：

```python
mock_stdout_q.get.side_effect = [...]        # 配的是 get
```

而 `execute()` 第一件事是 `_drain_queue()`：

```python
def _drain_queue(q):
    while True:
        try:
            lines.append(q.get_nowait())      # ← 调的是 get_nowait
        except queue.Empty:
            break
```

未配置的 MagicMock，`get_nowait()` **永远返回新 Mock、永远不抛 `queue.Empty`**
→ `while True` 100% CPU 空转 + `lines` 无限增长。

**它挂在任何断言之前**，所以这五个测试从来没验证过任何东西 —— 一个永不执行的测试
＝ 一个永不会失败的断言。修完立刻暴露出一条过期断言（`"Exit code: 1"` vs 实际
`"Exit code 1 (no stderr)"`，格式是有意改的），坐实了这一点。

与 `QueryEngine` 调 `ToolRegistry.execute`（真 registry 没这方法）是**同一类病**：
mock 与真实 API 对不上。那次的后果是「死代码看起来被测过」，这次是「整个套件被锁死」。

## 挂死点 2（未修，已知 debt）：asyncio 无限等待

修掉点 1 后跑到 **71%** 再次停住，**但性质不同**：

| | 点 1 | 点 2 |
|---|---|---|
| CPU | 180%（空转） | **0.1%（阻塞）** |
| 栈叶子 | `_drain_queue` 的 `while True` | `select_kqueue_control_impl → kevent` |
| 判定 | 死循环 | **asyncio 事件循环无限期等待** |

`kevent` = macOS 上 asyncio 的 KqueueSelector 在等事件。即某个 async 测试
`await` 了一个永不完成的对象且没设超时。**具体是哪个测试尚未定位**。

## 定位方法（照抄）

**别用 `-q` 追挂死** —— 它只打点，问不出测试名。用 `-v`：pytest 会**先打印测试名、
跑完再补结果**，所以日志最后一行（没有结果的那条）就是正在跑的那个。

```bash
# 1. 完全脱离 agent 会话跑（agent 起的后台任务会被会话边界 SIGKILL；
#    nohup 从交互 shell 起的能活下来。macOS 没有 setsid。）
(nohup .venv/bin/python -m pytest tests/ -v --continue-on-collection-errors \
   > /tmp/v.log 2>&1 &)

# 2. 判定「卡住」必须同时看两个量，缺一会误判
ps -p $PID -o %cpu=        # 高 CPU = 死循环；接近 0 = 阻塞。两者修法完全不同
stat -f '%Sm' /tmp/v.log   # 日志多久没动了

# 3. 拿栈。py-spy 在 macOS 需要 root，但内建的 sample 不需要
sample $PID 3 -file /tmp/s.txt
# 纯 Python 死循环 → 只见 _PyEval_EvalFrameDefault，命不出函数
# 阻塞 → 能看到 kevent / read / __psynch_cvwait 等真实叶子，信息量大得多

# 4. 要 Python 层的栈又没有 root：用标准库 faulthandler 包一层，
#    并写到独立文件（pytest 的捕获会吞掉 stdout）
python -c "
import faulthandler, sys, pytest
f = open('/tmp/fh.txt','w')
faulthandler.dump_traceback_later(15, exit=True, file=f)
sys.exit(pytest.main(['<单个测试>','-q','-s']))"
```

⚠️ **别用进度百分比反推测试序号**。本次试过：按 `-q` 的点数算出第 3201 个，
查 `--collect-only` 列表得到 `test_paper_trading_risk_enforcement.py`，
单独跑**完全正常**。真凶是 `test_persistent_bash_full.py`，`-v` 直接点名。
收集顺序与实际执行顺序在有 collection error 时对不上，推算不可靠。

## 顺带发现：115 个泄漏的心跳线程

`sample` 显示进程内 134 个线程里 **115 个叫 heartbeat**。
链路：`agent/evolution/scheduler.py:155` → `health_monitor.py:525`
起 `daemon=True, name="heartbeat"` 的线程。

`HeartbeatWriter.stop()` **只置 `_running=False`，不 join，且没人调用**；
`tests/conftest.py` 无任何清理。每个实例化 scheduler 的测试都永久留一个线程。
它们 `sleep(30)` 不烧 CPU，所以不是挂死元凶，但是真实泄漏，且每个线程都在
反复 `mkdir` + 写同一个文件 —— 与最初那条 "Too many open files" 很可能同源。

## 教训

**「不算硬 blocker」这个定性本身要验证。** 一条被当成「偶发告警」记了几天的 debt，
真去跑才发现它意味着「全量测试从来没有绿过」。把没验证过的严重性判断写进交接文档，
下一个人就会继续绕着它走。
