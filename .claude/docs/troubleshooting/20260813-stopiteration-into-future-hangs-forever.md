# 2026-08-13 — 用尽的 `side_effect` 在 executor 里 = 整套测试永久挂死

接 [20260809-suite-never-finished.md](20260809-suite-never-finished.md)。那份记录说挂死点 2
在 71%、是「asyncio 无限等待、具体哪个测试尚未定位」。这次定位到了，**位置是 28% 不是 71%**
（百分比会随 collection 结果变，见下），元凶是 `tests/test_hackernews_full.py::
TestFetchTopStories::test_fetch_top_stories_success`。

## 现象

- 进度停在 `[ 28%]`，**CPU 0.0%**（阻塞，不是空转）
- `sample` 的叶子：`_queue` → `PyThread_acquire_lock_timed` → `__psynch_cvwait`
- faulthandler 主线程栈：`pytest_asyncio → run_until_complete → run_forever →
  _run_once → selectors.select` —— 事件循环在等一个永远不会 resolve 的 future
- ThreadPoolExecutor 的 worker 全部空闲在 `thread.py:75 _worker` 的 `work_queue.get()`

⚠️ **`_queue` 的叶子会骗人**：那是**空闲 worker** 在等新任务，不是挂死点。
真正卡住的是主线程的事件循环。只看 `sample` 会追错方向，必须配 faulthandler 拿 Python 层栈。

## 根因（算术对不上）

```python
# agent/integration/hackernews.py
story_ids = resp.json()[:limit * 2]      # ← 故意过取，给 min_score 过滤留余量
...
await asyncio.gather(*[loop.run_in_executor(None, fetch_story, sid) for sid in batch])
```

测试给的 id 列表是 `[1,2,3,4,5]`、`limit=3` → `[:6]` = **5 个 id** → `fetch_story` 被调 **5 次**。
而测试只准备了 **3 个** `side_effect`：

```python
mock_fetch.side_effect = [HNStory(...), HNStory(...), HNStory(...)]   # 只有 3 个
```

第 4、5 次调用 → `MagicMock` 抛 `StopIteration` → 在 executor 线程里被 future 捕获 →
`_chain_future._set_state` 试图 `set_exception`：

```
TypeError: StopIteration interacts badly with generators and cannot be raised into a Future
```

**这个 TypeError 发生在事件循环的 callback 里，被当成 "Exception in callback" 打印后吞掉，
future 永远停在 pending** → `await gather(...)` 无限等待。

对照实验（其它一律不动，只把 side_effect 从 3 个改成 5 个）：

```
现状 (3 个): ⛔ HUNG (8s 超时未返回)
改成 5 个:   ✅ 返回 3 条
实测 fetch_story 真实调用次数: 5 (ids=[1,2,3,4,5])
```

## 修法

**定长 `side_effect` 列表 = 把「被调多少次」这个假设静默硬编码进测试。**
被测函数一旦过取 / 批处理 / 重试，数量立刻对不上。改成按 key 查表的 callable：

```python
stories_by_id = {sid: HNStory(id=sid, ...) for sid in [1, 2, 3, 4, 5]}
mock_fetch.side_effect = lambda story_id: stories_by_id.get(story_id)
assert mock_fetch.call_count == 5      # 把过取本身也断言掉
```

## 系统性防线：per-test timeout

单点修完还会有下一个。已在 `pyproject.toml` 加：

```toml
timeout = 300
timeout_method = "signal"
```

- `signal`（SIGALRM）**中断该测试后让整轮继续**；`thread` 方法会杀掉整个进程，达不到目的
- 300s 是为 `tests/llm` 的真实 API 往返留的余量
- 实测：合成一个「永不 resolve 的 future」测试，被转成**单个 failed**，同批另外 2 个照常 passed

## 顺带清掉的三个 collection error（62 个测试从来没被收集过）

| 文件 | 病因 | 处理 |
|---|---|---|
| `test_token_budget.py:143` | `IndentationError` —— `budget.consume(1)` 没缩进进 `for` | 补缩进 |
| `test_search.py` | `OptimizedDuckDuckGoSearch` 已搬到 `agent.search_legacy`（`agent/core.py` 仍在用作 fallback） | 改 import 路径 |
| `test_chat_stream.py` | `agent/finance/chat_stream.py` 在 `c000f1a`「drop Chat tab」被有意删除，三个 API 全仓不存在 | 删除测试文件 |

