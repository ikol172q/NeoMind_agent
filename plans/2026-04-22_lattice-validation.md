# Insight Lattice · Validation + Visualization Plan
_Created 2026-04-22. Supersedes the D4-phase viz hints in 2026-04-20_insight-lattice.md._

## 1 · User concerns → solutions matrix

| # | User concern | Root cause | Solution (where + how) |
|---|---|---|---|
| Q1 | AAPL 一家独大 | watchlist 只有一个 ticker，输入面窄 | **非代码修复**：加 watchlist；可选 V2 给 L3 prompt 加 ticker-diversity hint |
| Q2 | 中英混合输出 | prompt 固定英文 | V3：spec.py 加 `output_language`，narrative / call prompt 改读配置 |
| Q3 | 更好的可视化 | drilldown 只有文字，many-to-many 关系看不见 | V2 交付 `/api/lattice/graph` + V3 交付 SVG viz + panel |
| Q4 | 每层 item 数量控制 | 各层硬编码 / 分散在 YAML/Python | V2：spec.py 集中暴露 `MAX_CALLS / MAX_CANDIDATES / min_members`，YAML 加 `layer_budgets:`，lvl pipeline 读它 |
| Q5 | LLM vs algorithm 角色 | 文档 in docstring，用户看不见 | V2：graph edge 带 `computation.method`，V3：节点 shape + 边 style 按 `provenance.computed_by` 编码 |
| C1 | 算法结构 → 实现 100% 正确 | 常量/公式隐式分散在代码里 | **V1** `agent/finance/lattice/spec.py` 单一真相源 + L1 contract 测试 |
| C2 | 可视化 → 算法&结果 100% 映射 | 前端可能撒谎/漂移 | **V3** L5: DOM snapshot + 视觉编码测试 + click→panel computation 字段对账 |
| C3 | 每次迭代都 validate | 缺 fixture、缺精确数字锁、judge 只看质量不看结构 | **V4** L6: fixture 锁 `expected_weights.json` + judge 基线 regression + pre-commit/CI hook |

## 2 · 不可违反的契约

1. **单一真相源**：所有算法常量（severity_bonus、MMR λ、enum）从 `spec.py` 读；任何其他地方出现硬编码 = bug
2. **数据流守恒**：L0 → L1 → (L1.5 并行) → L2 → L3；L1.5 不进 L3；不因可视化便利而伪造层间连接
3. **viz 只渲染，不计算**：所有数学由 `/api/lattice/graph` 算完后随 `computation` 字段下发；前端禁止重算 Jaccard
4. **每种 drift 对应一个 deterministic 报错**：改了常量→L1 红；改了公式→L2 红；改了结构→L3 红；改了 graph→L4 红；改了 viz→L5 红；改了 prompt→L6 红

## 3 · 验证层次（6 层，每层抓一类 bug）

| 层 | 文件 | 抓的 bug 类 |
|---|---|---|
| L0 | `agent/finance/lattice/spec.py` | —（规范本身，不是测试） |
| L1 | `tests/test_lattice_spec_contract.py` | 常量/枚举与 spec 漂移 |
| L2 | `tests/test_lattice_formulas.py` | 公式实现错误（参数化 + hypothesis 属性测试） |
| L3 | `tests/test_lattice_endpoint_coherence.py` | `/obs` `/themes` `/calls` `/graph` 互不对齐 |
| L4 | `tests/test_lattice_graph_algorithm.py` | graph edge 的 computation 撒谎（recompute 不匹配） |
| L5 | `tests/test_web_lattice_viz.py` | viz DOM 漏节点/错编码，click panel 显示的数字 ≠ graph |
| L6 | `tests/test_lattice_drift.py` + `tests/lattice_fixtures/` | 迭代里算法/prompt 偷偷改了结果 |

## 4 · 分阶段交付（每阶段独立 commit + checkpoint）

### V1 · Spec + formula-level validation （backend only, 低风险）
**Work items**:
1. `agent/finance/lattice/spec.py` — 所有常量 / 公式 / 枚举集中
2. 重构 `themes.py` / `calls.py` 从 spec 导入，删除本地重定义
3. `tests/test_lattice_spec_contract.py` (L1, ~6 tests)
4. `tests/test_lattice_formulas.py` (L2, 参数化 + `hypothesis` 属性测试 ~500 examples)
5. `pyproject.toml` 加 pytest markers (`lattice_fast`, `lattice_slow`, `lattice_drift`)
6. `Makefile` 加 validation targets

