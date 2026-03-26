#!/usr/bin/env python3
# <xbar.title>NeoMind Unified</xbar.title>
# <xbar.version>v2.0</xbar.version>
# <xbar.author>irene</xbar.author>
# <xbar.desc>Unified LLM infrastructure monitor: Ollama + LiteLLM + NeoMind Bot + TokenSight</xbar.desc>
# <xbar.dependencies>python3</xbar.dependencies>
#
# Merges: llm-gateway.1m.sh + neomind-provider.1m.sh + tokensight.1m.py
#
# Filename: neomind-unified.1m.py  (1m = refresh every 1 minute)
# Install:
#   ln -sf ~/Desktop/NeoMind_agent/xbar/neomind-unified.1m.py \
#          "$HOME/Library/Application Support/xbar/plugins/"
#   chmod +x ~/Desktop/NeoMind_agent/xbar/neomind-unified.1m.py

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ════════════════════════════════════════════════════════════════
# Config
# ════════════════════════════════════════════════════════════════

HOME = Path.home()
NEOMIND_DIR = HOME / "Desktop" / "NeoMind_agent"
GATEWAY_DIR = HOME / ".llm-gateway"
STATE_DIR = Path(os.getenv("NEOMIND_STATE_DIR", str(HOME / ".neomind")))
TOKENSIGHT_DIR = HOME / ".tokensight-venv"

SCRIPT_DIR = Path(__file__).resolve().parent
CTL = SCRIPT_DIR / "provider-ctl.py"
PYTHON = "/usr/bin/python3"

# Find a usable python3
for p in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]:
    if os.path.exists(p):
        PYTHON = p
        break

# Ports
LITELLM_PORT = 4000
OLLAMA_PORT = 11434
TOKENSIGHT_PORT = 8900

# Files
STATE_FILE = STATE_DIR / "provider-state.json"
NEOMIND_ENV = NEOMIND_DIR / ".env"
GATEWAY_ENV = GATEWAY_DIR / ".env"
LITELLM_CONFIG = GATEWAY_DIR / "litellm_config.yaml"
LITELLM_LOG = HOME / "Library" / "Logs" / "llm-gateway" / "litellm.log"
LITELLM_ERR_LOG = HOME / "Library" / "Logs" / "llm-gateway" / "litellm-error.log"
PLIST_FILE = HOME / "Library" / "LaunchAgents" / "com.llmgateway.litellm.plist"
USAGE_LOG = TOKENSIGHT_DIR / "usage.jsonl"
USAGE_DAILY = GATEWAY_DIR / "usage-daily.json"
MODELS_DIR = GATEWAY_DIR / "models"
GATEWAY_CLI = GATEWAY_DIR / "gateway"
ACTIONS_DIR = HOME / ".llm-gateway" / "xbar" / "actions"

BOT_NAME = "neomind"

# Pacific Time for TokenSight
PT = timezone(timedelta(hours=-8))

# ════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════

def load_env(path):
    """Load key=value pairs from a .env file into a dict."""
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'").strip('"')
    return env


def http_check(port, path="/", timeout=3):
    """Quick HTTP check via curl. Returns (ok, status_code)."""
    try:
        r = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "--max-time", str(timeout), f"http://localhost:{port}{path}"],
            capture_output=True, text=True, timeout=timeout + 2,
        )
        code = r.stdout.strip()
        return code == "200", code
    except Exception:
        return False, "000"


def http_get_json(url, headers=None, timeout=5):
    """GET JSON from a URL via curl."""
    cmd = ["curl", "-s", "--max-time", str(timeout)]
    if headers:
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        return json.loads(r.stdout) if r.stdout.strip() else None
    except Exception:
        return None


def docker_status(container):
    """Check Docker container status. Returns status string or empty."""
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", f"name={container}", "--format", "{{.Status}}"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def docker_logs(container, tail=100, grep_pattern=None):
    """Get Docker container logs, optionally filtered."""
    try:
        r = subprocess.run(
            ["docker", "logs", container, "--tail", str(tail)],
            capture_output=True, text=True, timeout=5,
        )
        lines = (r.stdout + r.stderr).splitlines()
        if grep_pattern:
            lines = [l for l in lines if re.search(grep_pattern, l)]
        return lines
    except Exception:
        return []


def resolve_litellm_alias(alias):
    """Resolve a LiteLLM model alias to its actual model name from config."""
    if not LITELLM_CONFIG.exists():
        return alias
    try:
        raw = LITELLM_CONFIG.read_text()
        for block in re.split(r'(?=- model_name:)', raw):
            mn = re.search(r'model_name:\s*(\S+)', block)
            if mn and mn.group(1) == alias and 'litellm_params:' in block:
                mp = re.search(r'model:\s*(\S+)', block.split('litellm_params:')[-1])
                if mp:
                    return mp.group(1)
    except Exception:
        pass
    return alias


def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def now_pt():
    return datetime.now(PT).replace(tzinfo=None)


def utc_to_pt(ts_str):
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    return dt.astimezone(PT).replace(tzinfo=None)


# ════════════════════════════════════════════════════════════════
# Data Collection (run all checks)
# ════════════════════════════════════════════════════════════════

# ── Load env files ──
gw_env = load_env(GATEWAY_ENV)
nm_env = load_env(NEOMIND_ENV)
LITELLM_KEY = gw_env.get("LITELLM_MASTER_KEY", "")

