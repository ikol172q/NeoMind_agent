# NeoMind vs claurst + claudecode — Gap Analysis & Improvement Plan

**Date:** 2026-04-05 (v2 — cross-verified)
**Sources:**
- claurst (Kuberwastaken): Rust reimplementation, 12 crates, ~30K LOC
- claudecode (soongenwong): Rust MVP, 16 tools, hooks system, MCP support

## Review Notes (v2 审计修正)

**审计发现的问题：**
1. Auto-compact代码已存在(context_collapse.py+circuit_breaker概念)但未接入agentic loop → 改为**接入问题**而非**缺失问题**
2. 遗漏了Plugin系统 → 新增为HIGH
3. 遗漏了MCP资源浏览命令 → 新增为MEDIUM  
4. CLI参数优先级过高 → NeoMind的46个slash命令比CLI参数更重要，降为MEDIUM
5. Session格式不需要统一 → 当前JSONL+JSON并存是灵活设计，移除此项
6. Headless模式是其他功能的**前置依赖** → 必须最先实现

**NeoMind的独特优势（不要丢失）：**
- 46个命令 vs claurst~20/claudecode~30
- 6种权限模式 vs 两者3种
- 3-personality系统：独有
- Finance模块+自进化+记忆系统：独有

---

## Part 1: NeoMind已有但需要改进的功能

### 1.1 Streaming Output Quality (HIGH — 刚修过但仍需加强)

**claurst做法:** ratatui全屏TUI，工具状态独立渲染区域，spinner不与内容混合
**claudecode做法:** Markdown解析器+syntect语法高亮，spinner和内容分层

**NeoMind现状:** prompt_toolkit + 手动ANSI控制。刚修了spinner冲突但架构不够clean。

**改进点:**
- [ ] 工具执行状态独立显示区域（不和LLM输出混合）
- [ ] 代码块语法高亮（目前是纯文本）
- [ ] 工具输出折叠/展开（目前全部展开）
- [ ] 清晰的视觉边界：thinking区 / 工具区 / 回答区

### 1.2 Permission System (MEDIUM)

**claurst做法:** 3层模型（Mode + Handler + Request），InteractivePermissionHandler用TUI弹窗
**claudecode做法:** 3种模式（ReadOnly/WorkspaceWrite/DangerFullAccess），交互式边界提升

**NeoMind现状:** 6种模式+规则引擎+风险分类，功能比两者都强。但交互体验差——permission弹窗是纯文本。

**改进点:**
- [ ] Permission弹窗格式化（像claurst的TUI弹窗）
- [ ] 显示风险级别和解释（已有explain_permission，但未在弹窗中使用）

### 1.3 Auto-Compaction (MEDIUM)

**claurst做法:** 90%阈值触发，保留最近10条消息，API调用做摘要，3次失败断路器
**claudecode做法:** /compact命令，手动控制

**NeoMind现状:** 有ContextCompactor + micro_compact + context_collapse。功能齐全但触发逻辑简单。

**改进点:**
- [ ] 添加自动触发（像claurst的90%阈值）
- [ ] 添加断路器（3次失败后停止尝试）
- [ ] 保留最近N条消息不压缩

### 1.4 Session Persistence (MEDIUM)

**claurst做法:** 完整JSON序列化，版本化schema，可恢复
**claudecode做法:** JSON session文件，/export + /session命令

**NeoMind现状:** 有SessionWriter(JSONL) + save_session(JSON) + /resume。但两种格式并存不统一。

**改进点:**
- [ ] 统一session格式（JSONL或JSON，不要两种）
- [ ] 添加schema版本号（方便未来迁移）
- [ ] /session list/load/save 命令（像claudecode）

### 1.5 Tool Parser Robustness (HIGH — 刚修了一个)

**NeoMind现状:** 刚修了`\n?`问题。但还有更多LLM输出变体需要处理。

**改进点:**
- [ ] 处理更多代码块变体：` ```Bash `（大写）、` ``` bash `（空格）
- [ ] 处理LLM在代码块前输出文字的情况（"让我运行：```bash..."）
- [ ] 更好的tool_call JSON解析（处理单引号、尾逗号等）

---

## Part 2: NeoMind缺失的功能

### 2.1 Hooks System (HIGH — claudecode有，NeoMind没有)

**claudecode实现:** PreToolUse/PostToolUse shell命令钩子
- 通过环境变量传递tool信息
- Exit code控制：0=允许，2=拒绝，其他=警告
- 输出追加到工具结果

**NeoMind现状:** 有integration_hooks（内部Python钩子），但没有用户可配置的shell钩子。

