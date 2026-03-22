# Bidirectional LLM Provider Sync — xbar ↔ Telegram Bot

**Date:** 2026-03-22
**Status:** Draft — awaiting approval
**Goal:** 让 xbar (macOS 菜单栏) 和 Telegram bot 双向同步 LLM provider 状态，支持多 bot 独立配置。

---

## 1. 问题分析

### 当前状态

```
┌─────────────┐                    ┌──────────────────────┐
│  xbar 菜单   │  switch-provider.sh │  neomind-telegram    │
│  (macOS)    │ ──────────────────→ │  (Docker container)  │
│             │   改 .env + restart │                      │
│             │                    │  os.environ (内存)    │
│             │ ← ─ ─ ─ ─ ✗ ─ ─ ─ │  /provider 只改内存   │
└─────────────┘   无反向通知        └──────────────────────┘
```

**问题：**
1. xbar → bot: 通过改 .env + restart 容器，有效但粗暴（需重启，丢失上下文）
2. bot → xbar: 完全不同步。`/provider litellm` 只改内存中的 `os.environ`，xbar 看不到
3. 容器重启后：bot 端的切换丢失（因为只改了内存）
4. 单 bot 设计：provider 是全局的，未来加新 agent 无法独立控制

### 目标状态

```
┌─────────────┐         provider-state.json         ┌──────────────────────┐
│  xbar 菜单   │ ←─────── (共享状态文件) ──────────→ │  neomind-telegram    │
│  (macOS)    │         /data/neomind/.neomind/     │  (Docker container)  │
│             │         provider-state.json         │                      │
│  可看到每个   │                                    │  /provider 读写同文件  │
│  bot 的状态   │                                    │  自然语言也可切换      │
│  可独立切换   │                                    │  切换后主动通知群      │
└──────┬──────┘                                    └──────────┬───────────┘
       │                                                      │
       │  ┌──────────────────────────┐                        │
       └──│  future-bot-2 (Docker)   │────────────────────────┘
          │  独立读写自己的 provider   │   同一个 provider-state.json
          └──────────────────────────┘
```

---

## 2. 架构设计

### 2.1 核心：共享状态文件 `provider-state.json`

**位置：** `~/.neomind/provider-state.json` (macOS 本地)
→ Docker 内映射到 `/data/neomind/.neomind/provider-state.json` (通过 neomind-data volume)

**注意：** 目前 `neomind-data` 是 Docker named volume，macOS 端无法直接读写。
需要改为 bind mount（见 3.3）。

**文件格式：**

```json
{
  "version": 1,
  "updated_at": "2026-03-22T10:30:00Z",
  "updated_by": "xbar",
  "bots": {
    "neomind": {
      "provider_mode": "litellm",
      "litellm_model": "local",
      "direct_model": "deepseek-chat",
      "thinking_model": "deepseek-reasoner",
      "updated_at": "2026-03-22T10:30:00Z",
      "updated_by": "xbar"
    }
  },
  "litellm": {
    "base_url": "http://host.docker.internal:4000/v1",
    "health_ok": true,
    "last_health_check": "2026-03-22T10:29:55Z"
  }
}
```

**设计要点：**
- `bots` 字典：每个 bot 独立一个 key，未来加 agent 只需加一个新 key
- `provider_mode`: `"litellm"` 或 `"direct"` — 唯一的状态源
- `updated_by`: 记录是谁最后改的（`"xbar"` / `"telegram"` / `"natural_language"`）
- `litellm.health_ok`: xbar 可以实时显示 LiteLLM 健康状态

### 2.2 读写流程

#### xbar 切换 → bot 热加载（无需重启容器）

```
用户点 xbar 菜单 "NeoMind → LiteLLM"
  │
  ├─ 1. xbar 检查 LiteLLM 健康状态 (curl /health)
  ├─ 2. 写入 provider-state.json: neomind.provider_mode = "litellm"
  ├─ 3. macOS notification: "NeoMind 已切换到 LiteLLM"
  │
  └─ bot 端: 文件监听 / 下次请求时读取
       ├─ 检测到 provider_mode 变化
       ├─ 热切换 provider chain（无需重启）
       └─ 在 Telegram 群里发通知: "🔌 Provider 已被远程切换为 LiteLLM"
```