# ── Ollama ──
ollama_ok, _ = http_check(OLLAMA_PORT, "/api/tags")
ollama_models = []
ollama_loaded = []
if ollama_ok:
    data = http_get_json(f"http://localhost:{OLLAMA_PORT}/api/tags")
    if data:
        for m in data.get("models", []):
            size_gb = m.get("size", 0) / 1e9
            ollama_models.append((m["name"], size_gb))
    ps = http_get_json(f"http://localhost:{OLLAMA_PORT}/api/ps")
    if ps:
        for m in ps.get("models", []):
            vram = m.get("size_vram", 0) / 1e9
            ollama_loaded.append((m["name"], vram))

# ── LiteLLM ──
auth_headers = {"Authorization": f"Bearer {LITELLM_KEY}"} if LITELLM_KEY else {}
litellm_ok, _ = http_check(LITELLM_PORT, "/health/liveliness")
litellm_models = []
if litellm_ok:
    data = http_get_json(f"http://localhost:{LITELLM_PORT}/v1/models", headers=auth_headers)
    if data:
        litellm_models = [m["id"] for m in data.get("data", [])]

# Update LiteLLM health in shared state
if CTL.exists():
    try:
        subprocess.Popen(
            [PYTHON, str(CTL), "health-update", str(litellm_ok).lower()],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass

# launchd service
service_loaded = False
try:
    r = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/com.llmgateway.litellm"],
        capture_output=True, timeout=3,
    )
    service_loaded = r.returncode == 0
except Exception:
    pass

# ── TokenSight proxy ──
tokensight_ok, _ = http_check(TOKENSIGHT_PORT, "/health")

# ── Provider state ──
provider_mode = "direct"
provider_updated_by = "?"
provider_updated_at = "?"
provider_model = "?"
provider_thinking = "?"
all_bots = []
mode_models = {}
available_providers = []
health_ok = False

if STATE_FILE.exists():
    try:
        state = json.loads(STATE_FILE.read_text())
        bot = state.get("bots", {}).get(BOT_NAME, {})
        provider_mode = bot.get("provider_mode", "direct")
        provider_updated_by = bot.get("updated_by", "?")
        provider_updated_at = bot.get("updated_at", "?")
        health_ok = state.get("litellm", {}).get("health_ok", False)
        all_bots = list(state.get("bots", {}).keys())
        mode_models = bot.get("mode_models", {})
        available_providers = bot.get("available_providers", [])

        # Resolve model names
        if provider_mode == "litellm":
            alias = bot.get("litellm_model", "local")
        else:
            alias = bot.get("direct_model", "deepseek-chat")
        provider_model = resolve_litellm_alias(alias)
        provider_thinking = resolve_litellm_alias(bot.get("thinking_model", "deepseek-reasoner"))
    except Exception:
        pass

# Moonshot/Kimi models — try bot config first, then available_providers
moonshot_model = ""
moonshot_thinking = ""
if STATE_FILE.exists():
    try:
        state = json.loads(STATE_FILE.read_text())
        bot = state.get("bots", {}).get(BOT_NAME, {})
        moonshot_model = bot.get("moonshot_model", "")
        moonshot_thinking = bot.get("moonshot_thinking_model", "")
        # Fallback: read from available_providers if bot config fields are empty
        if not moonshot_model:
            for ap in bot.get("available_providers", []):
                if ap.get("name", "").lower() == "moonshot":
                    moonshot_model = ap.get("model", "")
                    break
    except Exception:
        pass

# ── NeoMind Docker ──
nm_container_status = docker_status("neomind-telegram")
nm_running = bool(nm_container_status)

# ── Cloud providers from .env ──
cloud_providers = []
if nm_env.get("DEEPSEEK_API_KEY"):
    cloud_providers.append("DeepSeek")
if nm_env.get("ZAI_API_KEY"):
    cloud_providers.append("z.ai")
if nm_env.get("MOONSHOT_API_KEY"):
    cloud_providers.append("Kimi")
ds_key_ok = bool(gw_env.get("DEEPSEEK_API_KEY") or nm_env.get("DEEPSEEK_API_KEY"))
tg_key_ok = bool(gw_env.get("TOGETHERAI_API_KEY"))

