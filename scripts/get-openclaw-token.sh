#!/bin/bash
# ─────────────────────────────────────────────────────────
# 获取 OpenClaw Gateway Token
#
# 用法：在你的终端（不是 Docker 容器里）运行：
#   bash scripts/get-openclaw-token.sh
#
# 脚本会自动：
# 1. 找到你运行中的 OpenClaw 容器
# 2. 尝试多种方式获取 token
# 3. 打印出来让你填到 .env 里
# ─────────────────────────────────────────────────────────

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[info]${NC} $1"; }
ok()    { echo -e "${GREEN}[ok]${NC} $1"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $1"; }
err()   { echo -e "${RED}[error]${NC} $1"; }

echo ""
info "正在查找 OpenClaw 容器..."
echo ""

# Step 1: 找容器
CONTAINERS=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -i claw || true)

if [ -z "$CONTAINERS" ]; then
    err "没有找到运行中的 OpenClaw 容器"
    echo ""
    echo "  请确认 OpenClaw 在运行："
    echo "    docker ps | grep claw"
    echo ""
    echo "  如果没在运行，先启动它："
    echo "    cd <你的openclaw目录> && docker compose up -d"
    exit 1
fi

echo "  找到以下容器："
echo "$CONTAINERS" | while read c; do echo "    📦 $c"; done
echo ""

# 取第一个容器（通常是 gateway 或 cli）
CONTAINER=$(echo "$CONTAINERS" | head -1)
info "使用容器: $CONTAINER"
echo ""

# Step 2: 尝试多种方法获取 token
TOKEN=""

# 方法 1: openclaw config get
info "方法 1: openclaw config get gateway.auth.token"
TOKEN=$(docker exec "$CONTAINER" openclaw config get gateway.auth.token 2>/dev/null || true)
if [ -n "$TOKEN" ] && [ "$TOKEN" != "null" ] && [ "$TOKEN" != "undefined" ]; then
    ok "成功！"
    echo ""
    echo "═══════════════════════════════════════════════════"
    echo -e "  ${GREEN}OPENCLAW_DEVICE_TOKEN=${TOKEN}${NC}"
    echo "═══════════════════════════════════════════════════"
    echo ""
    echo "  把上面这行粘贴到你的 .env 文件里"
    exit 0
fi
warn "方法 1 未成功"

# 方法 2: openclaw doctor --generate-gateway-token
info "方法 2: openclaw doctor --generate-gateway-token"
RESULT=$(docker exec "$CONTAINER" openclaw doctor --generate-gateway-token 2>/dev/null || true)
if [ -n "$RESULT" ]; then
    # 尝试从输出中提取 token
    TOKEN=$(echo "$RESULT" | grep -oE '[A-Za-z0-9_-]{20,}' | head -1 || true)
    if [ -n "$TOKEN" ]; then
        ok "成功！"
        echo ""
        echo "═══════════════════════════════════════════════════"
        echo -e "  ${GREEN}OPENCLAW_DEVICE_TOKEN=${TOKEN}${NC}"
        echo "═══════════════════════════════════════════════════"
        echo ""
        echo "  把上面这行粘贴到你的 .env 文件里"
        exit 0
    fi
fi
warn "方法 2 未成功"

# 方法 3: 读取配置文件
info "方法 3: 读取配置文件"
for CONFIG_PATH in \
    "/home/node/.openclaw/config.json" \
    "/home/node/.openclaw/.credentials.json" \
    "/home/node/.openclaw/gateway.json" \
    "/root/.openclaw/config.json" \
    "/root/.openclaw/.credentials.json"; do
    CONTENT=$(docker exec "$CONTAINER" cat "$CONFIG_PATH" 2>/dev/null || true)
    if [ -n "$CONTENT" ]; then
        info "  找到文件: $CONFIG_PATH"
        # 尝试提取 token 字段
        TOKEN=$(echo "$CONTENT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    # 常见的 token 字段名
    for key in ['gatewayToken', 'gateway_token', 'token', 'auth_token', 'authToken']:
        if key in d:
            print(d[key])
            break
    else:
        # 递归查找
        def find(obj, target='token'):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if 'token' in k.lower() and isinstance(v, str) and len(v) > 10:
                        print(v)
                        return True
                    if isinstance(v, (dict, list)):
                        if find(v): return True
            elif isinstance(obj, list):
                for item in obj:
                    if find(item): return True
            return False
        find(d)
except: pass
" 2>/dev/null || true)
        if [ -n "$TOKEN" ]; then
            ok "成功！从配置文件中提取到 token"
            echo ""
            echo "═══════════════════════════════════════════════════"
            echo -e "  ${GREEN}OPENCLAW_DEVICE_TOKEN=${TOKEN}${NC}"
            echo "═══════════════════════════════════════════════════"
            echo ""
            echo "  把上面这行粘贴到你的 .env 文件里"
            exit 0
        fi
    fi
done
warn "方法 3 未成功"

# 方法 4: 查看环境变量
info "方法 4: 检查容器环境变量"
TOKEN=$(docker exec "$CONTAINER" printenv OPENCLAW_GATEWAY_TOKEN 2>/dev/null || true)
if [ -n "$TOKEN" ]; then
    ok "成功！从环境变量获取"
    echo ""
    echo "═══════════════════════════════════════════════════"
    echo -e "  ${GREEN}OPENCLAW_DEVICE_TOKEN=${TOKEN}${NC}"
    echo "═══════════════════════════════════════════════════"
    echo ""
    echo "  把上面这行粘贴到你的 .env 文件里"
    exit 0
fi
warn "方法 4 未成功"

# 方法 5: 列出可用命令
echo ""
warn "自动获取均未成功，手动排查："
echo ""
info "OpenClaw 可用命令："
docker exec "$CONTAINER" openclaw --help 2>&1 | head -30 || true
echo ""
info "OpenClaw config 子命令："
docker exec "$CONTAINER" openclaw config --help 2>&1 | head -20 || true
echo ""
info "OpenClaw 配置目录内容："
docker exec "$CONTAINER" ls -la /home/node/.openclaw/ 2>/dev/null || \
docker exec "$CONTAINER" ls -la /root/.openclaw/ 2>/dev/null || \
echo "  未找到配置目录"
echo ""
info "把上面的输出发给我，我帮你定位 token"
