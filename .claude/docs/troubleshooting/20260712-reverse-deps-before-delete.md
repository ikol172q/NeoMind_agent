# 2026-07-12 — 按"内容重复"删模块，断了 tracked 代码的 import

**WRONG** 8 个 untracked fin 模块因"与 dashboard 副本内容一致(仅 import 路径不同)"被直接 rm —— 但 tracked 的 `dashboard_server.py` + `scheduler/{api,core}.py` 还 import 着它们，agent 立即断。审计时还把 `workflow/audit.py` 按首个命中("字符串列表")整文件定性，漏了深处 4 个真 import；fleet/ 再漏 2 处。

**RIGHT**
- 删/移模块前：`git grep -lE "import <mod>|finance\.<mod>"` 查 **tracked** 反向依赖；有人用=先迁移引用者再删。
- 审计每个命中文件逐个读上下文（eager/lazy 也要分）；批量改写后全仓残留 grep（含 fleet/ workflow/ scripts/ cli/）清零才算完。
- 高风险删除先 cp 到 scratchpad（本次靠备份零损失回滚）。

**WHY** 删除的安全性取决于反向依赖图而非文件内容；"内容重复"≠"无人依赖"。