# ── TokenSight usage data ──
PRICING = {
    "glm-5": {"in": 0.72, "out": 2.30},
    "glm-4.7": {"in": 0.38, "out": 1.98},
    "glm-4.7-flash": {"in": 0.06, "out": 0.40},
    "glm-4.6": {"in": 0.30, "out": 0.90},
    "glm-4.6v": {"in": 0.30, "out": 0.90},
    "glm-4.5": {"in": 0.60, "out": 2.20},
    "glm-4.5-air": {"in": 0.13, "out": 0.85},
    "local": {"in": 0, "out": 0},
    "deepseek-chat": {"in": 0.27, "out": 1.10},
    "deepseek-reasoner": {"in": 0.55, "out": 2.19},
    "moonshot-v1-128k": {"in": 0.60, "out": 0.60},
    "moonshot-v1-32k": {"in": 0.24, "out": 0.24},
    "kimi-k2.5": {"in": 0.60, "out": 0.60},
    "gpt-4o": {"in": 2.50, "out": 10.0},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.0},
    "claude-haiku-4-5": {"in": 0.80, "out": 4.00},
}
PROVIDER_MAP = {
    "glm-5": "Z.ai", "glm-4.7": "Z.ai", "glm-4.7-flash": "Z.ai",
    "glm-4.6": "Z.ai", "glm-4.6v": "Z.ai", "glm-4.5": "Z.ai", "glm-4.5-air": "Z.ai",
    "local": "Ollama",
    "deepseek-chat": "DeepSeek", "deepseek-reasoner": "DeepSeek",
    "moonshot-v1-128k": "Kimi", "moonshot-v1-32k": "Kimi", "kimi-k2.5": "Kimi",
    "gpt-4o": "OpenAI", "gpt-4o-mini": "OpenAI", "o3-mini": "OpenAI",
    "claude-sonnet-4-6": "Anthropic", "claude-haiku-4-5": "Anthropic",
}
PROVIDER_COLORS = {
    "Ollama": "#e879f9", "Z.ai": "#06b6d4", "DeepSeek": "#f59e0b",
    "Kimi": "#7c3aed", "OpenAI": "#10b981", "Anthropic": "#8b5cf6",
}
PROVIDER_ICONS = {
    "Ollama": "🏠", "Z.ai": "🔷", "DeepSeek": "🟡", "Kimi": "🌙",
    "OpenAI": "🟢", "Anthropic": "🟣",
}
PROVIDER_SHORT = {"Ollama": "L", "Z.ai": "Z", "DeepSeek": "DS", "Kimi": "KM", "OpenAI": "OA", "Anthropic": "AN"}
PROVIDER_ALIAS = {"zai": "Z.ai", "deepseek": "DeepSeek", "moonshot": "Kimi", "ollama": "Ollama", "openai": "OpenAI", "anthropic": "Anthropic"}


def cost_of(log):
    model = log.get("model", "")
    if model in PRICING:
        p = PRICING[model]
    elif ":" in model or model.startswith("ollama"):
        p = {"in": 0, "out": 0}  # local Ollama models are free
    else:
        p = {"in": 0.5, "out": 1.5}  # unknown model fallback
    return (log.get("input_tokens", 0) * p["in"] + log.get("output_tokens", 0) * p["out"]) / 1_000_000


def get_provider(log):
    prov = log.get("provider", "")
    if prov:
        return PROVIDER_ALIAS.get(prov.lower(), prov)
    model = log.get("model", "")
    if model in PROVIDER_MAP:
        return PROVIDER_MAP[model]
    # Local Ollama models often have format "name:tag" (e.g. qwen3:14b)
    if ":" in model or model.startswith("ollama"):
        return "Ollama"
    return "Other"


def load_tokensight_logs(days=30):
    if not USAGE_LOG.exists():
        return []
    cutoff = now_pt() - timedelta(days=days)
    logs = []
    for line in USAGE_LOG.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            ts = utc_to_pt(entry["timestamp"])
            entry["_pt_date"] = ts.strftime("%Y-%m-%d")
            entry["_pt_month"] = ts.strftime("%Y-%m")
            if ts >= cutoff:
                logs.append(entry)
        except Exception:
            pass
    return logs


ts_logs = load_tokensight_logs(30)
_today_str = now_pt().strftime("%Y-%m-%d")
_month_str = now_pt().strftime("%Y-%m")
today_logs = [l for l in ts_logs if l.get("_pt_date") == _today_str]
month_logs = [l for l in ts_logs if l.get("_pt_month") == _month_str]
today_cost = sum(cost_of(l) for l in today_logs)
month_cost = sum(cost_of(l) for l in month_logs)
today_calls = len(today_logs)

# ── DeepSeek balance ──
def get_deepseek_balance():
    key = gw_env.get("DEEPSEEK_API_KEY") or nm_env.get("DEEPSEEK_API_KEY", "")
    if not key:
        return None
    data = http_get_json(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        timeout=5,
    )
    if data and data.get("balance_infos"):
        b = data["balance_infos"][0]
        return {
            "total": float(b.get("total_balance", 0)),
            "topped": float(b.get("topped_up_balance", 0)),
            "granted": float(b.get("granted_balance", 0)),
        }
    return None


ds_balance = get_deepseek_balance()

# ── LiteLLM daily usage (from log parsing) ──
litellm_daily_calls = 0
litellm_daily_errs = 0
if LITELLM_LOG.exists():
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        data = {"date": today_str, "calls": 0, "errors": 0, "log_offset": 0, "log_inode": 0}
        if USAGE_DAILY.exists():
            saved = json.loads(USAGE_DAILY.read_text())
            if saved.get("date") == today_str:
                data = saved
            # else reset for new day

        st = os.stat(LITELLM_LOG)
        cur_inode, cur_size = st.st_ino, st.st_size
        saved_offset = data.get("log_offset", 0)
        if cur_inode != data.get("log_inode", 0) or cur_size < saved_offset:
            saved_offset = 0

        if cur_size > saved_offset:
            with open(LITELLM_LOG, "r", errors="replace") as f:
                f.seek(saved_offset)
                chunk = f.read()
                data["calls"] += len(re.findall(r"POST /v1/chat/completions.*200", chunk))
                data["errors"] += len(re.findall(r"POST /v1/chat/completions.*[45]\d\d", chunk))

        data["log_offset"] = cur_size
        data["log_inode"] = cur_inode
        # Atomic write
        tmp = USAGE_DAILY.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.rename(USAGE_DAILY)

        litellm_daily_calls = data["calls"]
        litellm_daily_errs = data["errors"]
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════
# Menu Output
# ════════════════════════════════════════════════════════════════

