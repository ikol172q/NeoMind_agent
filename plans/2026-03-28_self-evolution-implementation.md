# NeoMind 自我进化 — 工程实施方案

> 日期: 2026-03-28
> 针对: Docker容器内运行的 NeoMind Agent
> 原则: 借鉴但不抄袭 OpenClaw，一切围绕 NeoMind 自身架构

---

## 目标清单

| # | 需求 | 核心挑战 |
|---|------|---------|
| 1 | **自改代码** — Agent 能修改自己的 Python 源码 | Docker 容器内的安全热更新 |
| 2 | **自调 Prompt** — 自动优化 system prompt (YAML) | 多人格 prompt 的指标驱动调优 |
| 3 | **Adhoc 写程序** — 遇到障碍时自写脚本解围 | 沙箱执行 + 自诊断 |
| 4 | **24/7 不死** — 重启时保持行为正常，出问题自我debug并告知 | Docker进程管理 + 状态保存 + 告警 |
| 5 | **借鉴不抄** — 参考 OpenClaw 但走自己的路 | 架构差异化 |
| 6 | **Docker环境** — 一切方案必须适配现有 Docker 架构 | 容器内 git + 热加载 + 卷持久化 |

---

## 一、自改代码 (Self-Modify)

### 1.1 NeoMind 的代码修改模型

**不同于 OpenClaw:** OpenClaw 依赖 `apply_patch` + 社区技能市场。NeoMind 采用 **Git-Gated Self-Edit** 模型 — 每次修改都是一个 git commit，测试通过才保留。

```
┌──────────────────────────────────────────────────────────┐
│                NeoMind Self-Edit Pipeline                  │
│                                                            │
│  发现问题/改进点                                           │
│       ↓                                                    │
│  ┌─────────────┐   ┌──────────────┐   ┌────────────────┐ │
│  │ 生成补丁     │→ │ AST安全检查   │→ │ pytest沙箱测试  │ │
│  │ (LLM生成diff)│   │ (禁止危险调用) │   │ (fork进程执行)  │ │
│  └─────────────┘   └──────────────┘   └────────────────┘ │
│                                              ↓             │
│                                     ┌────────────────┐    │
│                         测试失败 ← │ 测试通过?       │    │
│                         回滚补丁    │                │    │
│                                     └───────┬────────┘    │
│                                             ↓ 通过        │
│                                     ┌────────────────┐    │
│                                     │ git commit      │    │
│                                     │ 热加载模块      │    │
│                                     │ 通知用户        │    │
│                                     └────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### 1.2 实现: `agent/evolution/self_edit.py`

```python
"""NeoMind Self-Edit Engine

Docker环境: 代码在 /app (COPY进容器)，但可通过 git 管理。
关键: Dockerfile 已安装 git，/app 就是 git repo。
"""

import ast
import subprocess
import importlib
import sys
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple, Optional

