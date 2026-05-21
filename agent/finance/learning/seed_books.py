"""Curated book list — separate from seed_classics.py (which holds
short-form memos/speeches/letters that are entirely free to read at
the source URL).

Each book has:
  - kind = 'book'
  - availability:
      'public_domain' — copyright expired, free legal full text
      'free_web'      — author/publisher distributes free online
      'paid'          — need to buy (Amazon / 当当 / library)
  - source_url:   canonical "about" / wikipedia / publisher page
  - purchase_url: where to BUY (paid) OR direct link to READ (free)

When the user opens a book card in the UI, they see the digest +
either a "📖 免费在线阅读" button (free) or "🛒 购买" button (paid).

URL provenance — anti-hallucination rule (see
.claude/skills/anti-hallucination/SKILL.md):
  - Every douban/amazon/jd/dangdang specific subject ID URL in this
    file MUST be verified live via WebFetch before commit. The
    earlier 2026-05-03 audit caught 5 fabricated douban IDs that
    pointed to unrelated books (see the url-fabrication anti-pattern
    note in the project's anti-hallucination memory).
  - When in doubt, prefer search-query URL forms (e.g.
    `search.douban.com/book/subject_search?search_text=...`) over
    deep-link IDs. Search URLs degrade gracefully; bad IDs lie.

If you find a new high-quality investing book, prefer entries with
free / public-domain availability so the user can start reading
immediately. Only add paid books that are truly canonical.
"""
from __future__ import annotations

from typing import Any, Dict, List