def p(text):
    print(text)

# ── Menu bar title ──
infra_ok = ollama_ok and litellm_ok
infra_partial = ollama_ok or litellm_ok

if infra_ok:
    status_dot = "🟢"
elif infra_partial:
    status_dot = "🟡"
else:
    status_dot = "🔴"

mode_icon = "🏠" if provider_mode == "litellm" else "☁️"

# Cost summary in title
if today_calls > 0:
    cost_str = f"¥{today_cost:.2f}"
else:
    cost_str = ""

title_parts = [f"🧠{mode_icon}"]
if cost_str:
    title_parts.append(cost_str)
p(f"{status_dot} {' '.join(title_parts)} | size=13")
p("---")

# ════════════════════════════════════════════════════════════════
# Section 1: Infrastructure
# ════════════════════════════════════════════════════════════════

p("🏗 Infrastructure")
p("--")

# Ollama
if ollama_ok:
    p("--✅ Ollama — 运行中 | color=green")
    if ollama_models:
        p("----已安装模型:")
        for name, size in ollama_models:
            p(f"----  {name} ({size:.1f}GB) | font=Menlo size=12")
    if ollama_loaded:
        p("----当前在 GPU 内存中:")
        for name, vram in ollama_loaded:
            p(f"----  🟢 {name} (VRAM {vram:.1f}GB) | font=Menlo size=12 color=green")
    elif ollama_ok:
        p("----  (无模型在内存中) | color=gray")
else:
    p("--❌ Ollama — 未运行 | color=red")

p("--")

# LiteLLM
if litellm_ok:
    p(f"--✅ LiteLLM Proxy — 运行中 (port {LITELLM_PORT}) | color=green")
    if litellm_models:
        p("----路由表:")
        for m in litellm_models:
            actual = resolve_litellm_alias(m)
            display = f"{m} → {actual}" if actual != m else m
            p(f"----  ✅ {display} | font=Menlo size=12")
    if service_loaded:
        p("----服务: 已注册 (开机自启) | color=green")
    else:
        p("----服务: 未注册 | color=orange")
else:
    p(f"--❌ LiteLLM Proxy — 未运行 | color=red")
    if LITELLM_ERR_LOG.exists():
        try:
            lines = LITELLM_ERR_LOG.read_text().splitlines()[-5:]
            for l in lines:
                if re.search(r"error|fatal|permission|denied|failed|traceback", l, re.I):
                    p(f"----⚠️ {l[:90]} | font=Menlo size=11 color=red")
                    break
        except Exception:
            pass

p("--")

# TokenSight proxy
if tokensight_ok:
    p(f"--✅ TokenSight Proxy — 运行中 (port {TOKENSIGHT_PORT}) | color=green")
    p("----🔷 Z.ai → localhost:8900/zai | font=Menlo size=11")
    p("----🟡 DeepSeek → localhost:8900/deepseek | font=Menlo size=11")
    p("----🟢 OpenAI → localhost:8900/openai | font=Menlo size=11")
else:
    p(f"--🔴 TokenSight Proxy — 未运行 | color=#ef4444")
    ts_cmd = NEOMIND_DIR / "tokensight" / "TokenSight.command"
    if ts_cmd.exists():
        p(f"----▶️ Start Proxy | bash={ts_cmd} terminal=true")

p("---")

# ════════════════════════════════════════════════════════════════
# Section 2: Model Management
# ════════════════════════════════════════════════════════════════

p("📦 模型管理")

if MODELS_DIR.exists():
    all_configured = set()
    model_files = sorted(MODELS_DIR.glob("*.yaml"))
    for mf in model_files:
        try:
            content = mf.read_text()
            mname = ""
            mmodel = ""
            for line in content.splitlines():
                if line.startswith("name="):
                    mname = line.split("=", 1)[1]
                elif line.startswith("model="):
                    mmodel = line.split("=", 1)[1]
                    all_configured.add(mmodel)
            mbase = mf.stem
            disabled = (MODELS_DIR / f"{mbase}.disabled").exists()

            if disabled:
                p(f"--○ {mname} (已禁用) | color=gray")
                p(f"----模型: {mmodel} | font=Menlo size=11 color=gray")
                p(f"----✅ 启用 | bash={GATEWAY_CLI} param1=enable param2={mname} terminal=false refresh=true")
                p(f"----🗑 删除 | bash={GATEWAY_CLI} param1=remove param2={mname} terminal=false refresh=true")
            elif "ollama" in mmodel:
                p(f"--🟢 {mname} (本地) | color=green")
                p(f"----模型: {mmodel} | font=Menlo size=11")
                p(f"----⏸ 禁用 | bash={GATEWAY_CLI} param1=disable param2={mname} terminal=false refresh=true")
                p(f"----🗑 删除 | bash={GATEWAY_CLI} param1=remove param2={mname} terminal=false refresh=true")
            else:
                p(f"--🔵 {mname} (云端) | color=#4a9eff")
                p(f"----模型: {mmodel} | font=Menlo size=11")
                p(f"----⏸ 禁用 | bash={GATEWAY_CLI} param1=disable param2={mname} terminal=false refresh=true")
                p(f"----🗑 删除 | bash={GATEWAY_CLI} param1=remove param2={mname} terminal=false refresh=true")
        except Exception:
            pass

p("--")
p("--➕ 添加模型")
p("----🏠 本地 Ollama 模型")

