# 2026-08-07 — `/health` 报 ok，而所有云模型 401 了五天

## 症状

LLM-Router `http://127.0.0.1:8000/health` 稳定返回：

```json
{"status": "ok", "models_total": 10, "providers": ["mlx-local","deepseek","zai","moonshot"]}
```

同时**每一个云模型请求都 401**。健康检查、xbar 菜单、依赖它的 agent 全都以为一切正常。

## 根因链

两个独立的坑叠在一起：

### 1. `.env.runtime` 是从**调用方 shell** 快照出来的

`start.sh` 用 `for var in DEEPSEEK_API_KEY ZAI_API_KEY MOONSHOT_API_KEY ...` 把 shell 里的 key
写进 `.env.runtime` 再 source。从**非 login shell**（xbar / GUI / 某些自动化）跑 `./start.sh`，
这些变量不存在 → 文件里只剩 `LLM_ROUTER_API_KEY` → config 里的 `${DEEPSEEK_API_KEY}` 没被展开，
**字面量**被当 key 发给上游。

上游的报错就是铁证：

```text
"Your api key: ****KEY} is invalid"
                     ^^^^  末尾这个 KEY} = 未展开的 ${...KEY}
```

看到这种结尾就别再去重办 key 了。`scripts/repair.sh` 的注释早就记录了这个坑
（"xbar 调用时是非交互 shell，没有 ~/.zshrc 里的 provider keys"），修法就是先 `source ~/.zshrc`：

```bash
zsh -lc './start.sh restart'      # login shell，会加载 .zshrc
```

### 2. poller 吞掉发现失败并保留旧模型表

```python
except Exception as exc:
    logger.warning("CloudPoller %s: fetch failed (%s) — keeping prior list", name, exc)
    return None        # ← registry 保持旧状态，/health 照常报 ok
```

"keeping prior list" 对**瞬时抖动**是对的设计，但它让**持续性认证失败**长得和健康一模一样：
模型表还在（boot 时从 config 种下的），`status` 硬编码 `"ok"`，没有任何字段暴露"我上次发现失败了"。

## 修 readiness 前：先查谁在消费它

**这一步不能跳。** `scripts/repair.sh` 是这么用的：

```bash
if curl -sf --max-time 3 http://localhost:8000/health >/dev/null; then echo "Router OK"
else "$DIR/start.sh" start; fi     # ← /health 失败 = 重启 router
```

如果把 `/health` 改成"key 坏了就返回 503"，repair.sh 会**无限重启 router** —— 而重启根本修不了
上游余额不足或 key 缺失。**liveness 和 readiness 是两个东西，别合并。**

## 正解

- `/health` 保持 **200**（liveness，repair.sh 的契约不变），但 body 说实话：
  `status: ok|degraded` + `provider_status`（每家 ok/error/checked_at）+ `degraded_providers`。
- 新增 `/ready`：所有云 provider 上次发现都失败 → **503**。
- poller 里加 `self.status[name] = {...}` 记录每次发现结果。
- 上游错误串在暴露前过一遍 `_redact_secrets()` —— 诊断端点不能变成第二个泄露点。

## 验证：必须证明 degraded 分支真会触发

只看到 `/health` 200、`/ready` 200 **等于什么都没验**——我修的就是"只会说 OK 的健康检查"。
拿真坏 key 起第二个实例（别动线上那个）：

```bash
sed 's/^  port: 8000/  port: 8010/' config.yaml > /tmp/config_degraded.yaml
LLM_ROUTER_CONFIG=/tmp/config_degraded.yaml \
  DEEPSEEK_API_KEY=sk-bogus ZAI_API_KEY=bogus MOONSHOT_API_KEY=bogus \
  .venv/bin/python router.py &

curl -s localhost:8010/health   # 期望 status=degraded，三家 ok=false 带真 401 文本
curl -s -o /dev/null -w '%{http_code}' localhost:8010/ready   # 期望 503
```

收尾按**端口**杀，别按 cmdline 杀 —— `pkill -f config_degraded.yaml` 匹配不到
（配置是走环境变量传的，进程 cmdline 里只有 `python router.py`）：

```bash
kill $(lsof -nP -iTCP:8010 -sTCP:LISTEN -t)
```