**实现计划:**
- [ ] 在settings.json支持hooks配置
- [ ] PreToolUse: 工具执行前运行shell命令，可阻止
- [ ] PostToolUse: 工具执行后运行shell命令，可追加反馈
- [ ] 通过环境变量传递：HOOK_TOOL_NAME, HOOK_TOOL_INPUT, HOOK_TOOL_OUTPUT

### 2.2 CLI Argument Parsing (HIGH — claurst有完整的clap，NeoMind用argparse)

**claurst实现:** clap with derive macros，支持：
- `-p/--print`：单轮模式（stdin→stdout）
- `--resume`：恢复会话
- `--max-turns`：最大轮数
- `--system-prompt/-s`：自定义系统提示
- `--append-system-prompt`：追加系统提示
- `--no-claude-md`：禁用CLAUDE.md
- `--output-format`：text/json
- `--verbose/-v`：详细模式
- `--mcp-config`：MCP配置文件
- `--no-auto-compact`：禁用自动压缩
- `--dangerously-skip-permissions`：跳过权限
- `--dump-system-prompt`：导出系统提示
- `--cwd`：工作目录

**NeoMind现状:** 简单的argparse：`--mode`, `--version`。大量功能缺失。

**实现计划:**
- [ ] 添加 `-p/--print` 单轮模式
- [ ] 添加 `--resume` 恢复会话
- [ ] 添加 `--system-prompt` 自定义提示
- [ ] 添加 `--output-format json` JSON输出
- [ ] 添加 `--max-turns` 最大轮数
- [ ] 添加 `--verbose` 详细模式
- [ ] 添加 `--cwd` 工作目录
- [ ] 添加 `--mcp-config` MCP配置

### 2.3 Headless/Print Mode (HIGH — 两个资源都有)

**claurst实现:** `--print`标志，单轮查询输出到stdout，无TUI
**claudecode实现:** 一次性prompt模式，可选JSON输出

**NeoMind现状:** 只有交互模式，不支持管道/脚本使用。

**实现计划:**
- [ ] `python main.py -p "What is 2+2?"` → 直接输出到stdout
- [ ] `echo "fix the bug" | python main.py -p` → stdin管道
- [ ] `--output-format json` → JSON格式输出（供其他程序解析）
- [ ] 非交互模式使用AutoPermissionHandler

### 2.4 Git Integration Commands (MEDIUM — claudecode有更多)

**claudecode实现:**
- `/branch list|create|switch`
- `/worktree list|add|remove`
- `/commit [message]`（带hooks）
- `/commit-push-pr`
- `/pr [context]`
- `/issue [context]`

**NeoMind现状:** 有`/git`, `/diff`, `/ship`。但缺少branch管理和worktree。

**实现计划:**
- [ ] 增强`/git`支持branch子命令
- [ ] 添加`/worktree`命令
- [ ] 增强`/ship`支持PR创建

### 2.5 Model Aliases (LOW — 两个都有)

**claurst/claudecode:** `opus`, `sonnet`, `haiku`简写

**NeoMind现状:** 需要输入完整模型名。

**实现计划:**
- [ ] `/model opus` → 解析为完整模型名
- [ ] `/model sonnet` → deepseek-chat的别名

### 2.6 CLAUDE.md / CLAW.md Auto-Discovery (MEDIUM)

**两个资源:** 自动加载项目根目录的指导文件

**NeoMind现状:** 有`.neomind/project.md`通过`/init`生成，但不自动加载到系统提示。

**实现计划:**
- [ ] 启动时自动查找`.neomind/project.md`或`NEOMIND.md`
- [ ] 将内容注入系统提示（像CLAUDE.md）

### 2.7 Syntax Highlighting for Code Blocks (MEDIUM)

**claurst:** syntect库
**claudecode:** syntect + pulldown_cmark

**NeoMind现状:** 代码块显示为纯文本。

**实现计划:**
- [ ] 使用Python的`pygments`库对代码块做语法高亮
- [ ] 在终端中用ANSI颜色渲染

### 2.8 Cost Tracking Display (LOW — claurst更完善)

**claurst实现:** 嵌入式模型定价，per-message成本，session总计

**NeoMind现状:** 有TokenBudget但不显示USD成本。

**实现计划:**
- [ ] 添加DeepSeek定价数据
- [ ] 在`/cost`命令中显示USD估算

---

## Part 3: NeoMind的独特优势（保持并增强）

这些是NeoMind有但两个资源都没有的：

