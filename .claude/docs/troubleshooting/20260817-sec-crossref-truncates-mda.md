# 10-K 章节切分: 正文里的交叉引用被当成了章节结束

**发现于** 2026-08-17 · **模块** `agent/data_sources/sec_edgar.py`

## 症状 (伪装成"模型无能")

Company Dossier 报告 GOOGL 的「分部与收入结构」「债务与到期」两维**空**,
审计日志显示抽取器 `emitted=0` —— 看上去是"LLM 抽不出 Alphabet 的分部"。

Alphabet 显然是有分部的 (Google Services / Google Cloud / Other Bets)。
**模型没错, 是切片错了。**

## 根因

`slice_10k_sections` 用这个正则找 Item 7 (MD&A) 的结束位置:

```python
item7_ends = [m.start() for m in re.finditer(
    r"(?i)item\s*(7a|8)\b\.?\s*\n*\s*(quantitative|financial\s*statements)", text)]
...
e = min(ends)      # ← 取最早的
```

Alphabet 的 MD&A **正文中间**有这么一句:

> ...see Note 1 and Note 3 of the Notes to Consolidated Financial Statements
> included in Item 8 **as well as Item 7A Quantitative and Qualitative
> Disclosures About Market Risk** of this Annual Report on Form 10-K.

这句散文里的**交叉引用**匹配了上面的正则, 且位置比真标题早 35K 字,
于是 `min(ends)` 选中它 → MD&A 被切在 17,549 字, **正好停在
"Executive Overview" 之前**, 而所有表格和数字都在那之后。

致命之处: 切下来的那段里 **`$` 出现 0 次**。而 segments / debt 抽取器的
prompt 写着「只输出名称和数字都出现在原文里的条目」——
所以它们**完全正确地**返回了空。

> 一个解析 bug 伪装成模型能力不足。这类最难发现: 输出"合理地"为空,
> 没有报错, 没有异常, 只是永远抽不出东西。

## ❌ 错误的修法 (第一版, 已否决)

```python
# 只保留行首的锚点
if text[line_start:s].strip() == "": keep
```

对 GOOGL 有效, 但**误杀 AMD**: `_html_to_text` 展平后 AMD 的真标题粘在
运行页眉后面 —— `"...Table of ContentsITEM 7A. QUANTITATIVE"` —— 不在行首。
误杀之后 AMD 的 MD&A 一路吞到财报附注: **37,653 → 139,929 字**,
把附注里的数字当成 MD&A 的数字。

## ✅ 正确的判据

判别的不是"是否在行首", 而是**"前面有没有流动的散文"**:

| 情形 | 同行前缀 | 判定 |
|---|---|---|
| GOOGL 交叉引用 | `'...included in Item 8 as well as '` (43 字, 以空格结尾) | ❌ 丢弃 |
| AMD 粘页眉的真标题 | `'s'` (无空格, 直接粘住) | ✅ 保留 |
| GOOGL 真标题 | `''` | ✅ 保留 |
| 页眉碎屑 + 标题 | `'Table of Contents '` (17 字) | ✅ 保留 |

`_heading_anchors()`: 前缀为空、或**不以空格结尾**(粘页眉)、或短于 25 字
(页眉碎屑) → 是标题; 否则是散文里的交叉引用。全被过滤时退回原样
(sparse > wrong, 同 `_body_anchors`)。

## 实测效果 (真 filing + 真抽取器)

| | 修复前 | 修复后 |
|---|---|---|
| GOOGL MD&A | 17,549 字 / **0** 个美元金额 | 52,645 字 / 59 个 |
| GOOGL segments | 0 条 | **2 条** (Google Services 85.08% / Google Cloud 14.57%) |
| GOOGL debt | 0 条 | **7 条** ($48.5B 优先无抵押票据, 带利率与期限) |
| AMD / META / AAPL / MP / PANW / AAOI | — | **完全不变** (无回归) |

## 教训

1. **抽取器返回空, 先看喂给它的是什么**, 别先怀疑模型。
   量化的判据: 要数字的抽取器, 先数源文本里有几个 `$`/`%`。
2. **章节边界正则必须区分"标题"和"提到这个标题"**。10-K 里
   "见 Item 8" 这种交叉引用极其常见。
3. 判据要**同时**拿两个反向的真样本验 (GOOGL 的散文 / AMD 的粘页眉),
   否则修好一个必然踩坏另一个。
4. 回归测试里, 边缘样本必须和正常样本**共存**在同一个 fixture 里 ——
   只放边缘样本一个, `or starts` 兜底会把坏判据也放行 (变异测试实测:
   6 个用例全绿)。

测试: `tests/test_sec_edgar_heading_anchors.py` (两个方向的变异都验证过会红)
