# NeoMind 自我进化计划 — 统一索引

> 创建日期: 2026-03-28
> 目的: 避免6份计划文档间的重复与冲突，提供单一入口点
> 总计: ~5940行, 6份文档

---

## 文档关系图

```
                    ┌─────────────────────────┐
                    │  enhanced-evolution-plan │ ← 核心文档 (v4.0)
                    │  数据采集 + 跨人格智能   │   NeoMind 自检从这里开始
                    │  赚钱路线图 + 18个#TAG   │
                    └──────────┬──────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
   ┌──────────────┐  ┌─────────────────┐  ┌──────────────────┐
   │ strategy-v2  │  │ integration-plan│  │ addendum-v4.1    │
   │ 研究 + #TAG  │  │ 17模块集成      │  │ 运维 + 合规 + LLM│
   │ 论文依据     │  │ 5层架构 + 路线图│  │ 无关抽象层       │
   └──────┬───────┘  └────────┬────────┘  └──────────────────┘
          │                   │
          ▼                   │
   ┌──────────────┐           │
   │ strategy-v1  │ ← 被v2取代│
   │ (参考留存)   │           │
   └──────────────┘           │
                              ▼
                    ┌──────────────────┐
                    │ implementation   │
                    │ 工程实施细节     │
                    │ (代码级方案)     │
                    └──────────────────┘
```

---

## 文档职责划分 (读哪个?)

| 要找什么? | 读这个文档 | 行范围 |
|-----------|-----------|--------|
| **NeoMind 是什么? 总体目标?** | `enhanced-evolution-plan.md` §0-§1 | 1-80 |
| **数据采集子系统设计** | `enhanced-evolution-plan.md` §2-§4 | 80-500 |
| **跨人格智能共享管线** | `enhanced-evolution-plan.md` §5 | 500-650 |
| **赚钱路线图 (4阶段)** | `enhanced-evolution-plan.md` §6 | 650-800 |
| **18个进化标签 (#TAG)** | `enhanced-evolution-plan.md` §7 | 800-1000 |
| **自检协议 + 待用户决定的问题** | `enhanced-evolution-plan.md` §8-§9 | 1000-1300 |
| **17个模块各自做什么?** | `integration-plan.md` §1-§2 | 1-400 |
| **模块间依赖关系** | `integration-plan.md` §3 | 400-550 |
| **Docker部署拓扑** | `integration-plan.md` §4 | 550-650 |
| **8周实施路线图** | `integration-plan.md` §5 | 650-900 |
| **所有论文/研究汇总表** | `integration-plan.md` §6 | 900-1060 |
| **研究论文详细分析** | `strategy-v2.md` 全文 | 1-1100 |
| **Git-Gated 自编辑流程** | `implementation.md` §1 | 1-300 |
| **Prompt自动调优** | `implementation.md` §2 | 300-550 |
| **技能锻造 (SkillForge)** | `implementation.md` §3 | 550-800 |
| **Mac Studio 资源管理** | `addendum-v4.1.md` §1 | 1-100 |
| **法律合规矩阵 (7数据源)** | `addendum-v4.1.md` §2 | 100-250 |
| **零停机重启 (4级)** | `addendum-v4.1.md` §3 | 250-380 |
| **LLM无关抽象层** | `addendum-v4.1.md` §4 | 380-520 |
| **24/7 自主运行循环** | `addendum-v4.1.md` §5 | 520-690 |

---

## 权威来源规则 (避免冲突)

当同一主题在多个文档出现时，以下文档为权威来源:

| 主题 | 权威文档 | 其他文档引用方式 |
|------|---------|-----------------|
| 数据采集架构 | enhanced-evolution-plan | 其他文档只引用结论 |
| 模块接口定义 | integration-plan | 其他文档只引用模块名 |
| 研究论文数据 | strategy-v2 (已校正) | 其他文档引用时标注来源 |
| 代码实现细节 | implementation | 其他文档只描述意图 |
| 运维/合规/LLM | addendum-v4.1 | 其他文档不重复这些内容 |
| 总体目标/自检 | enhanced-evolution-plan | 所有文档开头引用此定义 |

---

## 已知重复区域 (待未来合并)

以下内容在多个文档中有不同程度的重复，未来维护时应合并:

1. **Ebbinghaus遗忘曲线公式** — 出现在 strategy-v2 + integration-plan + enhanced-plan
   → 权威: strategy-v2 (含FOREVER改进公式)
2. **SkillRL双技能库** — 出现在 strategy-v2 + integration-plan
   → 权威: strategy-v2 (含完整论文分析)
3. **进程架构图** — 出现在 integration-plan + addendum-v4.1 + enhanced-plan
   → 权威: integration-plan §4 (含完整 supervisord 配置)
4. **免费API列表** — 出现在 enhanced-plan + addendum-v4.1
   → 权威: enhanced-plan §3 (含完整优先级排序)

---

## 研究校正记录

| 日期 | 原始内容 | 校正后 | 影响文档 |
|------|---------|--------|---------|
| 2026-03-28 | SkillRL "10-20% token compression" | "10-20x compression" (数量级非百分比) | strategy-v2, integration-plan |
| 2026-03-28 | PreFlect "10-15% improvement" | "11-17% (实测11.68-17.14%)" | integration-plan |
| 2026-03-28 | s6-overlay "<1MB内存" | "极低内存占用(具体数值未验证)" | integration-plan |

---

## 文档版本跟踪

| 文档 | 创建 | 最后修改 | 版本 |
|------|------|---------|------|
| enhanced-evolution-plan.md | 2026-03-28 | 2026-03-28 | v4.0 |
| self-evolution-strategy-v2.md | 2026-03-28 | 2026-03-28 | v2 (SkillRL已校正) |
| self-evolution-integration-plan.md | 2026-03-28 | 2026-03-28 | v1 (PreFlect+s6已校正) |
| self-evolution-implementation.md | 2026-03-28 | 2026-03-28 | v1 |
| evolution-addendum-v4.1.md | 2026-03-28 | 2026-03-28 | v4.1 |
| self-evolution-strategy.md | 2026-03-28 | 2026-03-28 | v1 (被v2取代,保留参考) |

---

## NeoMind 自读指引

当 NeoMind 需要理解自身进化计划时，按以下顺序读取:

1. **本文件** (`PLAN-INDEX.md`) — 了解文档结构和去哪找什么
2. **`enhanced-evolution-plan.md`** §0 自检协议 — 执行自检
3. **根据需要** 查阅具体文档的具体章节 (参考上方表格)
4. **不要** 从头到尾读所有文档 — 按需查阅，节省 token