if ollama_ok and ollama_models:
    for name, _ in ollama_models:
        oname = name.replace(":", "-")
        if f"ollama_chat/{name}" not in all_configured:
            p(f"------➕ {name} | bash={GATEWAY_CLI} param1=add param2={oname} param3=ollama_chat/{name} terminal=false refresh=true")

p(f"------📥 拉取新模型... | bash={GATEWAY_CLI} param1=pull terminal=true")

p("----☁️ 云端模型 (常用)")
p(f"------DeepSeek Chat | bash={GATEWAY_CLI} param1=add param2=deepseek-chat param3=deepseek/deepseek-chat terminal=false refresh=true")
p(f"------DeepSeek Reasoner | bash={GATEWAY_CLI} param1=add param2=deepseek-reasoner param3=deepseek/deepseek-reasoner terminal=false refresh=true")
p(f"------Qwen3 235B (Together) | bash={GATEWAY_CLI} param1=add param2=qwen3-235b param3=together_ai/Qwen/Qwen3-235B-A22B terminal=false refresh=true")
p(f"------Claude Sonnet 4.6 | bash={GATEWAY_CLI} param1=add param2=claude param3=anthropic/claude-sonnet-4-6-20250214 terminal=false refresh=true")

p("---")

# ════════════════════════════════════════════════════════════════
# Section 3: NeoMind Bot
# ════════════════════════════════════════════════════════════════

p("🤖 NeoMind Agent")
p("--")

if nm_running:
    p("--✅ Telegram bot: 运行中 | color=green")
    p("--  容器: neomind-telegram | font=Menlo size=11 color=gray")

    # Provider status
    if provider_mode == "litellm":
        p("--  🔌 Provider: LiteLLM → local (Ollama) | color=#06b6d4")
        if not litellm_ok:
            p("--  ⚠️ 错误: LiteLLM 未运行但 NeoMind 配置了 LiteLLM! | color=red")
            p("--    → NeoMind 会 fallback 到 DeepSeek 直连 | font=Menlo size=11 color=orange")
        if litellm_ok and not ollama_ok:
            p("--  ⚠️ Ollama 未运行 → LiteLLM fallback 到 DeepSeek | color=orange")
    else:
        prov_names = "/".join(cloud_providers) if cloud_providers else "DeepSeek/z.ai"
        p(f"--  🔌 Provider: Direct {prov_names} | color=#eab308")

    if provider_model != "?":
        p(f"--  🎯 模型: {provider_model} (思考: {provider_thinking}) | font=Menlo size=11")
    if moonshot_model:
        if moonshot_thinking:
            p(f"--  🌙 Kimi: {moonshot_model} (思考: {moonshot_thinking}) | font=Menlo size=11 color=#06b6d4")
        else:
            p(f"--  🌙 Kimi: {moonshot_model} | font=Menlo size=11 color=#06b6d4")
    if provider_updated_by != "?":
        p(f"--  📡 同步: {provider_updated_by} @ {provider_updated_at} | font=Menlo size=11 color=gray")

    # Per-model usage stats (from TokenSight logs)
    if today_logs or month_logs:
        p("--")
        p("--📊 模型用量")
        # Aggregate by model
        model_today = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cost": 0.0})
        model_month = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cost": 0.0})
        for l in today_logs:
            m = l.get("model", "?")
            model_today[m]["calls"] += 1
            model_today[m]["in"] += l.get("input_tokens", 0)
            model_today[m]["out"] += l.get("output_tokens", 0)
            model_today[m]["cost"] += cost_of(l)
        for l in month_logs:
            m = l.get("model", "?")
            model_month[m]["calls"] += 1
            model_month[m]["in"] += l.get("input_tokens", 0)
            model_month[m]["out"] += l.get("output_tokens", 0)
            model_month[m]["cost"] += cost_of(l)
        # All models seen
        all_models = sorted(set(list(model_today.keys()) + list(model_month.keys())))
        for m in all_models:
            td = model_today.get(m)
            md = model_month.get(m)
            prov_name = PROVIDER_MAP.get(m, "Other")
            icon = PROVIDER_ICONS.get(prov_name, "⚪")
            color = PROVIDER_COLORS.get(prov_name, "#999")
            p(f"----{icon} {m} | color={color}")
            if td and td["calls"] > 0:
                tok_in = fmt_tokens(td["in"])
                tok_out = fmt_tokens(td["out"])
                p(f"------今日: {td['calls']} calls, ↑{tok_in} ↓{tok_out}, ¥{td['cost']:.4f} | font=Menlo size=11")
            else:
                p("------今日: — | font=Menlo size=11 color=gray")
            if md and md["calls"] > 0:
                tok_in = fmt_tokens(md["in"])
                tok_out = fmt_tokens(md["out"])
                p(f"------本月: {md['calls']} calls, ↑{tok_in} ↓{tok_out}, ¥{md['cost']:.4f} | font=Menlo size=11")

    # Model routing (per-mode)
    if mode_models:
        p("--")
        p("--Model Routing")
        mode_icons = {"fin": "💰", "chat": "💬", "coding": "💻"}
        for mode_name in ["fin", "chat", "coding"]:
            info = mode_models.get(mode_name, {})
            if info:
                m = info.get("model", "?")
                t = info.get("thinking_model", "?")
                prov = info.get("provider", "?")
                if t and t != m:
                    p(f"----{mode_icons.get(mode_name, '')} {mode_name}: {prov}/{m} (think: {t}) | size=12")
                else:
                    p(f"----{mode_icons.get(mode_name, '')} {mode_name}: {prov}/{m} | size=12")

    # Cloud providers from state
    if available_providers:
        p("--")
        p("--Cloud Providers")
        for prov in available_providers:
            p(f"----✅ {prov['name']}: {prov.get('model', '?')} | color=#00aa00 size=12")
    elif cloud_providers:
        p("--")
        p("--Cloud Providers")
        for cp in cloud_providers:
            p(f"----✅ {cp} | color=#00aa00 size=12")

    # LiteLLM daily usage
    if provider_mode == "litellm":
        p("--")
        p("--  📊 今日 LiteLLM 用量:")
        p(f"--    成功: {litellm_daily_calls} 次 | font=Menlo size=11 color=green")
        if litellm_daily_errs > 0:
            p(f"--    失败: {litellm_daily_errs} 次 | font=Menlo size=11 color=red")
        p("--    费用: $0 (本地模型) | font=Menlo size=11 color=green")

    # Recent LLM calls
    last_ok = docker_logs("neomind-telegram", 100, r"\[llm\].*✅")
    last_err = docker_logs("neomind-telegram", 100, r"\[llm\].*❌")
    if last_ok:
        line = re.sub(r".*\[llm\] ", "", last_ok[-1])
        p(f"--  最近成功: {line} | font=Menlo size=11 color=green")
    if last_err:
        line = re.sub(r".*\[llm\] ", "", last_err[-1])
        p(f"--  最近失败: {line} | font=Menlo size=11 color=red")

    p("--")

    # Provider switching
    p("--━━━ Provider 切换 ━━━ | size=13")
    if provider_mode == "litellm":
        p("--  当前: LiteLLM (本地 Ollama, 免费) ✓ | color=#06b6d4")
        p(f"--  切换到 Direct API | bash={PYTHON} param1={CTL} param2=set param3={BOT_NAME} param4=direct terminal=false refresh=true")
    else:
        p("--  当前: Direct API ✓ | color=#eab308")
        p(f"--  切换到 LiteLLM (本地 Ollama, 免费) | bash={PYTHON} param1={CTL} param2=set param3={BOT_NAME} param4=litellm terminal=false refresh=true")
    p("--  ⚡ 即时生效，无需重启容器 | font=Menlo size=10 color=gray")

    p("--")
    p("--━━━ 操作 ━━━ | size=13")
    p(f"--查看 Bot 日志 | bash={SCRIPT_DIR}/view-bot-logs.sh terminal=true")
    p(f"--查看 LLM 调用日志 | bash={SCRIPT_DIR}/view-llm-logs.sh terminal=true")
    p(f"--重启 Bot | bash={SCRIPT_DIR}/restart-bot.sh terminal=false refresh=true")
