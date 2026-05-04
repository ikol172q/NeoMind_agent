"""Classic investing books / blogs / memos — public-domain or
public-web sources only. Each entry is a CHAPTER / KEY-IDEA digest,
not the full book — but with a click-through to the public source
so the user can read the full text directly.

These supplement the case-study seeds in seed_cases.py:
  - seed_cases.py = WHAT happened (events, blow-ups, big trades)
  - seed_classics.py = HOW to think (Buffett's mental models,
                       Marks' cycles, Munger's latticework, etc.)

Selection criteria:
  - Public source URL (no paywall, no scraping needed). Stuff like
    Berkshire shareholder letters, Marks memos at oaktree.com,
    Damodaran NYU blog, Munger speeches at USC/Caltech.
  - Each digest is the ESSENCE of the source, not a teaser. Lead with
    the takeaway in 1-2 sentences, then explain.
  - Mark era as "classic_intl" or "classic_cn" so the era filter
    cleanly separates them from event-cases and recent material.

If you add a new entry: stable slug, summary stays under ~700 chars,
include source_url to a free-to-read public origin.
"""
from __future__ import annotations

from typing import Any, Dict, List


CLASSICS: List[Dict[str, Any]] = [

    # ── Buffett shareholder letters ────────────────────────────────

    {
        "slug": "classic-buffett-1977-letter-cigar-butt-vs-quality",
        "title": "Buffett 1977 Letter — Cigar Butts vs Quality",
        "title_zh": "巴菲特 1977 股东信：从烟蒂到优质公司的转折",
        "summary_zh": (
            "1977 年这封信里, Buffett 第一次公开自己投资哲学的转向："
            "从早期 Graham 式的《捡烟蒂》(买入价远低于清算价值的烂公司，吸最后一口) "
            "转向找《以合理价格买入伟大公司》。原文金句：《一个被困在烂行业里的"
            "好管理层，名声打不过行业的烂》。教训：(1) 投资者最大的认知升级是从"
            "《买便宜的》转到《买对的》——后者复利效应远超前者；(2) 行业本身的资本"
            "回报率限制了管理层能做的事；(3) 这个转折是 Munger 影响 Buffett 的最大"
            "成果。这封信是研究 Buffett 思维进化的最佳起点。"
        ),
        "source_url": "https://www.berkshirehathaway.com/letters/1977.html",
        "source_name": "Berkshire 1977 Letter",
        "language": "en",
        "themes": ["巴菲特", "价值投资", "护城河", "投资哲学"],
        "tickers": ["BRK.A"],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "classic-buffett-1989-letter-mistakes-of-the-first-25-years",
        "title": "Buffett 1989 Letter — Mistakes of the First 25 Years",
        "title_zh": "巴菲特 1989 股东信：前 25 年我犯的错",
        "summary_zh": (
            "Buffett 在 1989 年信里用整整一段总结自己 25 年投资生涯的失误。最大教训："
            "(1) 《我以为便宜就是安全》——结果买入的烂公司，其低价反映的是真实的烂；"
            "(2) 《我和不喜欢的人合作》——管理层人品比公司基本面更重要；"
            "(3) 《我犹豫太久》——好机会出现时，10 万美元的机会和 100 万美元的"
            "机会需要的判断力一样，但只下了 10 万。后续启示：投资者最该花精力的是"
            "《识别哪些是真正确定的机会》，然后下足够大的注。这封信是 Buffett 自我"
            "批评的范本，远比《选股清单》更有学习价值。"
        ),
        "source_url": "https://www.berkshirehathaway.com/letters/1989.html",
        "source_name": "Berkshire 1989 Letter",
        "language": "en",
        "themes": ["巴菲特", "复盘", "仓位管理", "认知偏差"],
        "tickers": ["BRK.A"],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    # ── Munger ──────────────────────────────────────────────────────

    {
        "slug": "classic-munger-psychology-of-misjudgment-1995",
        "title": "Munger — The Psychology of Human Misjudgment (1995 Harvard speech)",
        "title_zh": "芒格《人类误判心理学》——投资者的 25 个认知陷阱",
        "summary_zh": (
            "Munger 1995 年在哈佛法学院的演讲，列出 25 种导致人决策失误的心理倾向。"
            "对投资者最关键的几条：(1) Reward and Punishment Super-response Tendency"
            "——激励决定行为，比如华尔街分析师永远偏多头；(2) Liking/Loving Tendency"
            "——你喜欢一家公司的产品就会高估它；(3) Social Proof Tendency——所有人都买"
            "的股票必然 mispriced；(4) Lollapalooza Tendency——多个偏差叠加产生极端"
            "结果（2008 次贷危机就是 5+ 个偏差合谋）。教训：投资 = 工程 + 心理学，"
            "懂第一种但不懂第二种的人最终都被市场淘汰。这是 Munger 最被引用的演讲。"
        ),
        "source_url": "https://fs.blog/great-talks/psychology-human-misjudgment/",
        "source_name": "Farnam Street · Munger transcript",
        "language": "en",
        "themes": ["心理学", "认知偏差", "芒格", "决策"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "classic-munger-worldly-wisdom-1994-usc",
        "title": "Munger — A Lesson on Elementary Worldly Wisdom (1994 USC)",
        "title_zh": "芒格 1994 USC 演讲：跨学科思维的力量",
        "summary_zh": (
            "Munger 在南加大商学院的演讲, 提出投资必须有 latticework of mental "
            "models（多学科模型构成的格栅）。核心论点：(1) 单一学科的视角必然失真——"
            "经济学家只看 supply/demand，但忽略心理学+生物学+物理学的相互作用；"
            "(2) 重要的模型大约 80-100 个, 来自数学/物理/生物/心理/历史/工程/化学；"
            "(3) 这些模型必须 internalized 到能在新场景下条件反射式调用。教训：投资者"
            "如果只懂金融模型 (DCF/CAPM/MPT), 就只能在金融模型成立时赚钱——一旦"
            "市场进入心理驱动 / 政策驱动 / 技术革命驱动期，纯金融视角就盲了。Munger"
            "本人是这种跨学科思维的活体范本。"
        ),
        "source_url": "https://fs.blog/great-talks/a-lesson-on-elementary-worldly-wisdom/",
        "source_name": "Farnam Street · Munger USC 1994",
        "language": "en",
        "themes": ["芒格", "跨学科", "mental models", "认知"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "advanced",
    },

    # ── Howard Marks ────────────────────────────────────────────────

    {
        "slug": "classic-marks-most-important-thing-second-level-thinking",
        "title": "Howard Marks — Second-Level Thinking (Memo, 2015)",
        "title_zh": "霍华德·马克斯《第二层思考》——超越共识才有 alpha",
        "summary_zh": (
            "Marks 论述投资者必须做《第二层思考》: 第一层是《这家公司好，所以买》，"
            "第二层是《市场已经知道它好，所以价格已经反映；那为什么我还应该买？》"
            "核心命题：(1) 第一层是直觉，每个人都能做；(2) 第二层是 contrarian，"
            "需要思考《others 怎么想 + 我和他们哪里不同 + 我对的概率多大》；"
            "(3) 大多数所谓的《投资判断》其实是第一层伪装的——跟着新闻走、跟着分析师走、"
            "跟着热点走。教训：你和市场的差异性 (variant perception) 才是 alpha 的源头。"
            "如果你的判断和共识一样, 你最多赚到 beta。这是 Marks 整本《最重要的事》"
            "的核心论点。"
        ),
        "source_url": "https://www.oaktreecapital.com/insights/memo/dare-to-be-great-ii",
        "source_name": "Oaktree · Howard Marks memo",
        "language": "en",
        "themes": ["alpha", "contrarian", "认知差", "马克斯"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "classic-marks-cycles-pendulum",
        "title": "Howard Marks — The Pendulum and Market Cycles",
        "title_zh": "霍华德·马克斯《钟摆理论》——市场情绪从恐惧到贪婪再回",
        "summary_zh": (
            "Marks 用钟摆比喻市场情绪：(1) 钟摆从来不停在中点，永远摆向极端；"
            "(2) 摆到一端就开始反向积累势能；(3) 极端时的行为最荒谬但被广泛认同 "
            "(2000 互联网, 2008 次贷, 2021 SPAC, 2022 加密)。投资者的工作不是预测"
            "拐点（不可能），而是判断当前在钟摆的哪个位置 + 据此调整 risk。核心思想："
            "(1) 卖在贪婪 / 买在恐惧，知易行难——因为贪婪时你也贪婪 + 恐惧时你也"
            "恐惧；(2) 真正能跑赢市场的人是 constant temperament + willingness "
            "to be lonely。教训：市场永远在循环, "
            "但每次循环的剧本都不一样, 看历史能识别 PATTERN 不能预测 TIMING。"
        ),
        "source_url": "https://www.oaktreecapital.com/insights/memo/the-most-important-thing",
        "source_name": "Oaktree · Howard Marks",
        "language": "en",
        "themes": ["周期", "情绪", "马克斯", "risk management"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    # ── Lefèvre / 老经典 (public domain) ──────────────────────────

    {
        "slug": "classic-reminiscences-of-stock-operator-livermore",
        "title": "Reminiscences of a Stock Operator (Lefèvre, 1923)",
        "title_zh": "《股票操盘手回忆录》——百年前的市场永远在重复",
        "summary_zh": (
            "Edwin Lefèvre 1923 年化名记录 Jesse Livermore 的投资生涯。Livermore "
            "在 14-50 岁经历了从赌客→bucket shop 杀手→华尔街大空头, 1907 年和 1929 年"
            "两次靠做空赚得当时 1 亿美元 (今值 ~30 亿)。书里最深刻的几句话："
            "(1) 《市场永远不会错, 错的永远是人的判断》；(2) 《最大的钱不是来自你的"
            "买卖, 是来自你坐着不动的时候》；(3) 《人性永远不变, 因此投机永远不变》。"
            "教训：100 年前的市场结构和今天完全不同, 但人的恐惧 + 贪婪 + FOMO + "
            "确认偏误一模一样。Livermore 最后破产自杀——再大的天才也敌不过"
            "情绪反复 + 杠杆 + 市场无情。public domain, gutenberg.org 全文免费。"
        ),
        "source_url": "https://www.gutenberg.org/ebooks/40766",
        "source_name": "Project Gutenberg · public domain",
        "language": "en",
        "themes": ["心理", "投机史", "Livermore", "古典"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "beginner",
    },

    # ── Peter Lynch / Beating the Street ──────────────────────────

    {
        "slug": "classic-lynch-rule-of-six-step",
        "title": "Peter Lynch — Buy What You Know + 5 Rules (One Up On Wall Street)",
        "title_zh": "彼得·林奇《买你了解的》——业余投资者的真实优势",
        "summary_zh": (
            "Peter Lynch 在 Fidelity Magellan 基金 1977-1990 年年化 29% 的回报。"
            "他坚持业余投资者其实有机构投资者没有的优势：(1) 《先消费再投资》——你在"
            "Costco 看到爆款才决定买 COST 股票, 比华尔街分析师早 6 个月；(2) 你的"
            "工作领域里你比 99% 的分析师都懂；(3) 没人逼你季度交业绩, 可以真正长持。"
            "他的 6 类股分类法：slow grower / stalwart / fast grower / cyclical /"
            "turnaround / asset play. 教训：(1) 别尝试做你不懂的, 哪怕它涨翻天；"
            "(2) 在你能 edge 的领域 size 加大；(3) 《10 倍股 (tenbagger)》 不需要"
            "找到, 经常它就在你身边。这本书是 90 年代散户运动的圣经。"
        ),
        "source_url": "https://www.fidelity.com/learning-center/personal-finance/peter-lynch-investment-strategy",
        "source_name": "Fidelity · Lynch overview",
        "language": "en",
        "themes": ["林奇", "选股", "tenbagger", "散户"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "beginner",
    },

    # ── Ben Graham / 价值投资始祖 ──────────────────────────────────

    {
        "slug": "classic-graham-mr-market-margin-of-safety",
        "title": "Ben Graham — Mr. Market + Margin of Safety (Intelligent Investor)",
        "title_zh": "格雷厄姆《聪明的投资者》——市场先生 + 安全边际",
        "summary_zh": (
            "Graham 1949 年首版《Intelligent Investor》, Buffett 称之为 《史上最好"
            "的投资书》。两个核心比喻：(1) 《市场先生》Mr. Market 是你的合伙人, "
            "每天给你报价, 但情绪极端 + 反复无常。聪明的投资者只在他给出离谱低价"
            "时买、离谱高价时卖, 其余时间忽略他；(2) 《安全边际》margin of safety "
            "= 你买入价 vs 内在价值 (intrinsic value) 之间的缓冲。如果你认为公司值 "
            "$100 但只在 $60 买, 即使你估算错 30%, 也不会亏。教训：(1) 价格和价值"
            "是两件事——价格短期由情绪驱动, 长期回归价值；(2) 你不需要预测市场, 只"
            "需要在价格离谱时反应。这两个概念是所有价值投资者的认知起点。"
        ),
        "source_url": "https://en.wikipedia.org/wiki/The_Intelligent_Investor",
        "source_name": "Wikipedia · Intelligent Investor 概要",
        "language": "en",
        "themes": ["价值投资", "格雷厄姆", "心理", "安全边际"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "beginner",
    },

    # ── Damodaran (NYU) ──────────────────────────────────────────────

    {
        "slug": "classic-damodaran-narrative-and-numbers",
        "title": "Damodaran — Narrative and Numbers (Story-driven Valuation)",
        "title_zh": "Damodaran《叙事与数字》——估值的本质是讲一个可信的故事",
        "summary_zh": (
            "NYU Stern 的 Damodaran 教授 (估值领域最权威学者) 在 2017 年这本书里"
            "论述：估值不是单纯的 DCF 数学, 而是要讲一个《可信的故事》, 然后用"
            "数字翻译它。三步法: (1) 《故事》——这家公司在 5/10/20 年后会是什么样的"
            "公司？(2) 《数字》——把故事翻译成 revenue growth + margin + ROIC + 终值"
            "(3) 《一致性》——故事和数字必须互相印证, 否则就是空中楼阁 (Tesla 几个"
            "时期 + WeWork 经典反例)。教训：(1) 同一家公司不同的故事能算出 10 倍"
            "差异的估值, 所以《故事是估值的核心变量》, 不是数字；(2) 看到分析师"
            "目标价时, 倒推他的故事是什么——故事不合理则价格不合理。Damodaran 自己"
            "公开估值过 200+ 公司, 是最透明的估值教学者。"
        ),
        "source_url": "https://aswathdamodaran.blogspot.com/",
        "source_name": "Damodaran 博客 (NYU Stern)",
        "language": "en",
        "themes": ["估值", "DCF", "Damodaran", "叙事"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "advanced",
    },

    # ── 中文经典 ────────────────────────────────────────────────────

    {
        "slug": "classic-cn-duan-yongping-buy-good-business",
        "title": "段永平 — 关于《好公司、好行业、合理价格》",
        "title_zh": "段永平《买好公司就够了》——中国价投的草根真传",
        "summary_zh": (
            "段永平 (步步高 / OPPO 创始人, 后转私募) 是中国最被尊敬的价值投资者之一, "
            "2001 年成功投资网易 (10x 回报)、2008 年投资苹果 (持有至今 60x+)。他在"
            "雪球的留言反复强调几个核心：(1) 《买股票就是买公司, 你买不下整家公司"
            "时, 至少把买股票当成入股》；(2) 《看不懂的公司不投, 哪怕它涨上天》；"
            "(3) 《商业模式 > 管理层 > 价格, 顺序不能颠倒》；(4) 《复利的关键是不"
            "亏钱, 一次大亏抵掉 10 年盈利》。教训：段永平的方法不是华尔街的, 是"
            "企业家的——他理解《公司的真实运营》, 这让他对苹果 / 茅台这种"
            "long-term moat 公司的判断比华尔街更早 / 更准。"
        ),
        "source_url": "https://xueqiu.com/9769652619",
        "source_name": "雪球·段永平 (大道无形我有型)",
        "language": "zh",
        "themes": ["段永平", "价值投资", "中文经典", "企业家视角"],
        "tickers": ["AAPL", "NTES"],
        "era": "classic_cn",
        "difficulty": "intermediate",
    },

    {
        "slug": "classic-cn-zhang-lei-value",
        "title": "张磊《价值》——长期主义在中国的实践",
        "title_zh": "张磊《价值》——为什么《Long Hard Effort》在中国也能 work",
        "summary_zh": (
            "高瓴资本张磊 2020 年《价值》一书。核心：(1) 《重仓最优秀的人》——"
            "张磊投资了腾讯、京东、美团、宁德时代早期，关键不是看商业模式, 而是"
            "看创始人。(2) 《Long Hard Effort, Repeated》——长期主义不是口号, 是 "
            "20 年只做几件事, 把每件做到极致。(3) 中国市场的特殊性：政府 +"
            "监管 + 文化, 美式价值投资框架 (Buffett/Munger) 必须本土化。教训："
            "(1) 在中国, 投资人和企业家的关系比美国更深——美国是甩手掌柜, 中国"
            "经常深度介入治理；(2) 张磊把 Buffett 的《长期持有》和 a16z 的《重投创始人》"
            "结合, 是中美投资文化的混合体；(3) 他对腾讯的 17 年长持和宁德时代的"
            "重仓, 都是在《公司还没被市场看清》时下注——这才是 alpha 的本质。"
        ),
        "source_url": "https://book.douban.com/subject/35190354/",
        "source_name": "豆瓣读书·张磊《价值》",
        "language": "zh",
        "themes": ["张磊", "高瓴", "长期主义", "中文经典"],
        "tickers": ["0700.HK", "JD", "MEIT"],
        "era": "classic_cn",
        "difficulty": "intermediate",
    },

]


def all_classics() -> List[Dict[str, Any]]:
    """Return classic entries. Wrapped so callers don't mutate the const."""
    return list(CLASSICS)