**关键改进：不再需要 restart 容器。** bot 自行 watch 文件变化或在每次 LLM 请求前读取。

#### bot 端切换 → xbar 自动感知

```
用户在 Telegram 发 "/provider direct" 或 "帮我切到直连 DeepSeek"
  │
  ├─ 1. bot 解析命令 / 自然语言理解
  ├─ 2. 写入 provider-state.json: neomind.provider_mode = "direct"
  ├─ 3. Telegram 回复: "✅ 已切换到 Direct DeepSeek"
  │
  └─ xbar 端: 定时刷新（xbar 本身就是定时执行脚本）
       └─ 读取 provider-state.json，更新菜单栏图标/状态
```

### 2.3 组件清单

| 组件 | 文件 | 职责 |
|------|------|------|
| **ProviderStateManager** | `agent/finance/provider_state.py` (新建) | 读写 provider-state.json 的 Python 类，被 bot 和 CLI 共用 |
| **Bot 集成** | `agent/finance/telegram_bot.py` (改造) | `/provider` 命令和 `_get_provider_chain()` 改为读 state 文件 |
| **xbar 插件** | `xbar/neomind-provider.1m.sh` (新建) | 菜单栏显示当前状态 + 切换按钮，替代旧的 switch-provider.sh |
| **docker-compose.yml** | (改造) | neomind-data 改为 bind mount，让 xbar 能读写 |
| **自然语言触发** | `telegram_bot.py` 的 system prompt (改造) | 让 LLM 识别 "切到本地模型" 等意图并执行 |

### 2.4 ProviderStateManager 接口设计

```python
class ProviderStateManager:
    """Shared provider state — single source of truth for all bots."""

    def __init__(self, state_dir: str = "~/.neomind"):
        self.state_file = Path(state_dir) / "provider-state.json"

    def get_bot_config(self, bot_name: str) -> dict:
        """读取某个 bot 的 provider 配置"""

    def set_provider_mode(self, bot_name: str, mode: str, updated_by: str) -> dict:
        """切换 provider mode，写入文件，返回新配置"""

    def get_provider_chain(self, bot_name: str, thinking: bool = False) -> list:
        """根据 state 文件构建 provider chain（替代现有的 _get_provider_chain）"""

    def get_all_bots(self) -> dict:
        """返回所有 bot 的状态（给 xbar 用）"""

    def update_health(self, litellm_ok: bool):
        """更新 LiteLLM 健康状态"""

    def on_change(self, callback):
        """注册文件变化回调（可选：用 watchdog 或轮询）"""
```

### 2.5 xbar 插件设计

```
菜单栏显示:   🤖 NeoMind: LiteLLM ✅
                │
                ├─ NeoMind
                │   ├─ ✅ LiteLLM (local Qwen3)    ← 当前选中
                │   ├─ ○ Direct (DeepSeek)
                │   └─ ○ Direct (z.ai GLM)
                │
                ├─ [future-bot-2]                   ← 未来扩展
                │   ├─ ...
                │
                ├─ ──────────────
                ├─ LiteLLM: 🟢 healthy
                ├─ Ollama: 🟢 3 models loaded
                └─ 刷新状态
```

**xbar 刷新频率：** 文件名 `neomind-provider.1m.sh` → 每 1 分钟刷新一次。
读 provider-state.json 展示状态，点击菜单项调用 switch 脚本写入 JSON。

### 2.6 Docker volume 改造

**当前（named volume，macOS 不可直接访问）：**
```yaml
volumes:
  - neomind-data:/data/neomind
```

**改为（bind mount，双端可读写）：**
```yaml
volumes:
  - ${NEOMIND_DATA_DIR:-~/.neomind}:/data/neomind/.neomind
```

这样：
- macOS 端：xbar 直接读写 `~/.neomind/provider-state.json`
- Docker 端：bot 读写 `/data/neomind/.neomind/provider-state.json`
- 是同一个物理文件

