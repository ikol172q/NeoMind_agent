# 2026-08-07 — 依赖库的 INFO 日志把 secret 写进磁盘 24.8 万行

## 症状

`/data/neomind/agent.log*` 四个轮转文件里 **248,596 行**含当前有效的 Telegram bot token 明文，
每 ~10 秒新增一条，已持续数月：

```text
02:45:35 [httpx] HTTP Request: POST https://api.telegram.org/bot<TOKEN>/getUpdates "HTTP/1.1 200 OK"
```

## 根因

**NeoMind 自己一行都没记过这个 token。** 是依赖库记的：

1. `httpx` 每个请求都在 **INFO** 级别打完整 URL；
2. Telegram Bot API 把 token 放在 **URL path** 里（`/bot<TOKEN>/getUpdates`）；
3. `agent/integration/telegram_bot.py` 的 `logging.basicConfig(level=INFO)` 让它 propagate 到
   root handler → stdout → supervisord 捕获 → `agent.log` 轮转落盘。

自查代码里有没有 `logger.info(token)` 永远查不到这个洞。**威胁模型必须包含"第三方库会记录
你传给它的东西"**。

## 修复（两层，缺一不可）

`agent/logging/secret_redaction.py`：

```python
install_secret_redaction()   # 紧跟在 basicConfig 之后调用
```

1. `httpx` / `httpcore` / `urllib3` / `telegram.*` 降到 WARNING —— 掐掉已知源头。
2. `SecretRedactingFilter` 挂到 **每个 handler** —— 兜住下一个想打 URL 的库。

### 坑 1：filter 必须挂 handler，不能挂 logger

```python
# WRONG — httpx 的 record 是从子 logger propagate 上来的，
# logger 级 filter 对 propagate 上来的 record 根本不生效
logging.getLogger().addFilter(SecretRedactingFilter())

# RIGHT
for h in logging.getLogger().handlers:
    h.addFilter(SecretRedactingFilter())
```

### 坑 2：改写 record 时必须同时清空 `record.args`

只改 `record.msg` 而留着 `args`，handler 格式化时会把 token 重新拼回去：

```python
record.msg = redact_secrets(record.getMessage())
record.args = ()          # ← 少这一行，脱敏等于没做
```

### 坑 3：`PIISanitizer.PATTERNS` 顺序敏感，宽正则会吃掉窄正则的形状

`sanitize()` 按插入顺序跑。Telegram token 的形状是 `<9~10位数字>:<35位字串>`，而 `ssn` 的
`\d{3}\d{2}\d{4}` 正好吃掉前面那段数字：

```text
输入:     <9位数字>:<35位密钥段>
错误输出: [REDACTED_SSN]:<35位密钥段>      ← 冒号后面的秘密整段还在
```

（本文刻意不写出完整形状的示例串——公开仓里任何 token 形状的字面量都会让 gitleaks
和 pre-commit 永久告警。测试里同理，`FAKE_TOKEN` 是拼接构造的。）

`telegram_bot_token` 必须排在 `ssn` **之前**。这个 bug 是被新写的测试抓到的，肉眼 review 没看出来。

另注：`PIISanitizer` 原有的 `api_key` 正则要求 `sk-` / `token_` 等厂商前缀，**匹配不到 Telegram
token**（它没有前缀）。别假设"已经有个 sanitizer 了"就等于覆盖。

## 验证方式（照抄）

不能只跑单测就宣布完成：

```bash
# 1. 双 venv 单测
.venv/bin/python -m pytest tests/test_secret_redaction.py tests/test_pii_sanitizer.py -q
~/.neomind_fin_venv/bin/python -m pytest tests/test_secret_redaction.py tests/test_pii_sanitizer.py -q

# 2. 重启后只统计"新增"日志段（旧日志本来就脏，全量 grep 无意义）
BASE=$(docker exec neomind-telegram sh -c 'wc -l < /data/neomind/agent.log')
docker restart neomind-telegram
docker exec neomind-telegram sh -c "tail -n +$((BASE+1)) /data/neomind/agent.log | \
  grep -ac --binary-files=text -E 'api\.telegram\.org/bot[0-9]'"     # 必须是 0

# 3. 对抗性验证：在容器里把 httpx 调回 INFO，证明第 2 层真的兜得住
docker exec neomind-telegram python -c "...install_secret_redaction(); \
  logging.getLogger('httpx').setLevel(logging.INFO); ..."
```

**「重启后没有 token 行」单独不算证据** —— bot 挂了也是 0 行。必须同时证明它 LIVE
（日志里的 `@bot is LIVE` + `docker ps` healthy）。

## 泄露定级：先分 tracked / untracked 再喊火

本次结论是**本地泄露，非公开泄露**，判定依据：

```bash
git grep -I -c -E "[0-9]{8,10}:[A-Za-z0-9_-]{35}" HEAD   # HEAD 树 → 0
git grep -I -l -E "..." ; git check-ignore -v .env       # 工作区 → 0；.env 已 ignore 且 untracked
```

进了 git = CFOR 永久公开，必须旋转 + 洗历史；只在本地 600 文件里 = 该修该旋转，但不是 P0 火警。

### 扫描本身的两个假阴性

- `grep -I` 会把含中文的日志当 binary **跳过** → 必须用 `--binary-files=text` / `grep -a`。
- **docker 命名卷不在 host 路径下**。扫 `~/.neomind` 扫不到 `/data/neomind`。先
  `docker inspect <c> --format '{{range .Mounts}}...'` 列全挂载点，再逐个扫。第一轮就是漏了
  这个，差点把 24.8 万行的洞报成"扫不到，无法复现"。