**Checkpoint V1**:
- [ ] L1 + L2 全绿
- [ ] 现有 64 个 lattice 测试无回归
- [ ] `make validate-algorithm-only` 可独立跑
- [ ] spec.py 内所有常量值与当前 production 代码完全一致（不是重新拍脑袋的数字）

### V2 · Graph endpoint + coherence validation
**Work items**:
1. `agent/finance/lattice/graph.py` builder（`build_graph(payload) → {nodes, edges}`）
2. `/api/lattice/graph?project_id=X` endpoint in router.py
3. `tests/test_lattice_endpoint_coherence.py` (L3)
4. `tests/test_lattice_graph_algorithm.py` (L4 — 重算每条边的 Jaccard 对账)
5. Frontend TypeScript types for `GraphPayload`

**Checkpoint V2**:
- [ ] `/api/lattice/graph` 返回的 nodes 数 = 各层之和（layer-wise 逐层对账）
- [ ] 每条 membership 边 `computation.detail.final` == spec.py 公式 recompute
- [ ] 每条 grounds 边对应 `call.grounds` 里存在
- [ ] Provenance 枚举全在 `spec.PROVENANCE_KINDS` 里
- [ ] 前端 TS 类型严格模式编译通过

### V3 · Interactive viz + L5 validation
**Work items**:
1. `web/src/components/widgets/LatticeGraphView.tsx` — 4-列 SVG
2. `web/src/components/widgets/LatticeTracePanel.tsx` — side panel
3. DigestView 加第 4 种模式 "Trace"
4. 视觉编码：node shape (rect / diamond / diamond+✓) × 边 style (solid / dashed / dashed+shield)
5. `tests/test_web_lattice_viz.py` (L5 Playwright)
6. DOM 结构快照：每个 graph node 都有对应 `[data-node-id="..."]`

**Checkpoint V3**:
- [ ] 点任一 node → panel 显示 id/tags/provenance
- [ ] 点任一边 → panel 显示 computation 字段里的精确数字
- [ ] provenance=llm+validator 节点必须渲染为菱形+盾
- [ ] 没有 graph 里没有的 DOM 元素（零幽灵）

### V4 · Drift detection + L6
**Work items**:
1. `tests/lattice_fixtures/scenario_{empty,thin,mid,rich,iv_heavy}/` — 每个场景锁死 input + expected_weights.json + graph.ref.json
2. Fixture 生成脚本 `tools/eval/pin_lattice_fixtures.py`（一次性运行）
3. `tests/test_lattice_drift.py` — fixture regression + judge baseline
4. DOM snapshot tests with mocked graph
5. `.git/hooks/pre-commit` 加 `lattice_fast` 校验
6. CI nightly 跑 `lattice_drift`

**Checkpoint V4**:
- [ ] 故意改 `SEVERITY_BONUS[warn]` 0.85→0.80 → fixture 测试精确报"这 N 条边的 weight 变了"
- [ ] Judge 基线测试打印当前分数，与 2026-04-21 归档对比
- [ ] pre-commit 能在 30 秒内跑完 lattice_fast

## 5 · Checkpoint protocol（每阶段边界）

每个阶段完成后，我（Claude）**自动**执行：

1. **运行完整验证套件**：`make validate-algorithm-only`（V1/V2）或 `make validate-lattice`（V3/V4）
2. **逐条核对 checkpoint 表**：上面每个 [ ] 都必须 ✅
3. **反检对本计划的契约**（§2）是否依然成立
4. **生成 checkpoint 报告**：包括测试数、耗时、覆盖的 edge case 数
5. **commit 当前阶段**（消息含 checkpoint 编号）
6. **报告给用户**：在进入下一阶段前摘要已完成/未完成/有争议

如果任一 checkpoint 失败：**停止**，不推进下一阶段，回复用户讨论。

## 6 · 回滚策略

- 每阶段独立 commit，可 `git revert` 单独回退
- V1 不改任何行为，只加校验 → 可随时回退
- V2 新加 endpoint 不影响现有 → 可随时回退
- V3 frontend 加新 mode，默认不激活 → 可随时回退
- V4 测试层 → 可随时回退

## 7 · 不做的事

- **不做** 算法本身的改动（性能优化、新生成器、新打分）。这个 plan 只管"把现有算法锁住 + 让它可视化"
- **不做** LLM 迭代（prompt tuning）。基线由 V4 judge drift 守护；主动改 prompt 是单独的工作
- **不做** 历史 trace 持久化。trace 仅实时反映当前 cache；要历史需要数据库，超范围
- **不做** n=5+。V1 验证 n=3/n=4 的 YAML 切换已覆盖；更多层是 D6 之后的事
