# Reference: 主要矛盾 / Primary contradiction

**Source**: 毛泽东《矛盾论》(1937年8月)，《毛泽东选集》第一卷
- 原文镜像: https://www.marxists.org/chinese/maozedong/marxist.org-chinese-mao-193708.htm
- 光明网《毛选》分页版: https://theory.gmw.cn/2012-09/25/content_5201761.htm

**Synthesized**: 2026-05-02 from full verbatim 原文 (user-paste verified)
+ 后世教科书注解 (multiple Chinese govt / 知乎 / 党史研究 sources via web search).

---

## 为什么把它放进 references

NeoMind references 已有:
- `first-principles.md` — 单点拆到 substrate
- `karpathy-2025-12-tweet.md` — 单点 surface assumption
- `karpathy-skills-2026.md` — 单点 falsifiability
- `prompt-design-philosophy.md` — pyramid template 综合上 3 项

这 4 条都解决 **"如何把单个 claim 做对"**。但当 task 牵涉**多个并存问题**时，缺一条优先级框架——用户在 2026-05-02 session 多次现场提醒"抓主要矛盾、别钻牛角尖、最小可工作版本先 ship"，正是这条 gap。

矛盾论提供**多问题排队的优先级筛子**：哪个先动 / 哪个让位 / 何时让位转换。

---

## 两个最容易混淆的概念（先 clarify）

| 维度 | 主要矛盾 vs 次要矛盾 | 矛盾的主要方面 vs 次要方面 |
|---|---|---|
| **比较对象** | 多个矛盾之间 | 同一矛盾内部的两方 |
| **决定什么** | 事物**发展进程**——先动哪个 | 事物**性质**——这事是黑还是白 |
| **典型场景** | 复杂任务多个 sub-problem 排队 | 单个问题里两股力量谁占上风 |
| **关键词信号** | "重点/中心/核心/关键" | "主流/方向/大局/本质/绝大多数" |
| **方法论** | "做事情、办事情" | "看问题、想问题" |
| **例子** | 中美/中日/中欧多对关系里中美是主要 | 单个买空调决策里"父强势母让步"=父是主要方面 |

