# Agent Team Testing Pattern — Tester + Fixer 协作模式

NeoMind 验证过的自动化测试架构。两个 agent 协作，一个发现问题一个修复，循环直到零缺陷。

---

## 架构

```
┌─────────────────────┐         ┌─────────────────────┐
│   REPL Tester Agent │         │   Fixer Agent       │
│   (Ground Truth)    │         │   (修复 + 回归)      │
│                     │         │                     │
│ 1. 启动真实终端      │  报告   │ 1. 读取失败报告      │
│    python3 main.py  │───────→│ 2. 读源码找根因      │
│ 2. 像人一样打字      │         │ 3. 修复代码          │
│ 3. 读LLM回复        │  确认   │ 4. 补充/更新unittest │
│ 4. 判断对错          │←───────│ 5. 跑全部unittest   │
│ 5. 写报告            │         │ 6. 报告修复结果      │
└─────────────────────┘         └─────────────────────┘
         │                               │
         └───── 循环直到 0 失败 ──────────┘
```

## 核心原则

1. **REPL Tester = 唯一真相来源**
   - 真实启动 `python3 main.py`
   - 通过 pexpect 驱动终端
   - 像真实用户一样发消息、输命令
   - 它说失败就是失败，不管unittest怎么说

2. **Fixer 必须同时做两件事**
   - 修复 REPL Tester 发现的 bug
   - 补充对应的 unittest 覆盖这个 bug
   - 跑全部 unittest 确保无回归

3. **Tester 不修代码，Fixer 不跑 REPL**

---

## REPL Harness 技术细节

文件：`tests/llm/repl_harness.py`

### 关键设计

```python
# pexpect 启动真实 REPL
child = pexpect.spawn('python3', ['main.py', '--mode', 'coding'],
                       env={'TERM': 'dumb'})  # 减少ANSI噪音

# 等待提示符 "> " 出现 = NeoMind 准备好了
child.expect(r'> ', timeout=30)

# 发送命令（即时返回，无LLM调用）
def send_command(cmd):
    drain_buffer()
    child.sendline(cmd)
    child.expect(r'> ', timeout=15)  # 等下一个提示符
    return clean_ansi(child.before)

# 发送聊天（等待LLM回复，最多90秒）
def send_chat(msg):
    drain_buffer()
    child.sendline(msg)
    child.expect(r'> ', timeout=90)  # LLM可能很慢
    return clean_ansi(child.before)
```

### 踩过的坑

| 问题 | 原因 | 解决 |
|------|------|------|
| 命令输出错位 | pexpect等到timeout才返回 | 改为等待 `> ` 提示符 |
| ANSI干扰 | prompt_toolkit输出控制序列 | `TERM=dumb` + clean_ansi() |
| Spinner干扰 | Thinking…动画字符混入输出 | 正则清除⠋⠙⠹等字符 |
| 测试隔离 | 权限规则持久化到磁盘影响unittest | 每次测试前清理磁盘状态 |

---

## 测试场景模板

```python
# Scenario: 验证某个功能
r = tester.send_command('/flags')           # 即时命令
tester.check("标志显示", 'AUTO_DREAM' in r)  # 断言

r = tester.send_chat('What is 2+2?')        # LLM调用
tester.check("数学计算", '4' in r)           # 断言
```

---

## 运行方式

```bash
# 跑 REPL 测试（ground truth）
python3 tests/llm/repl_harness.py

# 跑全部 unittest
python3 -m pytest tests/test_new_*.py tests/llm/ -v

# 跑快速验证
python3 -c "... (见 TESTING_GUIDE.md 第六部分)"
```

---

## 迭代记录

所有轮次的测试结果、修复内容、经验教训记录在：
`tests/llm/TEST_ITERATION_LOG.md`

---

## 经验总结

1. **先修 harness 再修代码** — 大部分"失败"其实是 harness 的时序问题
2. **TERM=dumb 是关键** — 消除 prompt_toolkit 的大部分终端控制序列
3. **命令和聊天分开处理** — 即时命令等15秒，LLM聊天等90秒
4. **每次 drain buffer** — 发命令前清空残留输出，防止错位
5. **磁盘状态影响测试** — 权限规则等持久化文件会污染 unittest
