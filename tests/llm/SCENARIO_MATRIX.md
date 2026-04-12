# NeoMind 完整测试场景矩阵 — 300+ 场景

## 测试分层

| 层级 | 测试方式 | 场景数 | LLM调用 | 耗时估计 |
|------|---------|--------|---------|---------|
| Tier 1: REPL | pexpect驱动真实终端 | ~100 | ✅ 真实 | ~15分钟 |
| Tier 2: API | Python直接调用agent API | ~120 | ✅ 真实 | ~10分钟 |
| Tier 3: Unit | pytest无LLM | ~100 | ❌ | ~1秒 |
| **总计** | | **~320** | | **~26分钟** |

---

## Tier 1: REPL 场景 (100个 — 真实终端交互)

### A. 命令系统 (30个)

**基础命令 (15个)**
| # | 场景 | 模式 | 验证内容 |
|---|------|------|---------|
| 001 | `/help` | coding | 显示所有命令列表 |
| 002 | `/help` | chat | chat模式也能显示 |
| 003 | `/help` | fin | fin模式也能显示 |
| 004 | `/flags` | coding | 显示14个特性标志 |
| 005 | `/flags AUTO_DREAM off` | coding | 关闭标志 |
| 006 | `/flags AUTO_DREAM on` | coding | 恢复标志 |
| 007 | `/doctor` | coding | 显示Python/API/Git/Services/Sandbox/Flags/Memory/Migration/Search |
| 008 | `/context` | coding | 显示消息数/Token数/进度条 |
| 009 | `/version` | coding | 显示版本号 |
| 010 | `/permissions` | coding | 显示当前权限模式 |
| 011 | `/cost` | coding | 显示费用信息 |
| 012 | `/stats` | coding | 显示统计信息 |
| 013 | `/dream` | coding | 显示AutoDream状态 |
| 014 | `/dream run` | coding | 手动触发整合 |
| 015 | `/debug` | coding | 切换调试模式 |