(后两行 reference: [中公网校公基讲解](https://www.eoffcn.com/kszx/detail/1010001.html) + [知乎 @bigboss 区分指南](https://zhuanlan.zhihu.com/p/152202830))

LLM agent 实际场景里两个都会用——前者用于"先 fix 哪个 bug"、后者用于"这次 PR 算 refactor 还是 feature"。下面分别给原文 + 应用。

---

## 一、主要矛盾 vs 次要矛盾

### Verbatim 原文（《矛盾论》第四节）

> 「在矛盾特殊性的问题中，还有两种情形必须特别地提出来加以分析，
> 这就是主要的矛盾和主要的矛盾方面。
>
> 在复杂的事物的发展过程中，有许多的矛盾存在，其中必有一种是主
> 要的矛盾，由于它的存在和发展规定或影响着其它矛盾的存在和发展。
>
> （…）任何过程如果有多数矛盾存在的话，其中必定有一种是主要的，
> 起着领导的、决定的作用，其它则处于次要和服从的地位。因此，研
> 究任何过程，如果是存在着两个以上矛盾的复杂过程的话，就要用全
> 力找出它的主要矛盾。**捉住了这个主要矛盾，一切问题就迎刃而解
> 了。**」

### 关键洞察

1. **主要矛盾"规定或影响"其它**——解决了主要矛盾，次要常常自然
   简化。
2. **不是永恒**——"过程发展的各个阶段中，只有一种主要的矛盾起
   着领导的作用"——条件变了，主要矛盾换人。
3. **必须用全力找它**——而不是"列出 todo 然后从上到下做"。先
   花 cost 识别主要矛盾，再行动；列 todo 是 false productivity。

### 应用到 LLM agent

| 场景 | 反 pattern (做错) | 正 pattern (做对) |
|---|---|---|
| User 报多个 issue | 逐个 patch symptoms | 找根因——多 issue 常 share 一个根因 |
| Refactor task | 把"顺手 cleanup"和"主要 refactor"一起做 | 主要矛盾 = single source 收敛；cleanup 是次要、不进这次 commit |
| 优化任务 | 同时优化性能 + UX + cache hit | 主要矛盾 = 让功能 work；其他后续 ship |
| 设计 plan | 多 design 选项僵持 | 不是选 best design，是问"哪个 design 决定其他选项" |
| 多个 sub-task | 平均时间分配 | 主要 sub-task 占 70-80% 时间，其他让位 |

---

## 二、矛盾的主要方面 vs 次要方面

### Verbatim 原文（《矛盾论》第四节）

> 「不能把过程中所有的矛盾平均看待，必须把它们区别为主要的和次
> 要的两类，着重于捉住主要的矛盾，已如上述。但是在各种矛盾之中，
> 不论是主要的或次要的，矛盾着的两个方面，又是否可以平均看待呢？
> 也是不可以的。**无论什么矛盾，矛盾的诸方面，其发展是不平衡的。**
> 有时候似乎势均力敌，然而这只是暂时的和相对的情形，基本的形态
> 则是不平衡。矛盾着的两方面中，必有一方面是主要的，他方面是次
> 要的。其主要的方面，即所谓矛盾起主导作用的方面。**事物的性质，
> 主要地是由取得支配地位的矛盾的主要方面所规定的。**
>
> 然而这种情形不是固定的，矛盾的主要和非主要的方面互相转化着，
> 事物的性质也就随着起变化。」

### 关键洞察

1. **主要方面规定事物的性质**——一个 PR 是"refactor"还是"feature"
   由其**主要改动**定性，不由次要 cleanup 定性。
2. **主次方面会转化**——开始 task A 是主要的，做着做着 sub-task B
   涨成主要方面（比如 search bug 演变成 token budget 问题），要
   切换关注重心。
3. **平均势力是暂时假象**——感觉"两边一样重要"时，停下来想"哪个
   先变就改变全局"。

### 应用到 LLM agent

| 场景 | 反 pattern | 正 pattern |
|---|---|---|
| 描述 PR | 列所有 file 改动 | "主要改的是 X (规定 PR 性质)，附带 Y" |
| Code review | 平均评论每行改动 | 抓住决定 PR 性质的 1-2 处主要改动 |
| Bug report 分析 | "也偶尔 X / 也想顺便 Y" 都同等处理 | 抓 user 最痛的主要方面，次要 acknowledge 但不带过场 |
| 双向需求冲突 | 妥协 50/50 | 识别**当前阶段**哪方应支配，明确说选边 |

---

## 三、矛盾的普遍性 vs 特殊性（共性 vs 个性）

### Verbatim 原文（《矛盾论》第二、三节摘录）

> 「矛盾存在于一切事物的发展过程中；（…）每一事物的发展过程中
> 存在着自始至终的矛盾运动。」（普遍性）
>
> 「**这一共性个性、绝对相对的道理，是关于事物矛盾的问题的精髓，
> 不懂得它，就等于抛弃了辩证法。**」（特殊性 ↔ 普遍性 关系）

### 关键洞察 + LLM 应用

- **特殊性**：每个 task 有它的特殊矛盾——**别用 generic solution
  套所有 case**。"上次类似问题这么做"是 analogy，不是分析。
- **普遍性**：但**不要走另一极**——彻底否认"这跟之前 X 类似"会
  让 reasoning 重起炉灶浪费 cost。共性是出发点，**个性是落点**。
- **应用**：先 surface "这次特殊在哪 (vs. 类似 case)"，再决定多
  少 generic + 多少 case-specific。

---

## 四、同一性 vs 斗争性

### Verbatim 原文（《矛盾论》第五节摘录）

> 「**有条件的相对的同一性和无条件的绝对的斗争性相结合，构成了
> 一切事物的矛盾运动。**」
>
> 「'相反'就是说两个矛盾方面的互相排斥，或互相斗争。'相成'就是
> 说在一定条件之下两个矛盾方面互相联结起来，获得了同一性。**而
> 斗争性即寓于同一性之中，没有斗争性就没有同一性。**」

### 关键洞察 + LLM 应用

- **同一性**：看似对立的 requirement 通常 share 一个**更深 goal**——
  找它，把表面冲突化解掉。例: "做得快"vs"做得对" 表面冲突，深层
  都是"用户能 ship 可信代码"。从这个 deeper goal 推 → "小步 ship +
  严格 verify" 同时满足两端。
- **但不要消灭斗争性**——强行"团结"不可调和 requirement = 用户
  两边都不满意。例: 强加 spec 把 schema 自由度 + 严格类型同时塞
  进同一字段 = 两边都 break。
- **斗争性是绝对的，同一性是相对的**——别把短期妥协当永久 fix；
  随条件变，斗争会再现，需要重新 frame。

---

## 五、对抗性 vs 非对抗性

### Verbatim 原文（《矛盾论》第六节摘录）

> 「**对抗是矛盾斗争的一种形式，而不是矛盾斗争的一切形式。**
>
> （…）矛盾和斗争是普遍的、绝对的，但是解决矛盾的方法，即斗争
> 的形式，则因矛盾的性质不同而不相同。有些矛盾具有公开的对抗性，
> 有些矛盾则不是这样。」
>
> 列宁说：「对抗和矛盾断然不同。在社会主义下，对抗消灭了，矛盾
> 存在着。」

### 关键洞察 + LLM 应用

- **对抗性矛盾**：必须用"激烈手段"（block / refuse / 推翻）。
- **非对抗性矛盾**：可以"讨论 / 教育 / 改良"（澄清 / 协商 / 迭代）。
- **用错方式 = 灾难**：把非对抗当对抗（拒绝合理请求 / 强制 user
  按 LLM 想法）= 关系破裂；把对抗当非对抗（试图说服 user 接受
  destructive shortcut）= 真正损失发生。

LLM agent 实例：
- User 推 unrealistic deadline → **非对抗性**：透明说成本，让 user
  自己 reframe。不要 force fit。
- User 让 force-push 主分支删历史 → **对抗性**：必须 block；不要
  "教育引导式 negotiate"。
- User 询问 OK 但实施会泄漏 secret → **对抗性**（安全 vs 便利
  根本对立）：拦下来，不解释长篇道理求 negotiate。

---

## 方法论：两点论 + 重点论 结合（"弹钢琴"）

后世教科书化总结 (govt 官方 + 党史研究综合):

> 「辩证思维要求既善于抓重点、抓关键、抓主要矛盾，又善于统筹兼
> 顾、以点带面，统筹推进各项工作。这就要求我们学会'弹钢琴'，把
> '两点论'和'重点论'结合起来，**以重点突破带动整体推进**。」
> — 党史/政府文件常见提法 ([中国政府网 2024 政策解读](https://www.gov.cn/zhengce/202402/content_6934163.htm))

**对 LLM agent 的 takeaway**：
- "重点论"——必须有主次区分，**不能平均用力**
- "两点论"——但**不能完全忽略次要**（次要可能转化为主要）
- "弹钢琴"——**意识到次要的同时全力做主要**；做完主要看次要是否
  自然消失，没消失则它升级成新主要

伪代码：
```
while task_unsolved:
    contradictions = list_all_subproblems(task)
    primary = find_one_that_governs_others(contradictions)
    secondary = contradictions - {primary}
    log(f"主要: {primary}; 让位的次要: {secondary}")
    solve(primary)
    if all_secondary_now_simplified_or_gone:
        break
    else:
        # 次要中可能升级新的主要
        task = remaining_open_subproblems
        # 回到 while 头
```

---

## 与 NeoMind 已有 references 的关系

| Reference | 解决什么 | 维度 |
|---|---|---|
| first-principles.md | 拆到 substrate | 单点 verify |
| karpathy-2025-12-tweet.md | surface implicit assumption | 单点 verify |
| karpathy-skills-2026.md | falsifiability | 单点 verify |
| prompt-design-philosophy.md | pyramid template (PINNACLE / failure modes / GATE) | 单点 verify 综合 |
| **main-contradiction.md (本文)** | **多问题优先级 + 决定事物性质 + 转化时机** | **多点排队** |

**正交补充**，不是 replacement。前 4 个是"单步质量"，本文是"多步顺序"。

---

## When to invoke this lens

- 用户报多个 issue / 多个 ask 在同一 turn 里
- Refactor 任务（容易 over-scope，"顺手 cleanup"诱惑大）
- Bug fix 时手痒想 cleanup adjacent code
- 设计 plan 时多个 design 选项僵持
- "时间紧" + "做对" 看似冲突时（先验是非对抗）
- 描述/评估 PR 性质时（PR 主要方面规定它是 refactor / feature / fix）

## When NOT to invoke

- 单一明确 task（直接做就行，框架是 noise）
- 已经在 ship 路上的最后一公里（这时分析框架阻碍 ship）
- Routine 操作（git status / ls / 读 file，不需要"找主要矛盾"仪式）
- 做 unfamiliar new 领域时（先 first-principles 拆 substrate，
  主次还分不清楚）

类似 first-principles.md 的 counterpart 提醒：**框架本身也有它
的适用范围，强行套用 = 钻牛角尖**——正好是这条 reference 想
prevent 的失败模式。

---

## Sources cited

Verbatim quotes 原文核对来源:
- 毛泽东《矛盾论》(1937年8月) 全文 — user 提供的 verbatim paste
  (2026-05-02), 与 marxists.org 中文镜像 + 《毛选》第一卷出版版本
  对照一致

后世注解综合参考:
- [主要矛盾 - 百度百科](https://baike.baidu.com/item/%E4%B8%BB%E8%A6%81%E7%9F%9B%E7%9B%BE/3485436)
- [中公网校 - 快速区分主要矛盾与矛盾的主要方面](https://www.eoffcn.com/kszx/detail/1010001.html)
- [知乎 @bigboss - 如何区分主要矛盾与矛盾的主要方面](https://zhuanlan.zhihu.com/p/152202830)
- [中国政府网 2024 - 抓住主要矛盾促进工作落实](https://www.gov.cn/zhengce/202402/content_6934163.htm)
- [人民论坛网 - 实践论矛盾论的现实意义](https://www.rmlt.com.cn/2017/1226/507132.shtml)
- [湘潭大学毛泽东思想中心 - 新时代学习理解《矛盾论》要点](https://myzx.xtu.edu.cn/info/1011/2842.htm)