else:
    p("--⚪ Telegram bot: 未运行 | color=gray")
    if provider_mode == "litellm" and not litellm_ok:
        p("--  ⚠️ LiteLLM 也未运行 — 启动后 Bot 可用本地模型 | color=orange")
    p(f"--▶️ 启动 Bot | bash={SCRIPT_DIR}/start-bot.sh terminal=false refresh=true")

# Per-bot status (multi-bot)
if len(all_bots) > 1:
    p("--")
    p("--All Bots")
    for bot in all_bots:
        try:
            state = json.loads(STATE_FILE.read_text())
            bm = state.get("bots", {}).get(bot, {}).get("provider_mode", "?")
            icon = "🏠" if bm == "litellm" else ("☁️" if bm == "direct" else "?")
            p(f"----{bot}: {icon} {bm} | color=#333333")
            p(f"------→ LiteLLM | bash={PYTHON} param1={CTL} param2=set param3={bot} param4=litellm terminal=false refresh=true")
            p(f"------→ Direct  | bash={PYTHON} param1={CTL} param2=set param3={bot} param4=direct terminal=false refresh=true")
        except Exception:
            pass

p("---")

# ════════════════════════════════════════════════════════════════
# Section 4: TokenSight — Usage & Costs
# ════════════════════════════════════════════════════════════════

p("◈ TokenSight")

# Backend mode
BACKEND_FILE = TOKENSIGHT_DIR / "backend"
ts_backend = "direct"
if BACKEND_FILE.exists():
    mode_val = BACKEND_FILE.read_text().strip().lower()
    if mode_val == "litellm":
        ts_backend = "litellm"

if ts_backend == "litellm":
    ll_icon = "🟢" if litellm_ok else "🔴"
    p(f"--⚡ Backend: LiteLLM {ll_icon} | color=#a78bfa")
    p("----Requests: app → tokensight → LiteLLM → API | color=#666 size=11")
    p(f"----🔀 Switch to Direct API | bash={PYTHON} param1=-c param2=open('{BACKEND_FILE}','w').write('direct') terminal=false refresh=true")
else:
    p("--⚡ Backend: Direct API | color=#06b6d4")
    p("----Requests: app → tokensight → API | color=#666 size=11")
    p(f"----🔀 Switch to LiteLLM | bash={PYTHON} param1=-c param2=open('{BACKEND_FILE}','w').write('litellm') terminal=false refresh=true")

p("--")

# Balances
p("--💰 Balances")
if ds_balance:
    p(f"----🟡 DeepSeek: ¥{ds_balance['total']:.2f} CNY | color=#f59e0b")
    p(f"------Topped-up: ¥{ds_balance['topped']:.2f}")
    p(f"------Granted: ¥{ds_balance['granted']:.2f}")