---

## 3. 状态同步时序图

### 3.1 xbar → bot（远程切换）

```
  xbar (macOS)                 state file               bot (Docker)
  ────────────                 ──────────               ────────────
       │                           │                         │
       │  ① curl LiteLLM /health  │                         │
       │ ─────────────────────→   │                         │
       │  ← 200 OK                │                         │
       │                           │                         │
       │  ② write JSON             │                         │
       │ ─────────────────────→   │                         │
       │  {neomind.provider_mode: │                         │
       │   "litellm"}             │                         │
       │                           │                         │
       │  ③ macOS notification    │  ④ next LLM request     │
       │  "已切换到 LiteLLM"      │ ←─────────────────────  │
       │                           │  read state, detect     │
       │                           │  mode changed           │
       │                           │                         │
       │                           │  ⑤ apply new chain     │
       │                           │ ─────────────────────→  │
       │                           │                         │
       │                           │  ⑥ notify group        │
       │                           │  "🔌 远程切换为 LiteLLM" │
       │                           │ ─────────────────────→  │
```

### 3.2 bot → xbar（Telegram 端切换）

```
  user (Telegram)              bot (Docker)             state file              xbar
  ───────────────              ────────────             ──────────              ────
       │                           │                        │                    │
       │  /provider direct         │                        │                    │
       │ ─────────────────────→   │                        │                    │
       │                           │  ① write JSON          │                    │
       │                           │ ─────────────────→    │                    │
       │                           │  {provider_mode:       │                    │
       │                           │   "direct"}            │                    │
       │                           │                        │                    │
       │  ② "✅ 已切换到 Direct"   │                        │  ③ 1min 定时刷新   │
       │ ←─────────────────────   │                        │ ←─────────────── │
       │                           │                        │  read state         │
       │                           │                        │  update menu icon  │
```

---

## 4. 你没想到可能需要考虑的地方

### 4.1 文件并发写入

xbar 和 bot 可能同时写入 provider-state.json。虽然概率极低（都是人工触发），但需要处理：

**方案：** 用 `fcntl.flock()` (Linux/macOS) 做文件锁。ProviderStateManager 的每次读写都获取排他锁。

### 4.2 LiteLLM 健康感知

切到 LiteLLM 后，如果 LiteLLM/Ollama 挂了，bot 端应该：
1. 自动 fallback 到 direct provider（现有逻辑已有）
2. 写回 state 文件标记 `litellm.health_ok = false`
3. xbar 下次刷新时显示 🔴 不健康
4. **不自动改 provider_mode** — 只是 fallback，用户的选择不变

### 4.3 自然语言切换的边界

"帮我切到本地模型" → bot 切换 provider → OK
"用 DeepSeek 回答我" → 这是临时单次使用还是永久切换？

**建议：** 永久切换需要明确指令（"/provider" 或 "切换到..."），单次临时使用不改 state 文件。在 system prompt 里明确这个规则。

### 4.4 bind mount vs named volume 的权衡

改为 bind mount 后：
- ✅ xbar 可以直接读写
- ⚠️ 需要确保 macOS 端目录已存在（第一次运行前需 `mkdir -p ~/.neomind`）
- ⚠️ 现有 named volume `neomind-data` 里的数据需要迁移（chat history、subscriptions 等）

**方案：** 保留 named volume 用于大数据（SQLite DB 等），只把 provider-state.json 单独 bind mount：

```yaml
volumes:
  - neomind-data:/data/neomind                          # 大数据还是 named volume
  - ${HOME}/.neomind/provider-state.json:/data/neomind/.neomind/provider-state.json  # 单文件 bind mount
```

### 4.5 多 bot 注册机制

未来加新 bot 时，如何注册到 provider-state.json？

**方案：** 每个 bot 启动时自动注册：
```python
# bot 启动时
state_mgr.register_bot("neomind", defaults={
    "provider_mode": "direct",
    "litellm_model": "local",
    "direct_model": "deepseek-chat",
})
```
如果 state 文件里已有该 bot 的配置，保留不覆盖。如果没有，用 defaults 创建。