class SelfEditor:
    """NeoMind 自我修改引擎

    设计原则:
    1. 每次修改是一个 git commit → 完整审计轨迹
    2. AST 分析拦截危险操作 → 安全边界
    3. pytest 在 fork 进程中测试 → 失败不影响主进程
    4. importlib.reload 热加载 → 无需重启容器
    """

    REPO_DIR = Path("/app")  # Docker 中的代码目录
    FORBIDDEN_CALLS = {"exec", "eval", "__import__", "os.system",
                       "subprocess.call", "shutil.rmtree"}
    FORBIDDEN_PATHS = {".env", "docker-entrypoint.sh", "Dockerfile",
                       "agent/evolution/self_edit.py"}  # 不允许改自己

    def __init__(self):
        self.edit_log = Path("/data/neomind/evolution/edit_history.jsonl")
        self.edit_log.parent.mkdir(parents=True, exist_ok=True)
        self.max_edits_per_day = 10
        self._today_edits = 0

    # ── 核心流程 ──

    def propose_edit(self, file_path: str, reason: str,
                     new_content: str) -> Tuple[bool, str]:
        """提出代码修改，走完整安全流程

        Returns: (success, message)
        """
        rel_path = str(Path(file_path).relative_to(self.REPO_DIR))

        # 守卫1: 日限额
        if self._today_edits >= self.max_edits_per_day:
            return False, f"今日已达修改上限 ({self.max_edits_per_day})"

        # 守卫2: 禁止修改的文件
        if rel_path in self.FORBIDDEN_PATHS:
            return False, f"禁止修改: {rel_path}"

        # 守卫3: 只能改 .py 文件
        if not rel_path.endswith(".py"):
            return False, "仅允许修改 .py 文件"

        # 守卫4: AST 安全检查
        safe, ast_msg = self._ast_safety_check(new_content)
        if not safe:
            return False, f"AST安全检查失败: {ast_msg}"

        # 守卫5: 语法检查
        try:
            compile(new_content, rel_path, "exec")
        except SyntaxError as e:
            return False, f"语法错误: {e}"

        # 备份当前文件
        target = self.REPO_DIR / rel_path
        if target.exists():
            original = target.read_text()
        else:
            original = None

        # 写入新内容
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content)

        # 在 fork 进程中跑测试
        test_ok, test_msg = self._run_tests_in_fork(rel_path)

        if not test_ok:
            # 回滚
            if original is not None:
                target.write_text(original)
            else:
                target.unlink(missing_ok=True)
            self._log_edit(rel_path, reason, "ROLLBACK", test_msg)
            return False, f"测试失败，已回滚: {test_msg}"

        # 测试通过 → git commit
        self._git_commit(rel_path, reason)

        # 热加载
        module_name = rel_path.replace("/", ".").replace(".py", "")
        self._hot_reload(module_name)

        self._today_edits += 1
        self._log_edit(rel_path, reason, "APPLIED", "测试通过")

        return True, f"✓ 已修改 {rel_path} 并热加载"

    # ── AST 安全检查 ──

    def _ast_safety_check(self, code: str) -> Tuple[bool, str]:
        """分析 AST，拦截危险调用"""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, str(e)

        for node in ast.walk(tree):
            # 检查危险函数调用
            if isinstance(node, ast.Call):
                func_name = self._get_call_name(node)
                if func_name in self.FORBIDDEN_CALLS:
                    return False, f"禁止调用: {func_name}"

            # 检查危险 import
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ("ctypes", "cffi"):
                        return False, f"禁止导入: {alias.name}"

        return True, "通过"

    def _get_call_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            parts = []
            current = node.func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return ""

    # ── Fork 测试 ──

    def _run_tests_in_fork(self, changed_file: str) -> Tuple[bool, str]:
        """在子进程中运行 pytest，不影响主进程"""
        try:
            # 找到相关测试文件
            test_file = self._find_test_for(changed_file)
            cmd = ["python", "-m", "pytest", "-x", "--tb=short", "-q"]
            if test_file:
                cmd.append(test_file)
            else:
                # 跑最小测试集: 导入检查
                cmd = ["python", "-c",
                       f"import importlib; importlib.import_module('{changed_file.replace('/', '.').replace('.py', '')}')"]

            result = subprocess.run(
                cmd,
                capture_output=True, text=True,
                timeout=60,  # 1分钟超时
                cwd=str(self.REPO_DIR),
                env={**dict(subprocess.os.environ),
                     "PYTHONPATH": str(self.REPO_DIR)},
            )
            if result.returncode == 0:
                return True, result.stdout[-200:]
            else:
                return False, (result.stderr or result.stdout)[-500:]
        except subprocess.TimeoutExpired:
            return False, "测试超时 (60s)"
        except Exception as e:
            return False, str(e)

    def _find_test_for(self, file_path: str) -> Optional[str]:
        """查找对应的测试文件"""
        # agent/evolution/auto_evolve.py → tests/test_evolution.py
        name = Path(file_path).stem
        candidates = [
            f"tests/test_{name}.py",
            f"tests/test_{Path(file_path).parent.name}.py",
        ]
        for c in candidates:
            if (self.REPO_DIR / c).exists():
                return c
        return None

    # ── 热加载 ──

    def _hot_reload(self, module_name: str):
        """importlib.reload 热加载已修改的模块"""
        try:
            if module_name in sys.modules:
                module = sys.modules[module_name]
                importlib.reload(module)
        except Exception as e:
            # 热加载失败不是灾难，下次启动会加载新代码
            pass

    # ── Git 管理 ──

    def _git_commit(self, file_path: str, reason: str):
        """Git commit 修改"""
        try:
            subprocess.run(["git", "add", file_path],
                          cwd=str(self.REPO_DIR), capture_output=True, timeout=5)
            subprocess.run(
                ["git", "commit", "-m", f"[self-edit] {reason[:100]}"],
                cwd=str(self.REPO_DIR), capture_output=True, timeout=10)
        except Exception:
            pass  # Git 失败不阻止功能

    # ── 日志 ──

    def _log_edit(self, file: str, reason: str, status: str, detail: str):
        """追加式编辑日志"""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "file": file,
            "reason": reason,
            "status": status,
            "detail": detail[:200],
        }
        with open(self.edit_log, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

### 1.3 Docker 适配要点

```dockerfile
# Dockerfile 中已有 git — 可以直接用
# 关键: 容器内 /app 就是代码目录

# 在 docker-entrypoint.sh 中初始化 git (如果还没有)
if [ ! -d /app/.git ]; then
    cd /app && git init && git add -A && git commit -m "initial"
fi
```

**卷挂载策略:**
- `/app` — 代码目录 (不挂载, 容器内管理)
- `/data/neomind` — 数据+进化状态 (Docker volume, 已有)
- `/data/neomind/evolution/edit_history.jsonl` — 编辑审计日志

---

## 二、自调 Prompt (Self-Tune)

### 2.1 NeoMind 的 Prompt 调优模型

**不同于 OpenClaw:** OpenClaw 靠手动编辑 SOUL.md。NeoMind 采用 **Metric-Driven YAML Tuning** — 基于用户反馈自动调整 YAML 配置中的可调参数。

**核心思路:** 不重写整个 system prompt，而是调整 YAML 配置中的 **参数化字段**。

### 2.2 YAML 配置参数化

当前 NeoMind 的 prompt 存储在 `agent/config/{chat,coding,fin}.yaml`。改造为:

```yaml
# agent/config/chat.yaml (改造后)
mode: chat
model: deepseek-chat

# ── 可调参数 (AutoTune 可修改这些) ──
tunable:
  temperature: 0.7          # 范围: [0.1, 1.5]
  max_tokens: 8192           # 范围: [2048, 16384]
  response_style: balanced   # 选项: concise | balanced | detailed
  language_preference: auto  # 选项: auto | zh | en
  reasoning_depth: medium    # 选项: shallow | medium | deep
  example_count: 2           # 范围: [0, 5], few-shot 示例数

# ── 系统 Prompt 模板 (含变量插值) ──
system_prompt_template: |
  你是新思，一个基于第一性原理思考的AI助手。

  {%- if response_style == "concise" %}
  保持回答简洁，每个回答不超过3段。
  {%- elif response_style == "detailed" %}
  提供详细的分析，包含推理过程。
  {%- endif %}

  {%- if language_preference == "zh" %}
  始终使用中文回答。
  {%- elif language_preference == "en" %}
  Always respond in English.
  {%- endif %}

  {%- if reasoning_depth == "deep" %}
  对每个问题，先分解为子问题，再逐步推理。
  {%- endif %}

# ── 不可调参数 (核心身份，永不自动修改) ──
immutable:
  core_identity: "新思 (NeoMind) — 基于第一性原理的AI助手"
  safety_rules: true
  first_principles: true
```

### 2.3 实现: `agent/evolution/prompt_tuner.py`

```python
"""NeoMind Prompt Auto-Tuner

不依赖 DSPy/TextGrad 等外部框架 (保持 zero-dependency)。
使用简单但有效的策略: 收集信号 → 生成变体 → A/B 评估 → 采纳最优。
"""

import yaml
import json
import copy
import random
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

class PromptTuner:
    """三阶段 Prompt 自动调优

    Stage 1: 信号收集 (每次对话后)
    Stage 2: 变体生成 (每日)
    Stage 3: 效果评估 + 采纳/回滚 (每周)
    """

    CONFIG_DIR = Path("/app/agent/config")
    TUNE_STATE = Path("/data/neomind/evolution/prompt_tune_state.json")

    # 可调参数的搜索空间
    SEARCH_SPACE = {
        "temperature": {"type": "float", "min": 0.1, "max": 1.5, "step": 0.1},
        "max_tokens": {"type": "int", "min": 2048, "max": 16384, "step": 1024},
        "response_style": {"type": "choice", "options": ["concise", "balanced", "detailed"]},
        "language_preference": {"type": "choice", "options": ["auto", "zh", "en"]},
        "reasoning_depth": {"type": "choice", "options": ["shallow", "medium", "deep"]},
        "example_count": {"type": "int", "min": 0, "max": 5, "step": 1},
    }

    def __init__(self):
        self.TUNE_STATE.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    # ── Stage 1: 信号收集 ──

    def record_signal(self, mode: str, signal_type: str, value: float,
                      context: Optional[Dict] = None):
        """记录质量信号

        signal_type:
        - "user_satisfaction": 用户满意度 (0-1), 从反馈推断
        - "task_completion": 任务完成 (0/1)
        - "retry_rate": 用户重试率 (0-1), 越低越好
        - "response_length_ok": 长度是否合适 (0/1)
        """
        key = f"{mode}:{signal_type}"
        if key not in self.state["signals"]:
            self.state["signals"][key] = []

        self.state["signals"][key].append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "value": value,
            "context": context or {},
        })

        # 限制存储: 每类信号最多保留200条
        if len(self.state["signals"][key]) > 200:
            self.state["signals"][key] = self.state["signals"][key][-200:]

        self._save_state()

    # ── Stage 2: 变体生成 (每日) ──

    def generate_variant(self, mode: str) -> Optional[Dict[str, Any]]:
        """基于信号生成一个 prompt 参数变体

        策略: 分析哪些信号低分 → 调整对应参数
        - 用户说"太长" → response_style: concise
        - 重试率高 → 提高 reasoning_depth
        - 任务完成率低 → 提高 temperature (更多创造性)
        """
        config = self._load_config(mode)
        if not config or "tunable" not in config:
            return None

        current = config["tunable"]
        variant = copy.deepcopy(current)

        # 分析信号
        signals = self._aggregate_signals(mode)

        # 规则: 信号 → 参数调整
        if signals.get("retry_rate", 0) > 0.3:
            # 重试率高 → 加深推理
            variant["reasoning_depth"] = "deep"

        if signals.get("response_length_ok", 1) < 0.5:
            # 长度不满意 → 切换风格
            if current.get("response_style") == "detailed":
                variant["response_style"] = "balanced"
            elif current.get("response_style") == "balanced":
                variant["response_style"] = "concise"

        if signals.get("task_completion", 1) < 0.6:
            # 任务完成率低 → 微调 temperature
            t = current.get("temperature", 0.7)
            variant["temperature"] = min(1.2, t + 0.1)

        if signals.get("user_satisfaction", 1) > 0.8:
            # 已经很好 → 不动
            return None

        # 也允许随机探索 (10%概率)
        if random.random() < 0.1:
            param = random.choice(list(self.SEARCH_SPACE.keys()))
            space = self.SEARCH_SPACE[param]
            if space["type"] == "float":
                variant[param] = round(random.uniform(space["min"], space["max"]), 1)
            elif space["type"] == "int":
                variant[param] = random.randrange(space["min"], space["max"] + 1, space["step"])
            elif space["type"] == "choice":
                variant[param] = random.choice(space["options"])

        # 保存变体
        self.state["pending_variants"][mode] = {
            "variant": variant,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "signals_at_creation": signals,
        }
        self._save_state()

        return variant

    # ── Stage 3: 评估与采纳 ──

    def evaluate_and_adopt(self, mode: str) -> Tuple[bool, str]:
        """比较变体 vs 当前配置的表现，决定是否采纳

        只在有足够新数据 (≥20条信号) 时才评估
        """
        pending = self.state["pending_variants"].get(mode)
        if not pending:
            return False, "无待评估变体"

        # 检查是否有足够的变体期间数据
        variant_created = pending["created_at"]
        new_signals = self._count_signals_after(mode, variant_created)

        if new_signals < 20:
            return False, f"数据不足 ({new_signals}/20), 继续收集"

        # 比较: 变体期间 vs 变体之前
        before = pending["signals_at_creation"]
        after = self._aggregate_signals(mode, after=variant_created)

        # 综合评分
        before_score = self._composite_score(before)
        after_score = self._composite_score(after)

        if after_score > before_score + 0.05:  # 至少5%改进才采纳
            # 采纳: 写入 YAML
            config = self._load_config(mode)
            config["tunable"] = pending["variant"]
            self._save_config(mode, config)

            # 清理
            del self.state["pending_variants"][mode]
            self.state["adoption_history"].append({
                "mode": mode,
                "ts": datetime.now(timezone.utc).isoformat(),
                "before_score": before_score,
                "after_score": after_score,
                "adopted": pending["variant"],
            })
            self._save_state()

            return True, f"✓ 采纳变体 (评分 {before_score:.2f} → {after_score:.2f})"
        else:
            # 回滚: 恢复原配置
            del self.state["pending_variants"][mode]
            self._save_state()
            return False, f"变体未改善 ({before_score:.2f} → {after_score:.2f}), 已放弃"

    # ── LLM辅助 Prompt 重写 (高级，可选) ──

    def llm_rewrite_prompt(self, mode: str, feedback_summary: str) -> Optional[str]:
        """用 LLM 重写 system prompt 的非核心部分

        安全约束:
        - 只改 system_prompt_template 中的非 immutable 部分
        - 改完后必须通过 SelfEditor 的安全流程
        - 每周最多 1 次
        """
        # 这里调用 NeoMind 自己的 LLM provider
        # 用最便宜的模型 (deepseek-chat)
        # 输入: 当前 prompt + 用户反馈摘要
        # 输出: 改进后的 prompt
        pass  # Phase 5D 实现

    # ── 辅助方法 ──

    def _aggregate_signals(self, mode: str, after: str = None) -> Dict[str, float]:
        """聚合信号为单一指标"""
        result = {}
        for key, records in self.state["signals"].items():
            if not key.startswith(f"{mode}:"):
                continue
            signal_type = key.split(":")[1]
            filtered = records
            if after:
                filtered = [r for r in records if r["ts"] > after]
            if filtered:
                result[signal_type] = sum(r["value"] for r in filtered) / len(filtered)
        return result

    def _composite_score(self, signals: Dict[str, float]) -> float:
        """加权综合评分"""
        weights = {
            "user_satisfaction": 0.4,
            "task_completion": 0.3,
            "retry_rate": -0.2,  # 负权重: 越低越好
            "response_length_ok": 0.1,
        }
        score = 0.0
        for key, weight in weights.items():
            if key in signals:
                score += signals[key] * weight
        return score

    def _load_config(self, mode: str) -> Dict:
        path = self.CONFIG_DIR / f"{mode}.yaml"
        with open(path) as f:
            return yaml.safe_load(f)

    def _save_config(self, mode: str, config: Dict):
        path = self.CONFIG_DIR / f"{mode}.yaml"
        with open(path, "w") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    def _load_state(self) -> Dict:
        if self.TUNE_STATE.exists():
            return json.loads(self.TUNE_STATE.read_text())
        return {"signals": {}, "pending_variants": {}, "adoption_history": []}

    def _save_state(self):
        self.TUNE_STATE.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))

    def _count_signals_after(self, mode: str, after: str) -> int:
        count = 0
        for key, records in self.state["signals"].items():
            if key.startswith(f"{mode}:"):
                count += sum(1 for r in records if r["ts"] > after)
        return count
```

---

## 三、Adhoc 写程序自救 (Self-Unblock)

### 3.1 NeoMind 的自救模型

**场景:** 网络超时、磁盘满、依赖缺失、API报错 — Agent 遇到阻碍时，自己写一个临时脚本来诊断和修复。

### 3.2 实现: `agent/evolution/self_unblock.py`

```python
"""NeoMind Self-Unblock Engine

当 Agent 遇到无法完成的操作时，自动:
1. 诊断问题 (写诊断脚本)
2. 尝试修复 (写修复脚本)
3. 如果修复失败 → 告知用户
"""

import subprocess
import tempfile
import os
from pathlib import Path
from typing import Tuple, Optional

class SelfUnblocker:
    """遇到障碍时自己写脚本解决"""

    SANDBOX_DIR = Path("/tmp/neomind_sandbox")
    MAX_SCRIPT_LINES = 50       # 脚本不能太长
    TIMEOUT = 30                # 脚本执行最多30秒

    # 已知问题的修复方案 (不需要LLM)
    KNOWN_FIXES = {
        "disk_full": "import shutil; usage = shutil.disk_usage('/data'); "
                     "print(f'Used: {usage.used/1e9:.1f}GB / {usage.total/1e9:.1f}GB')",

        "network_check": "import urllib.request; "
                         "r = urllib.request.urlopen('https://httpbin.org/ip', timeout=5); "
                         "print(f'Network OK: {r.read().decode()}')",

        "db_integrity": "import sqlite3; "
                        "c = sqlite3.connect('/data/neomind/db/chat_history.db'); "
                        "c.execute('PRAGMA integrity_check'); "
                        "print(c.fetchone())",

        "memory_check": "import psutil; "
                        "m = psutil.virtual_memory(); "
                        "print(f'Memory: {m.percent}% used, {m.available/1e9:.1f}GB free')",

        "import_check": "import importlib, sys; "
                        "failures = []; "
                        "[failures.append(m) for m in ['openai','yaml','rich','aiohttp'] "
                        " if not importlib.util.find_spec(m)]; "
                        "print(f'Missing: {failures}' if failures else 'All imports OK')",
    }

    def __init__(self):
        self.SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

    def diagnose(self, error_type: str, error_msg: str) -> Tuple[str, str]:
        """诊断问题，返回 (诊断结果, 建议修复)"""

        # 先试已知修复
        for key, script in self.KNOWN_FIXES.items():
            if key in error_type.lower() or key in error_msg.lower():
                ok, output = self._safe_exec(script)
                return output, f"已知问题类型: {key}"

        # 未知问题 → 自动诊断
        diag_script = self._generate_diagnostic(error_type, error_msg)
        ok, output = self._safe_exec(diag_script)
        return output, "自动诊断完成" if ok else f"诊断脚本失败: {output}"

    def attempt_fix(self, error_type: str, error_msg: str) -> Tuple[bool, str]:
        """尝试自动修复

        安全约束: 只执行以下类型的修复
        - 清理临时文件
        - 重建数据库索引
        - pip install 缺失依赖
        - 重置网络连接
        """

        # 磁盘满 → 清理临时文件
        if "disk" in error_msg.lower() or "no space" in error_msg.lower():
            script = """
import os, shutil
cleaned = 0
for d in ['/tmp', '/data/neomind/evolution']:
    for f in os.listdir(d):
        p = os.path.join(d, f)
        if f.startswith('tmp') or f.endswith('.tmp'):
            try:
                os.remove(p) if os.path.isfile(p) else shutil.rmtree(p)
                cleaned += 1
            except: pass
print(f'Cleaned {cleaned} temp files')
"""
            ok, output = self._safe_exec(script)
            return ok, output

        # 导入失败 → pip install
        if "ModuleNotFoundError" in error_msg or "ImportError" in error_msg:
            module = self._extract_module_name(error_msg)
            if module and module in self._safe_modules():
                ok, output = self._safe_exec(
                    f"import subprocess; "
                    f"r = subprocess.run(['pip', 'install', '{module}'], "
                    f"capture_output=True, text=True, timeout=60); "
                    f"print(r.stdout[-200:] if r.returncode==0 else r.stderr[-200:])"
                )
                return ok, output

        # SQLite损坏 → 重建
        if "database" in error_msg.lower() and "corrupt" in error_msg.lower():
            ok, output = self._safe_exec(
                "import sqlite3; "
                "c = sqlite3.connect('/data/neomind/db/chat_history.db'); "
                "c.execute('REINDEX'); "
                "print('Database reindexed')"
            )
            return ok, output

        return False, "无法自动修复此类问题"

    def write_adhoc_script(self, task_description: str, llm_func) -> Tuple[bool, str]:
        """用 LLM 生成并执行 adhoc 脚本

        安全约束:
        - 脚本最多50行
        - 不允许网络请求 (除特定诊断)
        - 不允许修改 /app 代码
        - 30秒超时
        """
        prompt = f"""写一个Python诊断脚本来解决: {task_description}

要求:
- 最多50行
- 只用标准库
- 不修改任何文件
- 不发送网络请求
- 打印诊断结果到stdout
"""
        script = llm_func(prompt)

        # 安全检查
        if len(script.split('\n')) > self.MAX_SCRIPT_LINES:
            return False, "脚本超过50行限制"
        if any(danger in script for danger in ["os.remove", "shutil.rmtree", "open(", "requests."]):
            return False, "脚本包含危险操作"

        ok, output = self._safe_exec(script)
        return ok, output

    def _safe_exec(self, script: str) -> Tuple[bool, str]:
        """在沙箱中安全执行脚本"""
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.py', dir=str(self.SANDBOX_DIR),
                delete=False
            ) as f:
                f.write(script)
                f.flush()
                script_path = f.name

            result = subprocess.run(
                ["python", script_path],
                capture_output=True, text=True,
                timeout=self.TIMEOUT,
                cwd=str(self.SANDBOX_DIR),
            )

            os.unlink(script_path)

            if result.returncode == 0:
                return True, result.stdout[-500:]
            else:
                return False, (result.stderr or result.stdout)[-500:]

        except subprocess.TimeoutExpired:
            return False, f"脚本超时 ({self.TIMEOUT}s)"
        except Exception as e:
            return False, str(e)

    def _extract_module_name(self, error_msg: str) -> Optional[str]:
        """从错误信息中提取模块名"""
        import re
        m = re.search(r"No module named '(\w+)'", error_msg)
        return m.group(1) if m else None

    def _safe_modules(self):
        """允许自动 pip install 的模块白名单"""
        return {"requests", "beautifulsoup4", "lxml", "html2text",
                "tiktoken", "psutil", "pyyaml"}
```

---

## 四、24/7 不死 (Immortal Agent)

### 4.1 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Container                         │
│                                                               │
│  ┌─────────┐                                                 │
│  │  tini    │ ← PID 1 (正确处理信号和僵尸进程)               │
│  └────┬────┘                                                 │
│       ↓                                                       │
│  ┌─────────────┐                                             │
│  │ supervisord  │ ← 进程管理器 (重启崩溃的进程)               │
│  └────┬────┘                                                 │
│       ├→ neomind-agent   (主进程, autorestart=true)          │
│       ├→ health-monitor  (健康监控, 独立进程)                 │
│       └→ watchdog        (看门狗, 检测挂死)                   │
│                                                               │
│  ┌─────────────────────────────────────────────┐             │
│  │ /data/neomind/ (Docker Volume, 持久化)      │             │
│  │ ├── db/          (SQLite WAL模式)           │             │
│  │ ├── evolution/   (进化状态)                  │             │
│  │ ├── heartbeat    (心跳文件)                  │             │
│  │ ├── crash_log/   (崩溃日志)                  │             │
│  │ └── state.json   (检查点)                    │             │
│  └─────────────────────────────────────────────┘             │
│                                                               │
│  Docker HEALTHCHECK → curl localhost:18790/health             │
│  restart: unless-stopped                                      │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Dockerfile 改造

```dockerfile
# ── 添加 tini 和 supervisord ──
FROM python:3.11-slim

# ... 现有依赖 ...

# 添加 tini (正确的 PID 1) 和 supervisord
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini supervisor \
    && rm -rf /var/lib/apt/lists/*

# ... 现有 pip install ...

# supervisord 配置
COPY supervisord.conf /etc/supervisor/conf.d/neomind.conf

# tini 作为 PID 1
ENTRYPOINT ["tini", "--"]
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/neomind.conf"]
```

### 4.3 supervisord 配置

```ini
; /etc/supervisor/conf.d/neomind.conf

[supervisord]
nodaemon=true
logfile=/data/neomind/supervisord.log
pidfile=/tmp/supervisord.pid

[program:neomind-agent]
command=python -u /app/main.py %(ENV_NEOMIND_ARGS)s
directory=/app
autorestart=true
startretries=5
startsecs=3
stopwaitsecs=10
redirect_stderr=true
stdout_logfile=/data/neomind/agent.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=3
environment=PYTHONUNBUFFERED=1,PYTHONPATH=/app

[program:health-monitor]
command=python -u /app/agent/evolution/health_monitor.py
directory=/app
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/data/neomind/health.log
stdout_logfile_maxbytes=5MB

[program:watchdog]
command=python -u /app/agent/evolution/watchdog.py
directory=/app
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/data/neomind/watchdog.log
stdout_logfile_maxbytes=5MB
```

### 4.4 实现: `agent/evolution/health_monitor.py`

```python
"""NeoMind Health Monitor — 独立进程

功能:
1. 心跳检测: 主进程每30s写心跳文件，监控进程检测超时
2. 崩溃分析: 主进程崩溃后分析日志，尝试自诊断
3. Boot Loop 检测: 5分钟内重启3次 → 进入安全模式
4. Telegram 告警: 出问题时通知用户
5. HTTP 健康端点: Docker HEALTHCHECK 用
"""

import os
import sys
import time
import json
import signal
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

logger = logging.getLogger("health-monitor")

HEARTBEAT_FILE = Path("/data/neomind/heartbeat")
CRASH_LOG_DIR = Path("/data/neomind/crash_log")
STATE_FILE = Path("/data/neomind/health_state.json")
HEARTBEAT_TIMEOUT = 90  # 秒: 超过90s没心跳 → 判定挂死
BOOT_LOOP_WINDOW = 300  # 秒: 5分钟窗口
BOOT_LOOP_THRESHOLD = 3  # 3次重启 → boot loop

class HealthState:
    def __init__(self):
        self.restart_times = []
        self.safe_mode = False
        self.last_crash_reason = None
        self.load()

    def load(self):
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                self.restart_times = data.get("restart_times", [])
                self.safe_mode = data.get("safe_mode", False)
                self.last_crash_reason = data.get("last_crash_reason")
            except: pass

    def save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "restart_times": self.restart_times[-10:],
            "safe_mode": self.safe_mode,
            "last_crash_reason": self.last_crash_reason,
        }))

    def record_restart(self):
        now = datetime.now(timezone.utc).isoformat()
        self.restart_times.append(now)
        self.save()

    def is_boot_loop(self) -> bool:
        """5分钟内重启3次 = boot loop"""
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=BOOT_LOOP_WINDOW)).isoformat()
        recent = [t for t in self.restart_times if t > cutoff]
        return len(recent) >= BOOT_LOOP_THRESHOLD


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP 健康检查端点"""
    state = None

    def do_GET(self):
        if self.path == "/health":
            # 检查心跳
            if HEARTBEAT_FILE.exists():
                mtime = HEARTBEAT_FILE.stat().st_mtime
                age = time.time() - mtime
                if age < HEARTBEAT_TIMEOUT:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "healthy",
                        "heartbeat_age_s": int(age),
                        "safe_mode": self.state.safe_mode if self.state else False,
                    }).encode())
                    return

            # 心跳超时
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"status":"unhealthy","reason":"heartbeat_timeout"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # 静默HTTP日志


def send_telegram_alert(message: str):
    """通过 Telegram 通知用户"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
    if not token or not chat_id:
        logger.warning("Telegram 告警未配置")
        return

    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": f"🤖 NeoMind Alert\n\n{message}"})
        req = urllib.request.Request(url, data.encode(), {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.error(f"Telegram 告警发送失败: {e}")


def analyze_crash(log_path: str = "/data/neomind/agent.log") -> str:
    """分析最近的崩溃日志"""
    try:
        with open(log_path) as f:
            lines = f.readlines()[-50:]  # 最后50行
        # 找错误
        errors = [l for l in lines if "ERROR" in l or "Traceback" in l or "Exception" in l]
        if errors:
            return "\n".join(errors[-5:])
        return "无明显错误 (可能是 OOM 或信号杀死)"
    except:
        return "无法读取日志"


def watchdog_loop(state: HealthState):
    """主监控循环"""
    state.record_restart()

    # Boot loop 检测
    if state.is_boot_loop():
        msg = "⚠️ Boot Loop 检测!\n5分钟内重启了3次。\n进入安全模式。"
        logger.critical(msg)
        state.safe_mode = True
        state.save()

        # 设置环境变量让主进程知道
        os.environ["NEOMIND_SAFE_MODE"] = "1"

        # 告警
        crash_info = analyze_crash()
        send_telegram_alert(f"{msg}\n\n最近错误:\n{crash_info}")

    while True:
        time.sleep(30)

        # 检查心跳
        if HEARTBEAT_FILE.exists():
            age = time.time() - HEARTBEAT_FILE.stat().st_mtime
            if age > HEARTBEAT_TIMEOUT:
                msg = f"⚠️ 主进程无响应!\n心跳超时 {int(age)}秒。"
                logger.warning(msg)
                crash_info = analyze_crash()
                send_telegram_alert(f"{msg}\n\n最近日志:\n{crash_info}")

                # 尝试诊断
                try:
                    from agent.evolution.self_unblock import SelfUnblocker
                    unblocker = SelfUnblocker()
                    ok, diag = unblocker.diagnose("hang", "Agent主进程无响应")
                    if ok:
                        send_telegram_alert(f"自动诊断结果:\n{diag}")
                except:
                    pass


def main():
    CRASH_LOG_DIR.mkdir(parents=True, exist_ok=True)
    state = HealthState()

    # 启动 HTTP 健康端点 (后台线程)
    HealthHandler.state = state
    server = HTTPServer(("0.0.0.0", 18791), HealthHandler)
    http_thread = threading.Thread(target=server.serve_forever, daemon=True)
    http_thread.start()
    logger.info("Health endpoint: http://0.0.0.0:18791/health")

    # 启动监控循环
    watchdog_loop(state)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [health] %(message)s")
    main()
```

### 4.5 主进程心跳 (加入 core.py)

```python
# 在 agent/core.py 的主循环中加入:

import threading
from pathlib import Path

def _heartbeat_loop():
    """每30秒写心跳文件"""
    heartbeat = Path("/data/neomind/heartbeat")
    while True:
        try:
            heartbeat.write_text(str(time.time()))
        except: pass
        time.sleep(30)

# 在 NeoMindAgent.__init__ 中启动:
heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
heartbeat_thread.start()
```

### 4.6 状态检查点 (重启恢复)

```python
# agent/evolution/checkpoint.py

"""状态检查点 — 重启后恢复到之前的状态"""

import json
from pathlib import Path
from typing import Dict, Any, Optional

CHECKPOINT_FILE = Path("/data/neomind/state_checkpoint.json")

def save_checkpoint(state: Dict[str, Any]):
    """保存当前状态 (每次用户交互后调用)"""
    tmp = CHECKPOINT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False))
    tmp.replace(CHECKPOINT_FILE)  # 原子替换

def load_checkpoint() -> Optional[Dict[str, Any]]:
    """重启后恢复状态"""
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text())
        except:
            return None
    return None

# 检查点内容:
# {
#     "mode": "fin",
#     "last_conversation_id": "...",
#     "turn_count": 42,
#     "active_sprint": null,
#     "evolution_state": { ... },
#     "safe_mode": false,
# }
```

### 4.7 Docker Compose 改造

```yaml
# docker-compose.yml 中的 neomind-telegram 服务添加:

  neomind-telegram:
    # ... 现有配置 ...
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:18791/health', timeout=5)"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s
    deploy:
      resources:
        limits:
          memory: 2G  # 防止 OOM
```

---

## 五、整体集成

### 5.1 新文件清单

```
agent/evolution/
├── auto_evolve.py       # [修改] 接入新引擎
├── self_edit.py          # [新增] 自我修改代码
├── prompt_tuner.py       # [新增] Prompt 自动调优
├── self_unblock.py       # [新增] Adhoc 自救
├── health_monitor.py     # [新增] 24/7 健康监控
├── watchdog.py           # [新增] 看门狗
├── checkpoint.py         # [新增] 状态检查点
├── scheduler.py          # [修改] 调度新任务
├── dashboard.py          # [修改] 展示新指标
└── upgrade.py            # [保留]
```

### 5.2 /evolve 命令扩展

```
/evolve status         # 总览
/evolve health         # 健康检查
/evolve learnings      # 查看 LEARNINGS.md
/evolve errors         # 查看 ERRORS.md
/evolve edit-history   # 查看代码自修改历史
/evolve prompt-status  # Prompt 调优状态
/evolve skills         # 技能库 (Phase 5C)
/evolve diagnose       # 手动触发自诊断
/evolve safe-mode      # 查看/切换安全模式
```

### 5.3 安全模式

当检测到 Boot Loop 时，NeoMind 进入安全模式:
- 禁用所有自动进化
- 禁用代码自修改
- 禁用 Prompt 自动调优
- 仅保留基本对话能力
- 通过 Telegram 告知用户并等待指示

---

## 六、与 OpenClaw 的本质区别

| 维度 | OpenClaw 做法 | NeoMind 做法 | 为什么不同 |
|------|-------------|-------------|-----------|
| **代码修改** | apply_patch (文本补丁) | Git-Gated Self-Edit (AST检查+fork测试+git commit) | 更安全，有完整审计轨迹 |
| **Prompt调优** | 手动编辑 SOUL.md | Metric-Driven YAML Tuning (信号收集→变体→A/B评估) | 自动化、数据驱动 |
| **自救** | 无 (依赖用户修复) | Self-Unblock (已知修复+adhoc脚本) | Docker环境需要自主性 |
| **24/7** | 依赖外部监控 | tini+supervisord+心跳+boot loop检测+Telegram告警 | Docker内必须自己管自己 |
| **记忆** | MEMORY.md 文件 | SQLite WAL + YAML 参数 | 已有基础设施更适合 |
| **进化触发** | Hook机制 | 三阶段调度 (即时/每日/每周) | 适配多人格架构 |

---

## 七、实施优先级

```
Week 1-2: 24/7 不死 (最关键 — 没有这个其他都没意义)
├── tini + supervisord 集成
├── 心跳 + 看门狗
├── Boot loop 检测 + 安全模式
├── Telegram 告警
└── 状态检查点

Week 3-4: Adhoc 自救 + 自改代码
├── SelfUnblocker (已知修复 + 诊断脚本)
├── SelfEditor (Git-Gated pipeline)
├── AST 安全检查
└── Fork 测试 + 热加载

Week 5-6: Prompt 自调优
├── YAML 参数化改造
├── 信号收集
├── 变体生成 + A/B 评估
└── 采纳/回滚机制

Week 7+: 持续迭代
├── LLM辅助 Prompt 重写
├── 更多已知修复方案
├── 进化效果度量
└── 技能锻造 (Phase 5C)
```
