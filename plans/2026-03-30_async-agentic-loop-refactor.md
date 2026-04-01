# Plan: Agentic Loop 全面异步化重构

**日期**: 2026-03-30
**问题**: 工具执行卡在"⚙️ 正在执行工具..."无响应
**根因**: 同步阻塞的 `AgenticLoop.run()` + 同步 `llm_caller` + 同步工具执行，全部阻塞 asyncio 事件循环

---

## 受影响文件总览

| 文件 | 改动级别 | 说明 |
|------|----------|------|
| `agent/agentic/agentic_loop.py` | **重写** | `run()` 从同步生成器改为异步生成器 |
| `agent/agentic/__init__.py` | 微调 | 更新导出 |
| `agent/integration/telegram_bot.py` | **重写** | `_run_agentic_tool_loop` 改用 `async for` + `aiohttp` |
| `cli/neomind_interface.py` | 中等 | `_run_agentic_loop` 适配异步接口（用 `asyncio.run`） |
| `agent/coding/tools.py` | 中等 | 工具执行函数加 async 变体 |
| `agent/coding/persistent_bash.py` | 小改 | 加 `async_execute()` 包装 |
| `agent/coding/tool_schema.py` | 小改 | `ToolDefinition.execute` 支持 async callable |
| `tests/test_agentic_loop_canonical.py` | **重写** | 所有测试改为 async |
| `tests/test_cli_agentic_refactor.py` | 中等 | 适配新接口 |
| `tests/test_tool_pipeline_e2e.py` | 中等 | 适配新接口 |
| `tests/test_telegram_hooks_restart.py` | 中等 | 适配新接口 |
| `tests/test_error_prone_areas.py` | 小改 | 适配新接口 |

---

## Step 1: `agentic_loop.py` — 核心异步化

**当前问题**:
- `run()` 是 `Iterator[AgenticEvent]`（同步生成器）
- 内部调用 `llm_caller(messages)` 是同步阻塞 HTTP
- 内部调用 `self._execute(tool_call)` 是同步阻塞（Bash 工具可能跑几十秒）

**改动**:

```python
# 之前
def run(self, llm_response, messages, llm_caller) -> Iterator[AgenticEvent]:
    ...
    current_response = llm_caller(messages)  # 阻塞！
    result = self._execute(tool_call)         # 阻塞！

# 之后
async def run(self, llm_response, messages, llm_caller) -> AsyncIterator[AgenticEvent]:
    ...
    current_response = await llm_caller(messages)   # 非阻塞
    result = await self._execute(tool_call)          # 非阻塞
```

具体改动点:

1. **签名变更**: `def run(...)` → `async def run(...)`，返回类型 `Iterator` → `AsyncIterator`
2. **`llm_caller` 类型**: `Callable[[List], str]` → `Callable[[List], Awaitable[str]]`
3. **`_execute` 方法**: `def _execute(...)` → `async def _execute(...)`
   - 内部判断 `tool_def.execute` 是否为 coroutine，是则 `await`，否则用 `asyncio.to_thread()` 包装
4. **hooks 调用**: `pre_llm_call()` 和 `post_response()` 是纯 CPU 计算，用 `await asyncio.to_thread()` 包装，避免阻塞（它们内部可能有 DB 写入）
5. **`yield` → 保持 yield**: async generator 中 `yield` 正常工作，无需改

**关键设计决策**:

`_execute` 内部对同步工具函数的处理策略 —— 因为 `ToolRegistry` 里注册的工具函数（`_exec_bash`、`_exec_read` 等）都是同步的，直接全部重写为 async 改动面太大。采用**适配器模式**：

```python
async def _execute(self, tool_call):
    tool_def = self.registry.get_tool(tool_call.tool_name)
    ...
    params = tool_def.apply_defaults(tool_call.params)

    # 适配：如果 execute 是 async 就 await，否则扔线程池
    if asyncio.iscoroutinefunction(tool_def.execute):
        return await tool_def.execute(**params)
    else:
        return await asyncio.to_thread(tool_def.execute, **params)
```

这样既支持未来新增的 async 工具，也兼容现有的所有同步工具，**不需要改 tools.py 里的任何工具函数**。