### 4.6 Docker 内访问 macOS 端的 LiteLLM

LiteLLM 跑在 macOS 上的 `localhost:4000`。Docker 容器内需要用 `host.docker.internal:4000`。

当前 .env 里 `LITELLM_BASE_URL` 是否正确设成了 `host.docker.internal`？需要确认。

---

## 5. 架构审查发现的问题 & 修正

### 5.1 单文件 bind mount 在 Docker Desktop 上不可靠 → 改为目录 bind mount

**问题：** Docker Desktop (macOS) 对单文件 bind mount 的 file watching 支持差，可能导致容器内读不到外部更新。

**修正：** bind mount 整个 `~/.neomind/` 目录，而不是单个文件：
```yaml
volumes:
  - neomind-data:/data/neomind                     # SQLite 等大数据保留 named volume
  - ${HOME}/.neomind:/data/neomind/.neomind        # 配置目录 bind mount
```

### 5.2 fcntl.flock 不够 → 原子写入

**问题：** bash (xbar) 端无法轻松使用 fcntl.flock，且 flock 不能防止读到写了一半的文件。

**修正：** 所有写入用原子模式 — 先写 `.tmp` 文件再 `rename`：
```python
def _atomic_write(self, data: dict):
    tmp = self.state_file.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.rename(self.state_file)  # atomic on same filesystem
```

xbar 端不直接写 JSON，而是调用 Python helper：
```bash
# xbar 菜单点击时
python3 ~/.neomind/provider-ctl.py set neomind litellm
```

### 5.3 每次请求都读文件太频繁 → mtime 缓存

**修正：** 只在文件 mtime 变化时才重新读取：
```python
def _read_state(self) -> dict:
    mtime = self.state_file.stat().st_mtime
    if mtime == self._cached_mtime:
        return self._cached_state
    # file changed, re-read
    self._cached_state = json.loads(self.state_file.read_text())
    self._cached_mtime = mtime
    return self._cached_state
```

### 5.4 .env.example 的 LITELLM_BASE_URL 不对

**修正：** `http://localhost:4000/v1` → `http://host.docker.internal:4000/v1` (Docker 内访问 macOS 的 LiteLLM)

### 5.5 向后兼容：state 文件不存在时

**修正：** bot 启动时如果 `provider-state.json` 不存在，从 `os.environ` 读取当前值，自动创建初始 state 文件。这样老用户无缝迁移。

### 5.6 state 文件损坏恢复

**修正：** JSON 解析失败时，保留损坏文件为 `.json.bak`，用默认值重建：
```python
try:
    state = json.loads(self.state_file.read_text())
except (json.JSONDecodeError, FileNotFoundError):
    state = self._default_state()
    self._atomic_write(state)
```

---

## 6. 实现计划

### Phase 1: ProviderStateManager (核心)

**新建 `agent/finance/provider_state.py`**

| 任务 | 详情 |
|------|------|
| `ProviderStateManager` 类 | 读写 provider-state.json，mtime 缓存，原子写入 |
| `get_provider_chain()` | 根据 state 构建 provider chain（替代现有 `_get_provider_chain`） |
| `set_provider_mode()` | 切换 mode + 写入文件 + 返回新 chain |
| `register_bot()` | bot 启动时自动注册，已有则不覆盖 |
| `migrate_from_env()` | 从 os.environ 读取旧值创建初始 state（向后兼容） |
| Schema version | `"schema_version": 1`，未来变更时做 migration |
| 错误恢复 | JSON 损坏时 fallback 到默认值并重建文件 |

### Phase 2: Bot 集成

**改造 `agent/finance/telegram_bot.py`**

| 任务 | 详情 |
|------|------|
| `__init__` 初始化 | 创建 ProviderStateManager 实例，调用 `register_bot("neomind")` |
| `_get_provider_chain()` | 改为调用 `state_mgr.get_provider_chain("neomind")` |
| `_cmd_provider` | 改为调用 `state_mgr.set_provider_mode()` |
| 远程切换通知 | 每次 LLM 请求前检查 state 变化，如果被外部改了就发群通知 |
| `/model` 新命令 | 显示当前实际使用的 model 名（区别于 `/provider` 显示 chain） |