| 功能 | NeoMind | claurst | claudecode |
|------|---------|---------|-----------|
| 3种personality模式 | ✅ coding/chat/fin | ❌ | ❌ |
| Finance模块 | ✅ 完整金融流水线 | ❌ | ❌ |
| Self-evolution | ✅ AutoDream+SkillForge | ❌ | ❌ |
| Universal Search | ✅ 10+搜索源 | ❌ | ❌ |
| Obsidian Vault | ✅ 长期记忆 | ❌ | ❌ |
| Frustration Detection | ✅ 中英文 | ❌ | ❌ |
| Memory Selector (LLM选择) | ✅ | ❌ | ❌ |
| Memory Taxonomy (4类型) | ✅ | ❌ | ❌ |
| Swarm/Team系统 | ✅ 邮箱+任务队列 | ❌ | ❌ |
| Export多格式 | ✅ MD/JSON/HTML | ❌ JSON | JSON |
| 46个CLI命令 | ✅ | ~20 | ~30 |

---

## Part 4: 实施优先级（v2 修正）

### Phase 0: System Prompt & Config Polish（最高优先级）— 没有这个其他都白做

NeoMind加了46个新功能，但system prompt不知道它们存在。LLM不知道自己有什么工具和命令，就不会用。

**必须做10轮以上打磨：**

1. **更新3个personality的system prompt**
   - coding.yaml: 告诉LLM它有52个工具（列出新增的9个），46个命令（列出新增的17个），安全系统（9种路径检查），权限系统（6种模式）
   - chat.yaml: 更新可用命令列表，告诉LLM它有记忆系统、会话管理
   - fin.yaml: 更新金融工具说明，告诉LLM它现在用DeepSeek

2. **更新工具使用指南**
   - 告诉LLM什么时候用`<tool_call>`格式，什么时候用```bash格式
   - 明确每个新工具的用途和参数
   - 安全工具说明（哪些路径被保护，哪些命令被拦截）

3. **更新命令列表**
   - 把17个新命令加入prompt中的"可用命令"部分
   - 包括/checkpoint、/rewind、/flags、/dream、/resume、/branch、/snip、/brief、/init、/ship、/btw、/doctor、/style、/rules、/team、/load、/transcript

4. **更新行为指导**
   - 告诉LLM它有错误恢复能力（context overflow时会自动compact）
   - 告诉LLM它有token budget（不要生成过长输出）
   - 告诉LLM它有挫败检测（用户生气时要更谨慎）

5. **参考Claude Code的prompt风格**
   - 从mehmoodosman/nirholas的system prompt中学习结构
   - 工具描述方式、安全规则写法、行为约束格式

6. **10轮打磨循环**
   - 改prompt → 用NeoMind聊天 → 观察LLM是否正确使用新功能 → 修正prompt → 重复
   - 每种personality至少3轮单独测试
   - 最后1轮三种模式混合测试

### Phase 1: 基础能力补齐（本周）— 阻塞性依赖
1. ~~bash解析`\n?`~~ ✅ 已完成
2. **Headless/Print模式**（-p标志）— 这是CI/CD和管道使用的前置条件
   - `python main.py -p "What is 2+2?"` → stdout输出
   - `echo "fix bug" | python main.py -p` → stdin管道
   - `--output-format json` → JSON输出
   - 非交互模式自动审批读操作，拒绝写操作
3. **Auto-compact接入agentic loop** — 代码已存在(context_collapse.py)，需2行接入
4. **Tool Parser更多变体** — ` ```Bash `大写、` ``` bash `空格、无闭合标记

### Phase 2: 用户可扩展性（下周）
5. **用户可配置Hooks系统** — PreToolUse/PostToolUse shell命令
   - settings.json配置 → shell命令 → 环境变量传参 → exit code控制
   - 参考claudecode hooks.rs实现（~100行核心代码）
6. **Plugin系统基础** — 动态加载外部工具
   - Plugin发现：`~/.neomind/plugins/` 目录扫描
   - Plugin注册：加入ToolRegistry
   - Plugin命令：`/plugin list|install|remove`
7. **NEOMIND.md自动发现** — 启动时加载项目指导文件到系统提示

### Phase 3: 体验提升（两周内）
8. **代码块语法高亮**（pygments） — 目前代码块是纯文本
9. **工具输出折叠/展开** — 长输出默认折叠，`/expand`展开
10. **MCP资源浏览命令** — `/mcp list|browse`
11. **CLI参数增强** — --resume, --system-prompt, --verbose, --cwd, --max-turns
12. **Model别名** — `/model opus` → 解析为完整名
13. **成本显示（USD）** — DeepSeek定价表 + /cost命令显示

### Phase 4: 架构优化（一个月内）
14. **工具状态独立渲染区域** — thinking/工具/回答三区分离
15. **Permission弹窗美化** — 格式化显示风险级别+解释
16. **Git命令扩展** — /branch, /worktree, /stash
17. **更多tool_call解析变体** — 处理各种LLM输出格式怪癖

### 不实施的项目（审计后移除）
- ~~Session格式统一~~ — 当前JSONL+JSON并存是灵活设计，不需要统一
- ~~CLI参数作为HIGH~~ — 降为Phase 3，NeoMind的slash命令已经比竞品丰富