---

## Step 2: `telegram_bot.py` — Telegram 端适配

**当前问题**:
- `llm_caller` 用 `requests.post`（同步阻塞）
- `for event in agentic.run(...)` 是同步迭代

**改动**:

### 2a. `llm_caller` 改用 `aiohttp`

```python
# 之前 (telegram_bot.py:3799)
def llm_caller(msgs):
    resp = req.post(provider["base_url"], ..., timeout=90, stream=True)
    for line in resp.iter_lines(decode_unicode=True):
        ...

# 之后
async def llm_caller(msgs):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            provider["base_url"],
            headers={...},
            json={...},
            timeout=aiohttp.ClientTimeout(total=90),
        ) as resp:
            if resp.status != 200:
                raise Exception(f"LLM API error: {resp.status}")
            async for line in resp.content:
                line = line.decode("utf-8").strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                # ... 解析 chunk 逻辑不变 ...

    if not full_text.strip():
        # 非流式 fallback 也用 aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(...) as resp2:
                ...

    return full_text
```

### 2b. 迭代改为 `async for`

```python
# 之前 (telegram_bot.py:3862)
for event in agentic.run(initial_response, messages, llm_caller):

# 之后
async for event in agentic.run(initial_response, messages, llm_caller):
```

事件处理逻辑（`tool_start`/`tool_result`/`llm_response`/`done`/`error`）保持不变，它们已经是 `await` 的。

### 2c. 加总超时保护

```python
try:
    await asyncio.wait_for(
        self._run_agentic_tool_loop(msg, response_text.strip(), ...),
        timeout=300,  # 5 分钟硬上限
    )
except asyncio.TimeoutError:
    await msg.reply_text("⚠️ 工具执行超时（5分钟），已终止")
```

### 2d. 依赖变更

在 `telegram_bot.py` 顶部或 `_run_agentic_tool_loop` 内新增：
```python
import aiohttp
```

需要确保 Docker 镜像中已安装 `aiohttp`。检查 `pyproject.toml` 或 `requirements.txt` 里是否已有。

---

## Step 3: `cli/neomind_interface.py` — CLI 端适配

**当前问题**: CLI 是同步的（非 asyncio），但 `AgenticLoop.run()` 改成了 async。

**改动策略**: 在 CLI 的 `_run_agentic_loop` 中用 `asyncio.run()` 桥接。

```python
def _run_agentic_loop(self, max_iterations=None):
    ...
    loop = AgenticLoop(registry, config)

    # llm_caller 需要是 async 的
    async def async_llm_caller(messages):
        # CLI 的 stream_response 是同步的，包装一下
        return await asyncio.to_thread(self._sync_llm_caller, messages)

    def _sync_llm_caller(self, messages):
        self.chat._skip_next_user_add = True
        return self.chat.stream_response("[Continue based on the tool results above.]")

    # 用 asyncio.run 来跑异步循环
    async def _async_loop():
        async for event in loop.run(last_response, history, async_llm_caller):
            # 事件处理逻辑保持不变（全是同步的 print/spinner）
            ...

    asyncio.run(_async_loop())
```

**注意**: 如果 CLI 的上层调用栈中已经有 asyncio event loop 在跑，`asyncio.run()` 会报错。需要检查：
- 如果已有 loop → 用 `loop.run_until_complete()` 或 `nest_asyncio`
- 如果没有 loop（典型的 CLI 场景）→ `asyncio.run()` 直接可用

根据代码，CLI 端走的是标准同步 Python 入口，没有现有 event loop，所以 `asyncio.run()` 可以直接用。

---

## Step 4: `agent/coding/tool_schema.py` — ToolDefinition 支持 async

**改动（可选但推荐）**:

在 `ToolDefinition` 类上加一个 `is_async` 属性方便判断：

```python
@property
def is_async(self) -> bool:
    return asyncio.iscoroutinefunction(self.execute)
```

这是纯粹的便利方法，不改动现有逻辑。

---

## Step 5: `agent/agentic/__init__.py` — 更新导出