### Phase 3: xbar 插件

**新建 `xbar/neomind-provider.1m.sh`** + **`xbar/provider-ctl.py`**

| 任务 | 详情 |
|------|------|
| `provider-ctl.py` | Python CLI 工具：读写 state file，原子操作，供 xbar 和手动调用 |
| `neomind-provider.1m.sh` | xbar 菜单栏插件：读 state 显示状态，点击调用 provider-ctl.py 切换 |
| LiteLLM 健康检查 | xbar 刷新时 curl LiteLLM /health，更新 state 中的 health_ok |
| macOS notification | 切换成功/失败时弹通知 |

### Phase 4: Docker & 配置

| 任务 | 详情 |
|------|------|
| `docker-compose.yml` | 添加 `~/.neomind` 目录 bind mount |
| `docker-entrypoint.sh` | 启动时确保 /data/neomind/.neomind 目录存在 |
| `.env.example` | 修正 LITELLM_BASE_URL 为 host.docker.internal |
| 旧 `switch-provider.sh` | 保留但标记 deprecated，指向新方案 |

### Phase 5: 验证

| 任务 | 详情 |
|------|------|
| 单元测试 | ProviderStateManager 的读写、缓存、并发、损坏恢复 |
| 集成测试 | xbar 切换 → bot 感知 → 群通知 |
| 回滚测试 | 删除 state 文件后 bot 能从 .env 恢复 |

---

## 7. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `agent/finance/provider_state.py` | **新建** | ProviderStateManager 核心类 |
| `agent/finance/telegram_bot.py` | **改造** | 集成 ProviderStateManager |
| `xbar/neomind-provider.1m.sh` | **新建** | xbar 菜单栏插件 |
| `xbar/provider-ctl.py` | **新建** | Python CLI 工具（原子读写 state） |
| `xbar/switch-provider.sh` | **标记废弃** | 加 deprecated 注释 |
| `docker-compose.yml` | **改造** | 添加 bind mount |
| `docker-entrypoint.sh` | **改造** | 确保目录存在 |
| `.env.example` | **改造** | 修正 LITELLM_BASE_URL |
| `tests/test_provider_state.py` | **新建** | 单元测试 |

---

## 8. 第二轮审查发现的问题 & 修正

### 8.1 SQLite 不能放在 bind mount 里

**问题：** Docker Desktop 的 bind mount 通过 Linux VM 透传文件系统。SQLite 的文件锁（尤其是 WAL 模式）在这种透传上经常出 "database is locked" 错误。

当前 `chat_history.db` 路径是 `$HOME/.neomind/chat_history.db`，如果把整个 `~/.neomind/` bind mount 进去，SQLite 就跑在了 bind mount 上。

**修正：** 把 SQLite DB 移出 `.neomind/` 目录，放到 named volume 的独立路径下：
```
/data/neomind/.neomind/     ← bind mount (配置 JSON 文件)
/data/neomind/db/           ← named volume (SQLite，高性能)
```

对应改动：
- `chat_store.py`: 默认路径改为 `/data/neomind/db/chat_history.db`
- `docker-entrypoint.sh`: `mkdir -p /data/neomind/db`
- 需要一次性迁移脚本把旧 DB 从 `.neomind/` 移到 `db/`

### 8.2 get_provider_chain() 仍需从 env 读 API key

**问题：** 计划说 ProviderStateManager.get_provider_chain() 替代现有 `_get_provider_chain()`。但现有方法从 `os.environ` 读取 `DEEPSEEK_API_KEY`、`ZAI_API_KEY`、`LITELLM_API_KEY`。state 文件只存 mode，不存 API key（密钥不应写入 JSON 文件）。