else:
    p("----🟡 DeepSeek: (未配置/无法获取) | color=#666")
p("----🔷 Z.ai: Pay-as-you-go (无余额 API) | color=#06b6d4")

p("--")

# Today
p("--📊 Today")
if today_calls == 0:
    p("----No calls yet today | color=#666")
else:
    p(f"----Total: {today_calls} calls, ¥{today_cost:.4f} | color=#e2e8f0")
    p("------")
    by_prov = defaultdict(list)
    for l in today_logs:
        by_prov[get_provider(l)].append(l)
    for prov_name in ["Ollama", "Z.ai", "DeepSeek", "Kimi", "OpenAI", "Anthropic", "Other"]:
        if prov_name not in by_prov:
            continue
        plogs = by_prov[prov_name]
        pcost = sum(cost_of(l) for l in plogs)
        icon = PROVIDER_ICONS.get(prov_name, "⚪")
        color = PROVIDER_COLORS.get(prov_name, "#999")
        p(f"----{icon} {prov_name}: {len(plogs)} calls, ¥{pcost:.4f} | color={color}")
        by_model = defaultdict(lambda: {"calls": 0, "cost": 0.0})
        for l in plogs:
            m = l.get("model", "?")
            by_model[m]["calls"] += 1
            by_model[m]["cost"] += cost_of(l)
        for model, v in sorted(by_model.items(), key=lambda x: -x[1]["cost"]):
            p(f"------{model}: {v['calls']} calls, ¥{v['cost']:.4f}")

p("--")

# This Month
p("--📅 This Month")
if not month_logs:
    p("----No calls this month | color=#666")
else:
    p(f"----Total: {len(month_logs)} calls, ¥{month_cost:.4f} | color=#e2e8f0")
    p("------")
    by_prov = defaultdict(list)
    for l in month_logs:
        by_prov[get_provider(l)].append(l)
    for prov_name in ["Ollama", "Z.ai", "DeepSeek", "Kimi", "OpenAI", "Anthropic", "Other"]:
        if prov_name not in by_prov:
            continue
        plogs = by_prov[prov_name]
        pcost = sum(cost_of(l) for l in plogs)
        ptokens = sum(l.get("input_tokens", 0) + l.get("output_tokens", 0) for l in plogs)
        icon = PROVIDER_ICONS.get(prov_name, "⚪")
        color = PROVIDER_COLORS.get(prov_name, "#999")
        p(f"----{icon} {prov_name}: {len(plogs)} calls, {fmt_tokens(ptokens)} tok, ¥{pcost:.4f} | color={color}")
        by_model = defaultdict(lambda: {"calls": 0, "cost": 0.0, "tok": 0})
        for l in plogs:
            m = l.get("model", "?")
            by_model[m]["calls"] += 1
            by_model[m]["cost"] += cost_of(l)
            by_model[m]["tok"] += l.get("input_tokens", 0) + l.get("output_tokens", 0)
        for model, v in sorted(by_model.items(), key=lambda x: -x[1]["cost"]):
            p(f"------{model}: {v['calls']} calls, {fmt_tokens(v['tok'])} tok, ¥{v['cost']:.4f}")

# By tag/app
by_tag = defaultdict(float)
for l in month_logs:
    by_tag[l.get("tag", "default")] += cost_of(l)
if len(by_tag) > 1:
    p("--")
    p("--🏷 By App")
    for tag, cost in sorted(by_tag.items(), key=lambda x: -x[1]):
        p(f"----{tag}: ¥{cost:.4f}")

p("---")

# ════════════════════════════════════════════════════════════════
# Section 5: API Keys
# ════════════════════════════════════════════════════════════════

p("🔑 API Keys")
if ds_key_ok:
    p("--DeepSeek:  ✅ 已配置 | color=green")
else:
    p("--DeepSeek:  ⚠️ 未配置 | color=orange")
if tg_key_ok:
    p("--Together:  ✅ 已配置 | color=green")
else:
    p("--Together:  ⚠️ 未配置 (可选) | color=gray")

if GATEWAY_ENV.exists():
    p(f"--编辑 Gateway Keys | bash=/usr/bin/open param1=-a param2=TextEdit param3={GATEWAY_ENV} terminal=false")
if NEOMIND_ENV.exists():
    p(f"--编辑 NeoMind Keys | bash=/usr/bin/open param1=-a param2=TextEdit param3={NEOMIND_ENV} terminal=false")

p("---")

# ════════════════════════════════════════════════════════════════
# Section 6: Quick Actions
# ════════════════════════════════════════════════════════════════

p("🚀 操作")

if litellm_ok:
    stop_script = ACTIONS_DIR / "stop-litellm.sh"
    p(f"--🛑 停止 LiteLLM | bash={stop_script} terminal=false refresh=true")
else:
    start_script = ACTIONS_DIR / "start-litellm.sh"
    p(f"--▶️  启动 LiteLLM | bash={start_script} terminal=false refresh=true")

if ollama_ok:
    p("--🛑 停止 Ollama | bash=/usr/bin/pkill param1=-f param2=ollama terminal=false refresh=true")
else:
    p("--▶️  启动 Ollama | bash=/usr/bin/open param1=-a param2=Ollama terminal=false refresh=true")

restart_script = ACTIONS_DIR / "restart-all.sh"
p(f"--🔄 全部重启 | bash={restart_script} terminal=false refresh=true")

