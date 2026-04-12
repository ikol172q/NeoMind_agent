# Test Progress — 2026-04-07 Final Update

## Method
- tmux 真实终端测试（capture-pane 获取用户视角）
- Fixer + Tester 分离
- 每个 fix 后 retest 验证
- 零 harness，零 env var hacks

## Final Progress

| Phase | Scenarios | PASS | FAIL | WARN | Status |
|-------|-----------|------|------|------|--------|
| P0: Basic + Commands | 32 | 32 | 0 | 0 | DONE ✅ |
| P1: Tools + Security + Session | 42 | 41 | 1 | 0 | DONE ✅ |
| P2: CodeGen + Modes + Combos | 50 | 48 | 0 | 2 | DONE ✅ |
| P3a: Deep Security + Errors | 49 | 33 | 10 | 5 | DONE → fixed 7 |
| P3b: Retest + New | 38 | 33 | 2 | 3 | DONE → fixed 2 |
| P3c: UI + Security + Long Conv | 57 | 42 | 6 | 9 | DONE → fixed 5 |
| P3d: Coding cmds + Frustration | 46 | 32 | 5 | 5 | DONE → fixed 1 |
| P3e: Final Retest + Stress | 73 | 36 | 6 | 25 | DONE |
| **TOTAL** | **387** | **297** | **30** | **49** | |

**Pass rate: 77% (PASS only), 89% (PASS+WARN)**
**Zero crashes across all 387 scenarios**

## Bugs Summary: 35 found, 28 fixed

| # | Bug | Sev | Fixed |
|---|-----|-----|-------|
| 1 | 中文输入被误判为文件名 | HIGH | ✅ |
| 2 | 代码块缺换行 | LOW | LLM |
| 3 | 重复 tool_call 污染历史 | HIGH | ✅ |
| 4 | tool_call 关闭标签不一致 | MED | ✅ |
| 5 | content filter agentic loop 丢失 | HIGH | ✅ |
| 6 | JSON 未转义换行 | HIGH | ✅ |
| 7 | 注释 bash 块重匹配 | MED | ✅ |
| 8 | /think on/off 忽略参数 | MED | ✅ |
| 9 | thinking 块混入 tool_call | HIGH | ✅ |
| 10 | Traceback 暴露给用户 | MED | ✅ |
| 11 | /dev/zero LLM 绕过 | MED | NOTED |
| 12 | </tool_call> 泄漏 UI | LOW | ✅ |
| 13 | /deep 命令未注册 | HIGH | ✅ |
| 14 | 敏感文件返回 File not found | LOW | NOTED |
| 15 | /ETC/PASSWD 大写绕过 | HIGH | ✅ |
| 16 | cat ~/.ssh/id_rsa 未拒绝 | MED | ✅ |
| 17 | WebSearch 代替 Grep | MED | ✅ |
| 18 | /clear 说 "compacted" | LOW | ✅ |
| 19 | /verbose /hooks /arch 未注册 | MED | ✅ |
| 20 | 重复创建团队无错误 | LOW | ✅ |
| 21 | PARSE FAILED 边界 (4种) | HIGH | ✅ |
| 22 | system_prompt 无 setter | MED | ✅ |
| 23 | tilde 路径绕过安全 | HIGH | ✅ |
| 24 | Finance 模式工具执行 | HIGH | PARTIAL |
| 25 | "always allow" 不持久 | MED | ✅ |
| 26 | LLM 虚构工具名 | MED | ✅ |
| 27 | headless 不执行工具 | HIGH | ✅ |
| 28 | ~/.docker/config.json 可读 | HIGH | ✅ |
| 29 | /tmp 写入被阻止 (macOS symlink) | HIGH | ✅ |
| 30 | Edit 工具不修改文件 | HIGH | ✅ (同29) |
| 31 | /compact 丢失用户身份 | MED | ✅ |
| 32 | /stats 全显示 0 | LOW | ✅ |
| 33 | --system-prompt 被忽略 | MED | ✅ (setter) |
| 34 | /flags toggle 解析错误 | HIGH | ✅ |
| 35 | tool_call 格式变体 (doubled/XML) | HIGH | ✅ (parser) |

## Remaining Known Issues (7)

1. **--system-prompt headless 仍不完全生效** — setter 加了，但 headless_main 可能没正确应用
2. **tool_call UI 泄漏 (doubled tags)** — parser 已修但 UI filter 仍偶尔漏
3. **DeepSeek 格式变体** — XML/JSON 混合格式的 tool call 偶尔解析失败
4. **Bash 命令风险分级不足** — 所有 bash 都是 HIGH，应有 LOW/MEDIUM/HIGH/CRITICAL 区分
5. **Finance 模式工具执行** — 部分场景 raw XML 泄漏
6. **/code scan 等 coding 专属命令** — 大部分返回 "Unknown command"
7. **LLM echo 命令缺空格** — 中文 prompt 导致 `echo你好` (无空格)

## Stability Assessment

- **零崩溃**: 387 个场景，包括 30 轮压力测试
- **核心功能稳定**: 聊天、工具调用、slash 命令、session 管理、安全系统
- **LLM 非确定性**: ~10% 的 FAIL 是 DeepSeek 行为变异（工具名虚构、格式变体）
- **20-30 轮长对话**: 稳定，无退化