**修正：** ProviderStateManager 的 `get_provider_chain()` 接口需要明确：
```python
def get_provider_chain(self, bot_name: str, thinking: bool = False) -> list:
    """从 state file 读 mode，从 os.environ 读 API keys。

    state file 管 "用哪个 provider"
    .env 管 "API key 是什么"
    职责分离：state file 不涉及任何敏感信息。
    """
```

### 8.3 远程切换通知：通知哪个群？

**问题：** xbar 切换后，bot 端要发群通知。但 bot 可能在多个群里。通知所有群？只通知最近活跃的？

**修正：** 通知策略：
- 通知 `TELEGRAM_ALLOWED_GROUPS` 里列出的所有群（如果配了的话）
- 如果没配 allowed_groups，则通知最近 24h 有过消息的群
- 通知文本简短，不打扰：`🔌 Provider 切换为 LiteLLM (由 xbar 触发)`

### 8.4 provider-ctl.py 不能 import bot 代码

**问题：** 计划说 xbar 调用 `provider-ctl.py`，而 bot 用 `ProviderStateManager`。但 `provider-ctl.py` 跑在 macOS 上，没有 bot 的 Python 环境和依赖。不能 `from agent.finance.provider_state import ...`。

**修正：** `provider-ctl.py` 必须是自包含的（zero dependency），不 import 任何项目代码。它直接读写 JSON，用同样的原子写入逻辑。ProviderStateManager（bot 端）和 provider-ctl.py（xbar 端）共享的是**文件格式契约**，不是代码依赖。

文件组织：
```
xbar/provider-ctl.py          ← macOS 端，自包含，零依赖
agent/finance/provider_state.py ← bot 端，可 import 其他模块
两者共享 provider-state.json 格式规范
```

### 8.5 今天刚加的 streaming 方法也调 _get_provider_chain

**问题：** 今天给普通模式加了 `_ask_llm_stream_normal()`，里面也调用 `self._get_provider_chain(thinking=False)`。Phase 2 改造时不能漏掉。

**修正：** 在 Phase 2 文件变更清单中加上：需改造的调用点共 6 处：
1. `_cmd_provider` — 显示/切换
2. `_get_provider_chain` — 核心方法（替换为 state_mgr 调用）
3. `_resolve_api` — 间接调用 _get_provider_chain
4. `_ask_llm` — 非流式（fallback 保留）
5. `_ask_llm_stream_normal` — 流式普通模式 ← **新增**
6. `_ask_llm_streaming` — 流式思考模式

---

## 9. 修正后的实现计划（最终版）

### Phase 1: ProviderStateManager (核心) — 预计 1-2 小时

**新建 `agent/finance/provider_state.py`**

```python
class ProviderStateManager:
    # state file 管 mode，.env 管 API keys，职责分离
    # mtime 缓存，原子写入，损坏恢复
    # get_provider_chain() 从 state 读 mode + 从 env 读 keys
    # register_bot() 自动注册
    # migrate_from_env() 向后兼容
```

### Phase 2: Bot 集成 — 预计 1-2 小时

**改造 `agent/finance/telegram_bot.py`**（6 处调用点）

- `__init__`: 创建 state_mgr，register_bot
- `_get_provider_chain()` → 委托给 state_mgr
- `_cmd_provider` → 读写 state_mgr
- 新增远程切换检测 + 群通知
- 新增 `/model` 命令

### Phase 3: SQLite 路径迁移 — 预计 30 分钟

- `chat_store.py` 默认路径改为 `/data/neomind/db/`
- `docker-entrypoint.sh` 加目录创建 + 一次性迁移逻辑
- `usage_tracker.py` 如果也用 SQLite，一并迁移

### Phase 4: xbar 插件 — 预计 1 小时

- `xbar/provider-ctl.py` — 自包含 CLI，零依赖
- `xbar/neomind-provider.1m.sh` — 菜单栏 + 调用 provider-ctl.py
- 旧 `switch-provider.sh` 标记废弃

### Phase 5: Docker 配置 — 预计 30 分钟

- `docker-compose.yml` 添加目录 bind mount
- `.env.example` 修正 LITELLM_BASE_URL
- 首次运行说明（mkdir -p ~/.neomind）