p(f"--Check LiteLLM Health | bash={PYTHON} param1={CTL} param2=health terminal=false refresh=true")

p("---")

# ════════════════════════════════════════════════════════════════
# Section 7: Links & Logs
# ════════════════════════════════════════════════════════════════

p("🔗 打开")
p(f"--LiteLLM Dashboard | href=http://localhost:{LITELLM_PORT}/ui")
ts_dashboard = NEOMIND_DIR / "tokensight" / "index.html"
if ts_dashboard.exists():
    p(f"--TokenSight Dashboard | bash=/usr/bin/open param1={ts_dashboard} terminal=false")
p("--Ollama 模型库 | href=https://ollama.com/library")
p("--DeepSeek 控制台 | href=https://platform.deepseek.com")
p("--Together 控制台 | href=https://api.together.ai")

p("---")

p("📋 日志")
if LITELLM_LOG.exists():
    p(f"--查看 LiteLLM 日志 | bash=/usr/bin/open param1=-a param2=Console param3={LITELLM_LOG} terminal=false")
if LITELLM_ERR_LOG.exists():
    p(f"--查看错误日志 | bash=/usr/bin/open param1=-a param2=Console param3={LITELLM_ERR_LOG} terminal=false")
    try:
        last_err = LITELLM_ERR_LOG.read_text().splitlines()[-1][:80]
        if last_err.strip():
            p("--最近一条错误:")
            p(f"--  {last_err}... | font=Menlo size=11 color=red")
    except Exception:
        pass

tail_log = ACTIONS_DIR / "tail-log.sh"
tail_err = ACTIONS_DIR / "tail-errors.sh"
if tail_log.exists():
    p(f"--Terminal 打开日志 | bash={tail_log} terminal=true")
if tail_err.exists():
    p(f"--Terminal 打开错误日志 | bash={tail_err} terminal=true")

p(f"--Show Full Provider Status | bash={PYTHON} param1={CTL} param2=get terminal=true")
p(f"--Open State File | bash=open param1={STATE_FILE} terminal=false")
p(f"--Open State Dir | bash=open param1={STATE_DIR} terminal=false")

ts_cli = NEOMIND_DIR / "tokensight" / "tokensight.py"
if ts_cli.exists():
    p(f"--TokenSight Summary | bash={PYTHON} param1={ts_cli} param2=summary terminal=true")
    p(f"--TokenSight Logs | bash={PYTHON} param1={ts_cli} param2=log terminal=true")

p("---")

# ════════════════════════════════════════════════════════════════
# Section 8: Troubleshooting
# ════════════════════════════════════════════════════════════════

p("🔧 故障排查")
p("--")
p("--━━━ Ollama 问题 ━━━ | size=13")
p("--")
p("--Ollama 没启动? | color=white")
p("--  → 打开 Ollama app，或终端跑 ollama serve | font=Menlo size=11 color=gray")
p("--")
p("--模型加载慢 / 首次请求超时? | color=white")
p("--  → 首次加载到 GPU 需要 20-30s，属正常 | font=Menlo size=11 color=gray")
p("--  → 手动预热: ollama run qwen3:14b 'hi' | font=Menlo size=11 color=gray")
p("--")
p("--━━━ LiteLLM 问题 ━━━ | size=13")
p("--")
p("--401 Unauthorized? | color=white")
p("--  → 请求必须带 Authorization: Bearer <MASTER_KEY> | font=Menlo size=11 color=gray")
p("--  → 检查 .env 中 LITELLM_MASTER_KEY | font=Menlo size=11 color=gray")
p("--")
p("--cloud-cheap 报错? (DeepSeek) | color=white")
p("--  → 检查 .env 中 DEEPSEEK_API_KEY | font=Menlo size=11 color=gray")
p("--  → DeepSeek 可能限流: 等 1 分钟重试 | font=Menlo size=11 color=gray")
p("--")
p("--端口被占用? | color=white")
p("--  → lsof -i :4000 / lsof -i :8900 查看 | font=Menlo size=11 color=gray")
p("--  → kill -9 $(lsof -ti :PORT) 强制释放 | font=Menlo size=11 color=gray")
p("--")
p("--━━━ 常用命令 ━━━ | size=13")
p("--")
run_test = ACTIONS_DIR / "run-test.sh"
if run_test.exists():
    p(f"--运行完整测试 | bash={run_test} terminal=true")
if GATEWAY_ENV.exists():
    p(f"--编辑 .env | bash=/usr/bin/open param1=-a param2=TextEdit param3={GATEWAY_ENV} terminal=false")
if LITELLM_CONFIG.exists():
    p(f"--编辑 LiteLLM 配置 | bash=/usr/bin/open param1=-a param2=TextEdit param3={LITELLM_CONFIG} terminal=false")
p(f"--打开 Gateway 目录 | bash=/usr/bin/open param1={GATEWAY_DIR} terminal=false")
p(f"--打开 NeoMind 目录 | bash=/usr/bin/open param1={NEOMIND_DIR} terminal=false")

troubleshooting_md = GATEWAY_DIR / "TROUBLESHOOTING.md"
if troubleshooting_md.exists():
    p(f"--打开 Troubleshooting 文档 | bash=/usr/bin/open param1={troubleshooting_md} terminal=false")

p("---")
p(f"State: {STATE_FILE} | size=11 color=gray")
p("Refresh | refresh=true")
