"""10-K 章节切分: 交叉引用 ≠ 章节标题。

**真事故 (2026-08-17)**: Alphabet 的 MD&A 正文里有一句
``"...included in Item 8 as well as Item 7A Quantitative and Qualitative
Disclosures About Market Risk of this Annual Report on Form 10-K."``
—— 这句**散文中间的交叉引用**匹配了 item7 的结束锚点正则, 于是
``min(ends)`` 选中了它, GOOGL 的 MD&A 被切在 17.5K 字, **正好停在
"Executive Overview" 之前**, 而所有数字都在后面。

后果不是"少一点内容", 而是切片里**一个美元金额都没有** ($ 出现 0 次):
segments / debt 抽取器的 prompt 要求"名称和数字都必须出现在原文",
于是它们**正确地**返回了空。看上去像"LLM 抽不出 Alphabet 的分部",
实际是解析 bug —— 这种伪装成模型无能的解析故障最难发现。

修复后实测 (真 filing, 真抽取器): GOOGL MD&A 17,549 → 52,645 字,
美元金额 0 → 59; segments 0 → 2 条 (Google Services 85.08% /
Google Cloud 14.57%), debt 0 → 7 条。
"""
from agent.data_sources.sec_edgar import _heading_anchors


def _pos(text: str, needle: str) -> int:
    i = text.find(needle)
    assert i >= 0, f"fixture 里找不到 {needle!r}"
    return i


def test_inline_cross_reference_is_not_a_heading():
    """GOOGL 那一刀 —— 前面是流动的散文 + 空格。"""
    text = ("Alphabet Inc.\n"
            "For additional information, see Note 1 and Note 3 of the Notes to "
            "Consolidated Financial Statements included in Item 8 as well as "
            "Item 7A Quantitative and Qualitative Disclosures About Market Risk.\n")
    i = _pos(text, "Item 7A Quantitative")
    assert _heading_anchors(text, [i]) == [i], "全被过滤时要退回原样 (sparse > wrong)"
    # 真标题同时存在时, 交叉引用必须被丢掉
    text2 = text + "ITEM 7A.\nQUANTITATIVE AND QUALITATIVE DISCLOSURES\n"
    j = _pos(text2, "ITEM 7A.\nQUANTITATIVE")
    assert _heading_anchors(text2, [i, j]) == [j]


def test_heading_glued_to_page_header_still_counts():
    """AMD 那一刀 —— `_html_to_text` 把页眉和标题粘一起, 中间**没有空格**。

    这正是"必须在行首"那个朴素判据会误杀的情况: 误杀之后 AMD 的 MD&A
    会一路吞到财报附注 (实测 37,653 → 139,929 字), 把附注里的数字
    当成 MD&A 的数字。
    """
    # 🔴 关键: 粘页眉的锚点必须和一个**行首**锚点同时存在。
    # 只放它一个的话, `or starts` 兜底会把它救回来 —— 于是"必须在行首"那个
    # 坏判据也能让测试通过 (变异测试实测: 6 个用例全绿)。看不见的腐蚀最危险。
    text = ("prose line\nTable of ContentsITEM 7A. QUANTITATIVE AND QUALITATIVE\n"
            "more prose\nITEM 8.\nFINANCIAL STATEMENTS\n")
    glued = _pos(text, "ITEM 7A.")
    own_line = _pos(text, "ITEM 8.")
    assert _heading_anchors(text, [glued, own_line]) == [glued, own_line], (
        "粘在页眉后的真标题被误杀了 —— AMD 的 MD&A 会因此一路吞到财报附注")


def test_heading_owning_its_line_counts():
    text = "some prose\nITEM 8.\nFINANCIAL STATEMENTS\n"
    i = _pos(text, "ITEM 8.")
    assert _heading_anchors(text, [i]) == [i]


def test_short_page_header_crumb_before_heading_counts():
    """页眉碎屑 + 空格 + 标题 —— 仍是标题, 不是散文。"""
    text = "prose\nTable of Contents ITEM 8. FINANCIAL STATEMENTS\n"
    i = _pos(text, "ITEM 8.")
    assert _heading_anchors(text, [i]) == [i]


def test_indented_heading_counts():
    text = "prose\n    ITEM 8. FINANCIAL STATEMENTS\n"
    i = _pos(text, "ITEM 8.")
    assert _heading_anchors(text, [i]) == [i]


def test_empty_input_is_safe():
    assert _heading_anchors("", []) == []
    assert _heading_anchors("abc", []) == []