### Phase 6: 验证 — 预计 1 小时

- `tests/test_provider_state.py` — 单元测试
- 手动集成测试清单

---

## 10. 最终文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `agent/finance/provider_state.py` | **新建** | ProviderStateManager 核心类 |
| `agent/finance/telegram_bot.py` | **改造** | 集成 state_mgr，6 处调用点 |
| `agent/finance/chat_store.py` | **改造** | SQLite 路径迁移出 .neomind/ |
| `xbar/neomind-provider.1m.sh` | **新建** | xbar 菜单栏插件 |
| `xbar/provider-ctl.py` | **新建** | 自包含 CLI（零依赖） |
| `xbar/switch-provider.sh` | **标记废弃** | 加 deprecated 注释 |
| `docker-compose.yml` | **改造** | 添加 bind mount |
| `docker-entrypoint.sh` | **改造** | 目录创建 + DB 迁移 |
| `.env.example` | **改造** | 修正 LITELLM_BASE_URL |
| `tests/test_provider_state.py` | **新建** | 单元测试 |

---

## 11. 第 3-5 轮审查发现的增量问题 & 修正

### 11.1 [Critical] 遗漏了第三个 SQLite 数据库: memory.db

项目中实际有 **3 个 SQLite DB** 需要从 bind mount 区迁移到 named volume：
- `~/.neomind/chat_history.db` (chat_store.py)
- `~/.neomind/usage.db` (usage_tracker.py)
- `~/.neomind/finance/memory.db` (secure_memory.py)

**修正：** Phase 3 扩展为迁移所有 3 个 DB。entrypoint 里用环境变量显式指定路径：
```bash
export NEOMIND_CHAT_DB=/data/neomind/db/chat_history.db
export NEOMIND_USAGE_DB=/data/neomind/db/usage.db
export NEOMIND_MEMORY_DIR=/data/neomind/db/finance
```
这样各模块不再自己推算路径，由 entrypoint 统一指定。

### 11.2 [Critical] 首次运行时 macOS 端 ~/.neomind 不存在

Docker bind mount 源路径不存在时，Docker Desktop 会自动创建为空目录（由 root 拥有），后续写入可能出权限问题。

**修正：** 两重保障：
1. `docker-compose.yml` 添加注释：首次运行前需 `mkdir -p ~/.neomind`
2. 新建 `scripts/setup.sh` 一键初始化脚本：
   ```bash
   mkdir -p ~/.neomind
   cp xbar/provider-ctl.py ~/.neomind/  # 可选
   ```

### 11.3 [Critical] xbar 菜单项的 `| bash=` 语法没有写明

xbar 点击菜单项时必须用特定语法：
```
✅ LiteLLM (local Qwen3) | bash=/path/to/provider-ctl.py param1=set param2=neomind param3=litellm terminal=false refresh=true
```
计划只画了菜单结构没给出实际 xbar 语法。

**修正：** Phase 4 实现时按照 xbar 标准格式，provider-ctl.py 通过 `$NEOMIND_DIR` 环境变量定位（在 xbar 插件头部设定，同现有 switch-provider.sh 一致）。

### 11.4 [High] Docker Desktop VirtioFS 的 mtime 传播有延迟 (100-500ms)

mtime 缓存策略可能在 xbar 写入后的短窗口内读到旧值。

**修正：** 双重检测：mtime 变了就重读，另外在每次构建 provider chain 时对比上次使用的 `provider_mode` 字符串，如果不同就触发切换通知。这样即使 mtime 有延迟，也不会影响正确性 — 最多多读一次文件。

### 11.5 [High] macOS 上 python3 路径不确定

xbar 在精简 shell 环境下运行，Homebrew 的 `/opt/homebrew/bin/python3` 可能不在 PATH 里。

**修正：** provider-ctl.py 的 shebang 用 `#!/usr/bin/env python3`，且 xbar 插件头部显式设 PATH：
```bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:$PATH"
```

### 11.6 [High] DB 迁移失败时没有回滚机制