BOOKS: List[Dict[str, Any]] = [

    # ── 公开免费可读 (public_domain / free_web) ────────────────────

    {
        "slug": "book-reminiscences-of-stock-operator",
        "title": "Reminiscences of a Stock Operator (Lefèvre, 1923)",
        "title_zh": "《股票操盘手回忆录》(勒菲弗, 1923)",
        "summary_zh": (
            "Edwin Lefèvre 化名记录 Jesse Livermore 的投资生涯, 100 年前的市场, "
            "今天的人性。Livermore 在 14-50 岁经历了从赌场→bucket shop→华尔街大空头, "
            "1907 年和 1929 年两次靠做空赚 1 亿美元 (今值 ~30 亿)。书里最深刻的几"
            "句话: 《市场永远不会错, 错的永远是人的判断》《最大的钱不是来自你的"
            "买卖, 是来自你坐着不动的时候》《人性永远不变, 因此投机永远不变》。"
            "教训：100 年前的市场结构和今天完全不同, 但人的恐惧 + 贪婪 + FOMO + "
            "确认偏误一模一样。Livermore 最后破产自杀——再大的天才也敌不过情绪反复 "
            "+ 杠杆 + 市场无情。"
        ),
        "source_url": "https://en.wikipedia.org/wiki/Reminiscences_of_a_Stock_Operator",
        "source_name": "Lefèvre · 1923",
        "purchase_url": "https://www.gutenberg.org/ebooks/40766",
        "availability": "public_domain",
        "language": "en",
        "themes": ["心理", "投机史", "Livermore", "古典"],
        "era": "classic_intl",
        "difficulty": "beginner",
    },

    {
        "slug": "book-poor-charlies-almanack",
        "title": "Poor Charlie's Almanack (Charlie Munger)",
        "title_zh": "《穷查理宝典》(芒格)",
        "summary_zh": (
            "芒格毕生思想合集, 包含他 5 场最重要的演讲全文 + 多年访谈精选。"
            "核心思想：(1) Latticework of mental models — 跨学科思维, 80-100 个"
            "重要模型来自数学/物理/生物/心理/历史/化学；(2) 反过来想 (Invert, "
            "always invert)——想清楚怎么失败比怎么成功更容易；(3) 25 种人类误判心理"
            "学；(4) 多花时间研究失败案例。芒格 99 岁去世前一直引用这本书的内容。"
            "Stripe Press 2023 年和芒格家族合作, 在 stripe.press 上免费发布完整网页"
            "版 (含原版插图)——比纸质书还方便, 移动端阅读也好。"
        ),
        "source_url": "https://en.wikipedia.org/wiki/Poor_Charlie%27s_Almanack",
        "source_name": "Charlie Munger · Stripe Press 2023",
        "purchase_url": "https://www.stripe.press/poor-charlies-almanack",
        "availability": "free_web",
        "language": "en",
        "themes": ["芒格", "跨学科", "mental models", "心理学"],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "book-berkshire-shareholder-letters",
        "title": "Berkshire Hathaway Shareholder Letters (1965-2024)",
        "title_zh": "《伯克希尔·哈撒韦股东信全集》(巴菲特, 1965-至今)",
        "summary_zh": (
            "60 年股东信合集, 巴菲特投资思想的活体记录。比任何讲投资的书都更深刻——"
            "因为这是真金白银执行了 60 年的策略, 不是理论。读法建议: (1) 1977 年"
            "前的早期信短而锋利, 看 Buffett 的 Graham 阶段；(2) 1977-1990 年是从"
            "Graham 到 Munger 影响的转折期 (cigar butts → quality)；(3) 1990 年代后"
            "都是大师阶段, 每封都讨论一个 mental model；(4) 重点信：1977 (cigar"
            "butts→quality), 1988 (Coca-Cola), 1989 (mistakes of the first 25 years), "
            "2008 (financial crisis 实战), 2014 (50 周年回顾)。全部免费 PDF 在"
            "berkshirehathaway.com 上。"
        ),
        "source_url": "https://www.berkshirehathaway.com/letters/letters.html",
        "source_name": "Warren Buffett · Berkshire Hathaway",
        "purchase_url": "https://www.berkshirehathaway.com/letters/letters.html",
        "availability": "free_web",
        "language": "en",
        "themes": ["巴菲特", "价值投资", "护城河", "复利"],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "book-howard-marks-memos",
        "title": "Howard Marks Memos (Oaktree Capital, 1990-至今)",
        "title_zh": "《霍华德·马克斯备忘录全集》(Oaktree, 1990-至今)",
        "summary_zh": (
            "Oaktree 创始人 Howard Marks 30+ 年写给客户的季度 memo, 是另一种"
            "《股东信》——但比 Buffett 的更体系化、更聚焦于 risk + cycles。核心"
            "几篇必读: (1) The Most Important Thing (2003, 后来成书); (2) "
            "We're All Bond Investors Now (2022); (3) Sea Change (2022); "
            "(4) The Calibration Question (2023). Marks 的核心思想是 second-level "
            "thinking + cycle awareness, 永远思考《market 已经知道什么 + 我和它的"
            "不同点在哪》。所有 memo 公开免费, 在 oaktreecapital.com/insights 上。"
            "建议倒序读, 先看最近的 memo 体会他对当前市场的判断, 然后回看历史"
            "memo 看他过去对的次数和错的次数 (他都坦诚)。"
        ),
        "source_url": "https://www.oaktreecapital.com/insights/howard-marks-memos",
        "source_name": "Howard Marks · Oaktree Capital",
        "purchase_url": "https://www.oaktreecapital.com/insights/howard-marks-memos",
        "availability": "free_web",
        "language": "en",
        "themes": ["马克斯", "周期", "risk", "second-level"],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "book-damodaran-investment-valuation",
        "title": "Investment Valuation (Damodaran NYU online textbook)",
        "title_zh": "《投资估值》(Damodaran NYU 在线教科书)",
        "summary_zh": (
            "NYU Stern 的 Aswath Damodaran 教授 (估值领域最权威的学者) 把他的全套"
            "估值教科书 + 课件 + 课程视频 + 历史所有 200+ 公司估值案例 全部免费"
            "公开在他的 NYU 个人页面 + 同名博客 aswathdamodaran.blogspot.com 上。"
            "核心包含: (1) DCF 估值的所有变体 (FCFE/FCFF/EVA/APV)；(2) 相对估值"
            "(P/E, P/B, EV/EBITDA) 的统计基础和适用性；(3) 期权估值在公司估值"
            "中的应用 (negative working capital, growth options)；(4) 200+ 真实"
            "公司案例 (Tesla 估值演化, WeWork 反例, Uber IPO, Zomato IPO)。"
            "如果你认真做投资, 这是你需要 reference 一辈子的资源——胜过任何付费"
            "MBA 课程。建议从他的 valuation MBA 课程视频开始 (15 集)。"
        ),
        "source_url": "https://pages.stern.nyu.edu/~adamodar/",
        "source_name": "Aswath Damodaran · NYU Stern",
        "purchase_url": "https://pages.stern.nyu.edu/~adamodar/",
        "availability": "free_web",
        "language": "en",
        "themes": ["估值", "DCF", "Damodaran", "教科书"],
        "era": "classic_intl",
        "difficulty": "advanced",
    },

    {
        "slug": "book-duan-yongping-xueqiu-collected",
        "title": "段永平雪球留言精选 (大道无形我有型)",
        "title_zh": "《段永平雪球留言精选》(大道无形我有型)",
        "summary_zh": (
            "段永平 (步步高 / OPPO 创始人, 网易早期投资人, 苹果长期持有人) 没出过书, "
            "但他在雪球的 2000+ 条留言被很多人当作《中国版巴菲特股东信》。他的"
            "投资方法论核心：(1)《买股票就是买公司》——不能投不愿意整体收购的公司；"
            "(2)《商业模式 > 管理层 > 价格》, 顺序不能颠倒；(3)《不亏钱比赚钱重要》"
            "——一次大亏抵 10 年盈利；(4)《看不懂就不做》——错过 100 个机会比做错"
            "1 次更划算。他也是 Buffett 的精神门徒, 但落地在中国实战。雪球账号"
            "免费可读全部历史留言。"
        ),
        "source_url": "https://xueqiu.com/9769652619",
        "source_name": "段永平 · 雪球 (大道无形我有型)",
        "purchase_url": "https://xueqiu.com/9769652619",
        "availability": "free_web",
        "language": "zh",
        "themes": ["段永平", "价值投资", "中文经典", "企业家"],
        "era": "classic_cn",
        "difficulty": "intermediate",
    },

    # ── 需要购买 (paid) ────────────────────────────────────────────

    {
        "slug": "book-intelligent-investor",
        "title": "The Intelligent Investor (Benjamin Graham, 1949)",
        "title_zh": "《聪明的投资者》(本杰明·格雷厄姆, 1949)",
        "summary_zh": (
            "Buffett 称之为《史上最好的投资书》。1949 年首版, 2003 年 Jason Zweig"
            "增订评注版是最广泛阅读的版本。两个核心比喻成为价值投资词汇的基石:"
            "(1)《市场先生》——你的合伙人, 每天报价但情绪极端, 聪明的投资者只在"
            "他给离谱低/高价时反应；(2)《安全边际》——买入价 vs 内在价值之间的"
            "缓冲, 即使你估错 30%, 也不会亏。这本书的真正价值不在公式, 而在"
            "心理素质塑造——它教你怎么不被市场情绪牵着走。中文版有人民邮电出版社"
            "和机械工业出版社两个常见译本。如果只读一本投资入门书, 就读这本。"
        ),
        "source_url": "https://en.wikipedia.org/wiki/The_Intelligent_Investor",
        "source_name": "Benjamin Graham · Harper Business",
        "purchase_url": "https://search.douban.com/book/subject_search?search_text=The+Intelligent+Investor+Graham",
        "availability": "paid",
        "language": "en",
        "themes": ["价值投资", "格雷厄姆", "心理", "入门"],
        "era": "classic_intl",
        "difficulty": "beginner",
    },

    {
        "slug": "book-one-up-on-wall-street-lynch",
        "title": "One Up On Wall Street (Peter Lynch, 1989)",
        "title_zh": "《彼得·林奇的成功投资》(林奇, 1989)",
        "summary_zh": (
            "Peter Lynch 在 Fidelity Magellan 基金 1977-1990 年年化 29% 回报。这本"
            "书的副标题是《业余投资者如何利用自己的优势获得专业回报》。核心论点："
            "(1) 业余投资者其实有机构没有的优势——你在 Costco 看到爆款比华尔街早"
            "半年；(2) Buy what you know——只投你工作领域 + 消费领域；(3) 6 类股的"
            "分类 (slow grower / stalwart / fast grower / cyclical / turnaround / "
            "asset play) 给完全不同的投资策略；(4)《10 倍股》(tenbagger) 不需要"
            "找, 经常在你身边。这本书被誉为 90 年代散户运动的圣经。中文译本是"
            "机械工业出版社, 比较容易买到。"
        ),
        "source_url": "https://en.wikipedia.org/wiki/One_Up_on_Wall_Street",
        "source_name": "Peter Lynch · Simon & Schuster",
        "purchase_url": "https://search.douban.com/book/subject_search?search_text=One+Up+on+Wall+Street+Peter+Lynch",
        "availability": "paid",
        "language": "en",
        "themes": ["林奇", "选股", "tenbagger", "散户"],
        "era": "classic_intl",
        "difficulty": "beginner",
    },

    {
        "slug": "book-most-important-thing-marks",
        "title": "The Most Important Thing (Howard Marks, 2011)",
        "title_zh": "《投资最重要的事》(霍华德·马克斯, 2011)",
        "summary_zh": (
            "Marks 把自己 20+ 年的 memo 精华整理成的一本书, 比 memo 更系统化。"
            "《最重要的事》其实包含 20 件事——second-level thinking, 理解市场效率"
            "限制, contrarian timing, 周期意识, 钟摆模型, 风险定义 (= 永久性资本"
            "损失, 不是 volatility), defensive vs offensive, patience, 知道自己"
            "不知道, etc. Buffett 说《非常稀少: 一本真正有用的投资书》。如果你"
            "已经看完 Marks 的几篇 memo 觉得有共鸣, 这本书是把碎片整合成系统的"
            "完整版。中信出版社中文版翻译尚可。也可以先读他的 memo (free), 觉得"
            "不错再买书。"
        ),
        "source_url": "https://en.wikipedia.org/wiki/Howard_Marks_(investor)",
        "source_name": "Howard Marks · Columbia Business School Press",
        "purchase_url": "https://search.douban.com/book/subject_search?search_text=The+Most+Important+Thing+Howard+Marks",
        "availability": "paid",
        "language": "en",
        "themes": ["马克斯", "risk", "周期", "second-level"],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "book-margin-of-safety-klarman",
        "title": "Margin of Safety (Seth Klarman, 1991)",
        "title_zh": "《安全边际》(塞斯·卡拉曼, 1991, 已绝版)",
        "summary_zh": (
            "Baupost Group 创始人 Seth Klarman 在 1991 年写的价投经典, 早就绝版, "
            "二手市场上原版 eBay 1500-3000 美元一本。Klarman 是 Buffett 之后最被"
            "尊敬的价值投资者 (Baupost 30+ 年年化 ~16%)。这本书的核心：(1) 价值"
            "投资 ≠ 简单的低 PE / 低 PB；(2) 真正的价值投资是在《市场认为是垃圾》"
            "时找出《本质上不是垃圾》的资产；(3) 追求绝对回报, 不追相对基准；"
            "(4) Cash 不是闲置, 是 optionality——市场给你机会时, 你没钱比你犯错"
            "更可惜。如果买不到原版, 网上能找到 PDF 流传 (灰色, 但作者本人多次"
            "公开表示不计较), 中文翻译版网上也有 (非正式)。"
        ),
        "source_url": "https://en.wikipedia.org/wiki/Margin_of_Safety_(book)",
        "source_name": "Seth Klarman · HarperBusiness (out of print)",
        "purchase_url": "https://www.ebay.com/sch/i.html?_nkw=margin+of+safety+klarman+book",
        "availability": "paid",
        "language": "en",
        "themes": ["价值投资", "Klarman", "深度价值", "绝版"],
        "era": "classic_intl",
        "difficulty": "advanced",
    },

    {
        "slug": "book-zhang-lei-value",
        "title": "价值 (张磊, 高瓴资本, 2020)",
        "title_zh": "《价值》(张磊, 高瓴资本, 2020)",
        "summary_zh": (
            "高瓴资本张磊 2020 年自传 + 投资哲学合集。张磊是中国新一代最成功的"
            "投资人之一, 早期重仓腾讯 (拿了 17 年)、京东、美团、宁德时代等。"
            "核心思想：(1)《重仓最优秀的人》——投资人 = 投创始人；(2)《Long Hard"
            "Effort, Repeated》——长期主义不是口号是 20 年只做几件事；(3) 中国"
            "市场的特殊性 (政府 / 监管 / 文化), 美式价投框架必须本土化；(4) ESG"
            "和 social impact 在中国的实践。教训：对中国投资者来说, 这本书比"
            "任何美国经典都更贴近实际——因为它的 case 全是中国市场, 且作者亲历。"
            "浙江教育出版社 2020-09, 京东 / 当当 都有。"
        ),
        "source_url": "https://book.douban.com/subject/35188914/",
        "source_name": "张磊 · 浙江教育出版社",
        "purchase_url": "https://book.douban.com/subject/35188914/",
        "availability": "paid",
        "language": "zh",
        "themes": ["张磊", "高瓴", "长期主义", "中文经典"],
        "era": "classic_cn",
        "difficulty": "intermediate",
    },

    {
        "slug": "book-qiu-guolu-simplest-thing",
        "title": "投资中最简单的事 (邱国鹭, 2014)",
        "title_zh": "《投资中最简单的事》(邱国鹭, 2014)",
        "summary_zh": (
            "邱国鹭是高毅资产创始人, 之前在南方基金做投资总监。这本书是他多年"
            "投资笔记的整理。核心论点：(1)《价值投资在中国是有效的》——但要选"
            "正确的行业 (消费 / 医药 / 金融部分子板块), 不是无脑买所有股票；"
            "(2)《均值回归》是 A 股最强的规律之一——估值极端时永远会回归；"
            "(3)《好生意 + 好公司 + 好价格》三好原则, 缺一不可；(4) 大量真实 A 股"
            "case, 茅台、格力、平安、招商银行的研究框架。这本书是中国本土价投"
            "实战手册, 比直接照搬 Buffett 框架更接地气。京东 / 当当 30-50 元。"
        ),
        "source_url": "https://book.douban.com/subject/35000951/",
        "source_name": "邱国鹭 · 中国经济出版社 (更新版 2020)",
        "purchase_url": "https://book.douban.com/subject/35000951/",
        "availability": "paid",
        "language": "zh",
        "themes": ["邱国鹭", "A股", "中文经典", "实战"],
        "era": "classic_cn",
        "difficulty": "intermediate",
    },

    # ── 中译本 (Chinese translations of English originals) ────────
    #
    # Each entry below mirrors a parent English entry above. The
    # parent keeps the original-language framing for English readers;
    # this sibling gives Chinese readers a verified 豆瓣 page with
    # publisher/translator info. All URLs verified via WebFetch on
    # 2026-05-03 — see feedback_url_fabrication_in_seeds.md.

    {
        "slug": "book-intelligent-investor-zh",
        "title": "聪明的投资者 (人民邮电出版社, 王中华/黄一义译)",
        "title_zh": "《聪明的投资者》(中译本 · 人民邮电, 王中华/黄一义 译)",
        "summary_zh": (
            "Graham《The Intelligent Investor》中译本, 译者王中华 / 黄一义, "
            "人民邮电出版社。是国内流通最广的版本之一, 包含 Jason Zweig 的"
            "全部评注 (《市场先生》和《安全边际》两个核心比喻在中文里也通顺)。"
            "适合不愿读英文原版的中国读者作为入门——配套读上面的英文条目里"
            "的全部精华即可。京东 / 当当 都有, 50-70 元。"
        ),
        "source_url": "https://book.douban.com/subject/5243775/",
        "source_name": "人民邮电出版社 · 王中华/黄一义 译",
        "purchase_url": "https://book.douban.com/subject/5243775/",
        "availability": "paid",
        "language": "zh",
        "themes": ["价值投资", "格雷厄姆", "中译本", "入门"],
        "era": "classic_intl",
        "difficulty": "beginner",
    },

    {
        "slug": "book-one-up-on-wall-street-lynch-zh",
        "title": "彼得·林奇的成功投资 (机械工业出版社, 刘建位/徐晓杰译)",
        "title_zh": "《彼得·林奇的成功投资》(中译本 · 机工社, 刘建位/徐晓杰 译)",
        "summary_zh": (
            "Lynch《One Up on Wall Street》中译本, 机械工业出版社, 刘建位 / "
            "徐晓杰译。刘建位本身是国内研究 Lynch + Buffett 的资深译者, "
            "翻译质量公认靠谱。Lynch 提出的《散户优势》《六类股分类》《tenbagger》"
            "在中文里都翻得清楚。京东 / 当当 30-50 元, 是入门散户书的中文首选。"
        ),
        "source_url": "https://book.douban.com/subject/1958714/",
        "source_name": "机械工业出版社 · 刘建位/徐晓杰 译",
        "purchase_url": "https://book.douban.com/subject/1958714/",
        "availability": "paid",
        "language": "zh",
        "themes": ["林奇", "选股", "中译本", "散户"],
        "era": "classic_intl",
        "difficulty": "beginner",
    },

    {
        "slug": "book-most-important-thing-marks-zh",
        "title": "投资最重要的事 (全新升级版, 中信出版社, 李莉/石继志译)",
        "title_zh": "《投资最重要的事》(中译本 · 中信全新升级版, 李莉/石继志 译)",
        "summary_zh": (
            "Marks《The Most Important Thing Illuminated》中译本 (升级版含其他 4 位"
            "投资人评注: Bruce Greenwald / Christopher Davis / Joel Greenblatt / "
            "Paul Johnson), 中信出版社 2015-09, 李莉 / 石继志译。中译质量比"
            "原版第一版更稳, 带评注让阅读更立体。如果中文 reader 想系统看 Marks "
            "思想, 这本比单看 Oaktree memo 更适合一气读完。京东 / 当当 ~55 元。"
        ),
        "source_url": "https://book.douban.com/subject/26634824/",
        "source_name": "中信出版社 · 李莉/石继志 译 (升级版 2015)",
        "purchase_url": "https://book.douban.com/subject/26634824/",
        "availability": "paid",
        "language": "zh",
        "themes": ["马克斯", "risk", "second-level", "中译本"],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "book-poor-charlies-almanack-zh",
        "title": "穷查理宝典 (珍藏版, 中信出版社, 李继宏译)",
        "title_zh": "《穷查理宝典》(中译本 · 中信珍藏版, 李继宏 译)",
        "summary_zh": (
            "Munger《Poor Charlie's Almanack》中译本 (珍藏版), 中信出版社 2017-03, "
            "李继宏译。这是国内唯一授权完整版本——包含芒格全部 5 场重要演讲、"
            "20 多年访谈摘录、芒格家人和合作伙伴的回忆文章。李继宏译笔流畅"
            "(也是《追风筝的人》《了不起的盖茨比》的译者)。注意: Stripe Press 的"
            "免费英文网页版只是英文原本, 没有李继宏的中文翻译——如果想读中文,"
            "买这本。京东 / 当当 ~70 元。"
        ),
        "source_url": "https://book.douban.com/subject/26992478/",
        "source_name": "中信出版社 · 李继宏 译 (珍藏版 2017)",
        "purchase_url": "https://book.douban.com/subject/26992478/",
        "availability": "paid",
        "language": "zh",
        "themes": ["芒格", "跨学科", "mental models", "中译本"],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "book-reminiscences-of-stock-operator-zh",
        "title": "股票大作手回忆录 (中华工商联合出版社, 王坤译)",
        "title_zh": "《股票大作手回忆录》(中译本 · 中华工商联合, 王坤 译)",
        "summary_zh": (
            "Lefèvre《Reminiscences of a Stock Operator》中译本, 王坤译, "
            "中华工商联合出版社 2017-11。原著 1923 年, 已是公版书, 因此"
            "中文译本众多——这一版口碑较好, 流通也稳。如果想读 Livermore"
            "的故事中文版而不愿啃英文古典文体, 这本足够。京东 / 当当 30-40 元。"
            "(原版英文免费可在 Project Gutenberg 读, 见上面公版书条目)。"
        ),
        "source_url": "https://book.douban.com/subject/27601129/",
        "source_name": "中华工商联合出版社 · 王坤 译",
        "purchase_url": "https://book.douban.com/subject/27601129/",
        "availability": "paid",
        "language": "zh",
        "themes": ["心理", "投机史", "Livermore", "中译本"],
        "era": "classic_intl",
        "difficulty": "beginner",
    },

    {
        "slug": "book-buffett-letters-zh",
        "title": "巴菲特致股东的信 (第4版, 机工社, 杨天南译, 坎宁安编)",
        "title_zh": "《巴菲特致股东的信》(第4版 · 机工社, 杨天南 译, 坎宁安 编)",
        "summary_zh": (
            "巴菲特历年股东信精选合集 (Lawrence Cunningham 主题化编辑), "
            "中文第 4 版, 杨天南译, 机械工业出版社 2018-03。杨天南本身是国内"
            "知名价投实战派 (《一个投资家的 20 年》作者), 翻译有 insider"
            "视角。这本不是 Berkshire 全部 60 年的信全集 (那本要去 berkshirehathaway.com"
            "看英文 PDF), 而是 Cunningham 按主题 (治理 / 估值 / 并购 / 会计 / 价值"
            "投资) 重组后的精华合集——更适合系统学习, 不适合按时间线追踪 Buffett 思想"
            "演化。两种读法各有用处。京东 / 当当 ~60 元。"
        ),
        "source_url": "https://book.douban.com/subject/30164963/",
        "source_name": "机械工业出版社 · 杨天南 译 (坎宁安 编, 第4版 2018)",
        "purchase_url": "https://book.douban.com/subject/30164963/",
        "availability": "paid",
        "language": "zh",
        "themes": ["巴菲特", "价值投资", "中译本", "合集"],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "book-damodaran-investment-valuation-zh",
        "title": "估值 (第2版, 机工社, 李必龙/李羿/郭海译)",
        "title_zh": "《估值》(中译本第 2 版 · 机工社, 李必龙/李羿/郭海 译)",
        "summary_zh": (
            "Damodaran《Investment Valuation》(2nd ed) 中译本, 机械工业出版社, "
            "李必龙 / 李羿 / 郭海译。这是 Damodaran 估值教科书的中文版——比看英文"
            "原书 + 课件慢, 但对不愿读英文教科书的读者是 reasonable 的入口。"
            "注意: 中译本只翻译了主教科书, Damodaran 本人在 NYU 网页 + 博客上"
            "免费的 200+ 公司案例 / 课件 / 视频都没翻——那部分还是要去英文站看"
            "(见上面 free_web 条目)。京东 / 当当 ~120 元 (大部头)。"
        ),
        "source_url": "https://book.douban.com/subject/24708136/",
        "source_name": "机械工业出版社 · 李必龙/李羿/郭海 译 (第 2 版)",
        "purchase_url": "https://book.douban.com/subject/24708136/",
        "availability": "paid",
        "language": "zh",
        "themes": ["估值", "DCF", "Damodaran", "中译本"],
        "era": "classic_intl",
        "difficulty": "advanced",
    },
]


def all_books() -> List[Dict[str, Any]]:
    """Return all books. Wrapped so callers don't mutate the const."""
    return list(BOOKS)