**collection error 是静默的覆盖空洞**：`--continue-on-collection-errors` 让整轮照样"成功"结束，
而那些文件的测试一个都没跑。修完 6184(+3 error) → **6246(0 error)**。

### 那个缩进错误挡住了三个生产 bug

补上缩进、让 `test_token_budget.py` 第一次被收集之后，立刻炸出三个**从来没人见过的真 bug**：

**① `TokenBudget` 用 `threading.Lock()` 而方法之间互相调用 → 两个方法无条件死锁**

```python
def reserve(self, tokens):
    with self._lock:
        if not self.can_proceed(tokens):   # can_proceed 自己也 with self._lock
            ...
def get_stats(self):
    with self._lock:
        return {... "remaining": self.remaining(),      # 同样再取一次锁
                    "usage_ratio": self.usage_ratio(),
                    "should_warn": self.should_warn(), ...}
```

`Lock` 不可重入 → `reserve()` 和 `get_stats()` **每次调用、每个进程、100% 必死**。
修法：`threading.Lock()` → `threading.RLock()`（一个词）。

⚠️ **探针一旦死锁就污染后续所有探测**：第一个卡住的线程永久持锁，之后 `release`/`consume`/
`reset` 全都"看起来"死锁。必须**每个方法用全新实例单独测**，否则会把 6 个方法误判成全坏
（本次先误判了一次）。真实结果：13 个方法里只有 2 个坏。

**② `store_tool_result()` 里 `Path` 从来没被 import** → `NameError`，凡内容 >100KB 必炸。

**③ `TokenBucketLimiter`：`rate < 1.0` 的任何配置都会让调用方永久挂起**（`agent/search/sources.py`）

```python
self.tokens = min(self.rate, ...)   # 桶容量 = rate
if self.tokens >= 1.0:              # 而每次取用固定 1.0
```

`rate=0.1, per=1.0`（合法的「每 10 秒一次」）→ tokens 永远被压在 0.1，够不到 1.0 →
`while True` 里无限 `await asyncio.sleep()`。容量和取用量单位不一致。
修法：容量改 `max(rate, 1.0)`，`rate >= 1.0` 的行为完全不变（生产用的 2.0 不受影响）。

**教训：一个缩进错误 = 三个生产 bug 的免死金牌。** collection error 必须当 P0 清零，
因为它让整个文件的测试静默消失，而 CI 仍然报"成功"。

## 顺带修掉的心跳线程泄漏（115 → 0）

`HeartbeatWriter.stop()` 只翻 `_running=False`，**不 join**，而线程 park 在 `time.sleep(30)` 里
根本看不到标志位；且**全仓 0 个调用者**。改成 `threading.Event` + join，加 `stop_all_heartbeats()`
供 `tests/conftest.py` 逐测试清理。

⚠️ 第一版修复自己引入了新洞，被自己写的测试当场抓到：

```python
def stop(self):
    if not self._running:      # ← 看着无害，实则致命
        return
```

只要 `_running` 被别的路径清掉（正是旧 `stop()` 干的事），这个 fast path 就让线程永远搁浅。
**守卫要挂在「线程活着吗」上，不是挂在标志位上**；`is_running()` 同理，必须报告线程而非标志位。

## 教训

1. **`_queue` 在栈里通常是无辜的空闲 worker。** 阻塞型挂死要拿 Python 层栈（faulthandler）
   才能分清「谁在等」和「谁在闲」。
2. **别用进度百分比当路标。** 上一份文档记的是 71%，这次是 28% —— 因为 collection
   结果一变，分母就变。用 `-v` 的最后一行点名。
3. **`StopIteration` 是 asyncio 里唯一会「静默变成永久挂起」的异常。** 任何
   `run_in_executor` / `gather` 包住的 mock，一旦 `side_effect` 用尽就是这个后果。
4. **修复本身也要被测试打一遍。** 这次的第一版 `stop()` 逻辑上"显然正确"，
   跑起来就露馅。