如果 entrypoint 迁移 SQLite 到新路径时磁盘满或权限不够，数据可能丢失。

**修正：** 迁移策略改为 **复制后验证，不删源文件**：
```bash
# docker-entrypoint.sh
if [ -f "$OLD_DB" ] && [ ! -f "$NEW_DB" ]; then
    cp "$OLD_DB" "$NEW_DB"
    # 验证新 DB 可读
    sqlite3 "$NEW_DB" "SELECT count(*) FROM messages;" >/dev/null 2>&1 && \
        echo "[migrate] ✅ $OLD_DB → $NEW_DB" || \
        { echo "[migrate] ❌ 验证失败，保留旧文件"; rm -f "$NEW_DB"; }
fi
```
旧文件只在手动确认后才删除。

### 11.7 [High] LiteLLM 健康恢复机制缺失

xbar 检测到 LiteLLM 挂了会写 `health_ok=false`，但恢复后谁写回 `true`？

**修正：**
- xbar 每次刷新都做健康检查，恢复了就写 `true`
- bot 端：如果 provider_mode=litellm 且 health_ok=false，先尝试一次 LiteLLM 调用，成功就写回 `true`
- 双端都能恢复，不依赖单一方

### 11.8 [Medium] subscriptions.json 也需要原子写入

当前 `_save_subscriptions()` 直接 `write_text()`，bind mount 上 partial write 可能导致损坏。

**修正：** 跟 provider-state.json 一样，改为原子写入（write .tmp → rename）。

### 11.9 [Medium] state 文件里要禁止出现 API key

未来代码变更可能不小心把 key 写入 state JSON（它在 bind mount 上，macOS 可见）。

**修正：** ProviderStateManager._atomic_write() 里加个 assertion：
```python
assert "api_key" not in json.dumps(data).lower(), "API key must never be written to state file"
```

### 11.10 [Medium] 需要 schema_version 的迁移分发机制

计划说了 `schema_version: 1` 但没说 v2 怎么升级。

**修正：** 添加迁移框架：
```python
_MIGRATIONS = {
    # (from_version, to_version): migration_function
    (0, 1): _migrate_v0_to_v1,  # 从 env 迁移
}

def _ensure_schema(self, state: dict) -> dict:
    current = state.get("schema_version", 0)
    while current < CURRENT_SCHEMA_VERSION:
        migrator = _MIGRATIONS.get((current, current + 1))
        if migrator:
            state = migrator(state)
        current += 1
    state["schema_version"] = CURRENT_SCHEMA_VERSION
    return state
```

### 11.11 [Low] xbar curl 健康检查没有超时

如果 LiteLLM 卡住，curl 会阻塞 xbar 刷新。

**修正：** 所有 curl 加 `--max-time 3`。

---

## 12. 最终修正后的 Phase 汇总

| Phase | 内容 | 对比之前新增/修正 |
|-------|------|------------------|
| 1 | ProviderStateManager | + schema 迁移框架 + API key 断言 + 双重检测 (mtime + mode 比对) |
| 2 | Bot 集成 | + LiteLLM 健康恢复逻辑 + subscriptions.json 原子写入 |
| 3 | SQLite 迁移 | + **3 个 DB** (不是 2 个) + 复制后验证不删源 + entrypoint 环境变量注入 |
| 4 | xbar 插件 | + 完整 `\| bash=` 语法 + PATH 设定 + curl 超时 + 首次 setup 脚本 |
| 5 | Docker 配置 | + mkdir 说明 + setup.sh |
| 6 | 验证 | + VirtioFS 延迟测试 + DB 迁移回滚测试 |

---

## 13. 不在本次范围的东西

- xbar 上直接切换具体模型（如 Qwen3 14B → 32B）— 这个由 LiteLLM config 管，不属于 provider sync
- 多 bot 间的跨 provider 路由策略（如 neomind 用 LiteLLM、另一个 bot 用 Direct）— 架构已支持，但具体 UI 等以后再做
- 权限控制（谁能切换 provider）— 现有的 TELEGRAM_ADMIN_USERS 已足够