```python
# 无需改动，AgenticLoop/AgenticEvent/AgenticConfig 的导出路径不变
# 只是 AgenticLoop.run() 的签名变了
```

---

## Step 6: 测试文件更新

### 6a. `tests/test_agentic_loop_canonical.py`（改动最大）

这个文件有大量 `for event in loop.run(...)` 的同步测试。全部需要改为：

```python
import asyncio

class TestAgenticLoopBasicFlow(unittest.TestCase):
    def test_xxx(self):
        async def _test():
            events = []
            async for event in loop.run(response, messages, mock_llm_caller):
                events.append(event)
            # assertions...

        asyncio.run(_test())
```

或者用 `unittest.IsolatedAsyncioTestCase`（Python 3.8+）：

```python
class TestAgenticLoopBasicFlow(unittest.IsolatedAsyncioTestCase):
    async def test_xxx(self):
        events = []
        async for event in loop.run(response, messages, mock_llm_caller):
            events.append(event)
```

`mock_llm_caller` 也要改成 async：

```python
# 之前
mock_llm_caller = Mock(return_value="no tool call here")

# 之后
mock_llm_caller = AsyncMock(return_value="no tool call here")
```

### 6b. 其他测试文件

- `test_cli_agentic_refactor.py` — mock `AgenticLoop` 的 `run()` 返回 `AsyncMock`
- `test_tool_pipeline_e2e.py` — `AgenticLoop._execute` 改为 async，测试适配
- `test_telegram_hooks_restart.py` — 已经用 `AsyncMock`，改动较小
- `test_error_prone_areas.py` — `_execute` 相关测试改为 async

---

## Step 7: 依赖和基础设施

### 7a. `pyproject.toml` / `requirements.txt`
确保 `aiohttp` 在依赖列表中（Telegram bot 大概率已经装了，`python-telegram-bot` 内部就用 `httpx`）。

### 7b. `Dockerfile`
确认基础镜像中有 `aiohttp`。如果没有，加到 pip install 行。

### 7c. Python 版本
需要 Python 3.10+（`async for` + `AsyncIterator` + `asyncio.to_thread` 都需要 3.9+，`aiohttp` 推荐 3.10+）。

---

## 执行顺序（推荐）

```
Phase 1 — 核心（修复卡死问题）
  ├── Step 1: agentic_loop.py 异步化
  ├── Step 2: telegram_bot.py 适配
  └── 验证: Telegram 端工具调用不再卡死

Phase 2 — CLI 适配
  ├── Step 3: neomind_interface.py 适配
  └── 验证: CLI coding 模式工具调用正常

Phase 3 — 测试更新
  ├── Step 6a: test_agentic_loop_canonical.py
  ├── Step 6b: 其他测试文件
  └── 验证: pytest 全部通过

Phase 4 — 收尾
  ├── Step 4: tool_schema.py（可选）
  ├── Step 7: 依赖检查
  └── Docker 重新构建测试
```

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| CLI 端 `asyncio.run()` 嵌套冲突 | CLI 崩溃 | 检测现有 event loop，fallback 到 `to_thread` 方案 |
| `aiohttp` 与现有 `requests` 行为差异 | 流式解析出错 | 单独测试 llm_caller 的流式/非流式路径 |
| 工具函数中隐含的线程不安全 | 数据竞争 | `to_thread` 自带 GIL 保护，大部分 IO 场景安全 |
| 大量测试需要重写 | 开发时间长 | 可用 helper 函数批量适配，或分批推进 |
| `persistent_bash.py` 的 `queue.get` 阻塞 | 工具执行慢但不卡死 | `to_thread` 已解决；后续可改为 `asyncio.subprocess` |

---

## 核心改动量估算

- `agentic_loop.py`: ~50 行改动（主要是加 `async`/`await` 关键字）
- `telegram_bot.py`: ~80 行改动（`llm_caller` 重写 + `for` → `async for` + 超时）
- `neomind_interface.py`: ~30 行改动（asyncio.run 桥接）
- 测试文件: ~200 行改动（机械性替换 `Mock` → `AsyncMock`，`for` → `async for`）

总计约 **360 行改动**，核心逻辑变动集中在 `agentic_loop.py` 的约 50 行。