**模式切换 (5个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 016 | `/think` on | 切换thinking模式 |
| 017 | `/think` off | 切换回来 |
| 018 | `/brief on` | 启用简洁模式 |
| 019 | `/brief off` | 关闭简洁模式 |
| 020 | `/mode chat` → `/mode coding` | 模式切换 |

**会话管理 (10个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 021 | `/checkpoint test1` | 保存检查点 |
| 022 | 聊几轮 → `/rewind test1` | 回退到检查点 |
| 023 | `/rewind 2` | 回退2轮 |
| 024 | `/branch experiment` | 分叉对话 |
| 025 | `/snip 3` | 保存最近3条 |
| 026 | `/save test.md` | Markdown导出 |
| 027 | `/save test.json` | JSON导出 |
| 028 | `/save test.html` | HTML导出 |
| 029 | 退出 → `/resume` | 列出可恢复会话 |
| 030 | `/resume <name>` | 恢复会话+状态 |

### B. 工具调用 (25个)

**Bash工具 (8个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 031 | `运行 echo hello` | Bash基本执行 |
| 032 | `运行 pwd` | 获取当前目录 |
| 033 | `运行 ls -la` | 列出文件 |
| 034 | `运行 git status` | Git状态 |
| 035 | `运行 git branch` | Git分支 |
| 036 | `运行 python3 --version` | Python版本 |
| 037 | `运行 cat main.py | head -5` | 管道命令 |
| 038 | `运行 echo $PWD` | 环境变量 |

**Read工具 (5个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 039 | `读取 main.py 前10行` | 文件读取+行限制 |
| 040 | `读取 agent/config/base.yaml` | YAML文件读取 |
| 041 | `读取 pyproject.toml` | TOML文件读取 |
| 042 | `读取不存在的文件` | 错误处理 |
| 043 | `读取 README.md 然后总结` | 读取+分析 |

**Grep/Glob工具 (5个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 044 | `搜索所有包含class的.py文件` | Grep搜索 |
| 045 | `列出所有.yaml文件` | Glob模式 |
| 046 | `搜索main.py中import的数量` | 文件内搜索 |
| 047 | `找到所有test_开头的文件` | 测试文件查找 |
| 048 | `搜索TODO或FIXME注释` | 多模式搜索 |

**复合工具任务 (7个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 049 | `看看这个codebase是干啥的` | 多工具分析 |
| 050 | `main.py有多少行代码` | Bash(wc)+Read |
| 051 | `这个项目用了哪些Python包` | Read(requirements/pyproject) |
| 052 | `找到最大的.py文件` | Bash(find+sort) |
| 053 | `agent目录结构是什么` | LS/Bash(tree) |
| 054 | `对比两个config文件的区别` | Read+分析 |
| 055 | `检查有没有安全隐患` | 多文件分析 |

### C. LLM对话 (25个)

**基础对话 (5个)**
| # | 场景 | 模式 | 验证内容 |
|---|------|------|---------|
| 056 | 2+2=? | coding | 数学计算 |
| 057 | 日本首都 | coding | 知识问答 |
| 058 | Hello (English) | chat | 英文问候 |
| 059 | 你好 (Chinese) | chat | 中文问候 |
| 060 | 什么是ETF | fin | 金融知识 |

**上下文记忆 (10个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 061 | 设置名字Alice → 回忆 | 单轮记忆 |
| 062 | 设置3台服务器 → 回忆第2台 | 列表记忆 |
| 063 | 设置密码banana42 → 回忆 | 精确回忆 |
| 064 | 设置项目SuperApp+FastAPI → 回忆两项 | 多事实记忆 |
| 065 | 5轮对话 → 回忆第1轮内容 | 长程记忆 |
| 066 | 设置偏好(中文) → 回忆 | 中文上下文 |
| 067 | coding模式 → 设置事实 → 切chat → 回忆 | 跨模式记忆 |
| 068 | 纠正错误 → 验证更新 | 上下文更新 |
| 069 | 设置多个事实 → 逐一回忆 | 多事实检索 |
| 070 | 复杂指令(多步骤) → 执行 | 指令跟随 |

**代码生成 (5个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 071 | 写fibonacci函数 | 函数生成 |
| 072 | 写列表推导式 | 单行代码 |
| 073 | 写类(含__init__) | 类生成 |
| 074 | 写装饰器 | 高级语法 |
| 075 | 写单元测试 | 测试代码生成 |

**中文对话 (5个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 076 | 用中文解释Python | 中文技术解释 |
| 077 | 用中文写注释 | 中文代码注释 |
| 078 | 中英混合提问 | 混合语言 |
| 079 | 用中文分析代码 | 中文代码分析 |
| 080 | 用中文问金融问题 | 中文金融 |

### D. 团队/权限/安全 (20个)

**团队管理 (5个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 081 | `/team create` | 创建团队 |
| 082 | `/team list` | 列出团队 |
| 083 | `/team info` | 查看团队详情 |
| 084 | `/team delete` | 删除团队 |
| 085 | 创建→添加成员→删除 | 完整生命周期 |

**权限规则 (5个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 086 | `/rules` 空列表 | 初始状态 |
| 087 | `/rules add Bash allow npm test` | 添加规则 |
| 088 | `/rules` 显示规则 | 列表更新 |
| 089 | `/rules remove 0` | 删除规则 |
| 090 | 添加deny规则 → 验证阻止 | 规则执行 |

**安全检查 (5个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 091 | 尝试读取/dev/zero | 路径穿越拦截 |
| 092 | 尝试读取~/.bashrc | 受保护文件 |
| 093 | 尝试运行rm -rf | 危险命令检测 |
| 094 | 尝试curl|bash | Bash安全检查 |
| 095 | 尝试读取二进制文件 | 二进制检测 |

**其他功能 (5个)**
| # | 场景 | 验证内容 |
|---|------|---------|
| 096 | `/btw 2+2=?` | 旁路问题 |
| 097 | `/style` | 输出样式 |
| 098 | `/init` | 项目初始化 |
| 099 | `/ship` | Git工作流 |
| 100 | `/review` | 代码审查 |

---

## Tier 2: API 场景 (120个 — Python API直接调用)

### E. 安全系统 (30个)
| 范围 | 场景数 | 内容 |
|------|--------|------|
| 路径穿越 | 10 | 每种攻击向量各1: device, UNC, tilde, URL-encoded, unicode, backslash, case, glob, symlink, protected |
| Bash安全 | 10 | curl_pipe, ifs, proc, dd, eval, xargs, wget, mkfs, crontab, ssh_forward |
| 二进制检测 | 5 | PNG, PDF, ELF, ZIP, 文本文件 |
| 受保护文件 | 5 | .bashrc, .aws, .kube, .env, .ssh |

### F. 权限系统 (25个)
| 范围 | 场景数 | 内容 |
|------|--------|------|
| 6种模式 | 6 | 每种模式×Read/Write/Bash |
| 风险分类 | 5 | LOW/MEDIUM/HIGH/CRITICAL + 参数提升 |
| 规则引擎 | 5 | add/remove/match/glob/content_pattern |
| 拒绝追踪 | 3 | 连续拒绝/总拒绝/回退 |
| 权限解释 | 3 | Bash/Write/Edit解释文本 |
| 权限委托 | 3 | 通过邮箱请求权限 |

### G. 记忆系统 (20个)
| 范围 | 场景数 | 内容 |
|------|--------|------|
| 记忆选择 | 5 | <5条/=5条/>5条/缓存/回退 |
| 老化警告 | 4 | 1天/7天/30天/新鲜 |
| 分类法 | 4 | user/feedback/project/reference |
| Agent记忆 | 4 | 3作用域/快照/恢复/注入 |
| SessionNotes | 3 | 触发/提取/持久化 |

### H. 会话存储 (15个)
| 范围 | 场景数 | 内容 |
|------|--------|------|
| JSONL写入 | 3 | 消息/元数据/去重 |
| JSONL读取 | 3 | 轻量/完整/元数据 |
| 中断检测 | 3 | 用户最后/助手最后/工具未完成 |
| 子Agent侧链 | 3 | 写入/读取/隔离 |
| 导出格式 | 3 | Markdown/JSON/HTML |

### I. 压缩系统 (10个)
| 范围 | 场景数 | 内容 |
|------|--------|------|
| 微压缩 | 3 | 截断旧输出/保留新/阈值触发 |
| 渐进压缩 | 3 | 85%/90%/95%阶段 |
| 媒体剥离 | 2 | base64图片/长二进制 |
| 状态重注入 | 2 | 工具schema/活跃计划 |

### J. 工具接口 (10个)
| 范围 | 场景数 | 内容 |
|------|--------|------|
| isReadOnly | 2 | Read=true, Write=false |
| isDestructive | 2 | SelfEditor=true, Bash(rm)=true |
| isConcurrencySafe | 2 | Read=true, Bash=false |
| isOpenWorld | 2 | WebFetch=true, Read=false |
| interruptBehavior | 2 | Write=block, Bash=cancel |

### K. 提示组合 (10个)
| 范围 | 场景数 | 内容 |
|------|--------|------|
| 优先级链 | 4 | override>coordinator>agent>default |
| 缓存边界 | 2 | 存在/位置正确 |
| Token统计 | 2 | 节数/TOTAL |
| 上下文注入 | 2 | git/OS/date |

---

## Tier 3: Unit 场景 (100个 — 无LLM)

### L. 特性标志 (10个)
### M. 配置迁移 (7个)
### N. 错误恢复 (10个)
### O. Token预算 (10个)
### P. 停止钩子 (8个)
### Q. Swarm系统 (15个)
### R. 挫败检测 (10个)
### S. Skill系统 (10个)
### T. 沙箱系统 (10个)
### U. 协调器 (10个)

---

## 多Agent场景 (额外20个 — Tier 1)

| # | 场景 | 验证内容 |
|---|------|---------|
| 301 | Coordinator模式启动 | 系统提示正确 |
| 302 | Worker工具过滤 | 排除TeamCreate等 |
| 303 | Worker消息上限 | 500条截断 |
| 304 | Scratchpad创建/写入/读取 | 跨Worker共享 |
| 305 | Scratchpad清理 | 完成后删除 |
| 306 | 团队创建+添加成员 | 颜色分配 |
| 307 | 邮箱写入+读取 | 消息传递 |
| 308 | 邮箱已读标记 | 状态更新 |
| 309 | 共享任务队列添加 | 任务创建 |
| 310 | 共享任务队列领取 | 原子操作 |
| 311 | 任务完成标记 | 状态变更 |
| 312 | XML任务通知格式 | 结构正确 |
| 313 | Worker简单模式 | 只有Read/Write/Edit/Bash |
| 314 | Worker全模式(排除) | 排除内部工具 |
| 315 | 团队删除 | 清理所有资源 |
| 316 | 并发工具执行 | 安全工具并行 |
| 317 | 非安全工具串行 | 写工具串行 |
| 318 | 多轮Coordinator对话 | 4阶段完整流程 |
| 319 | Agent Memory 3作用域 | user/project/local隔离 |
| 320 | Agent Memory快照 | 创建+恢复 |
