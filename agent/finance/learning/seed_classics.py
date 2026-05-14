"""Memos / speeches / shareholder-letter digests — kind='memo'.

Three sibling seed files in this directory:
  - seed_cases.py    — kind='case': event-driven case studies
  - seed_classics.py — kind='memo': short-form essays, speeches,
                       letters, blog posts (this file)
  - seed_books.py    — kind='book': actual books, with availability
                       (public_domain / free_web / paid) + read-or-
                       purchase URL

Memos here are short pieces (1-30 page transcripts / single articles)
that are entirely free to read at the source URL. Books that contain
collections of memos (Berkshire shareholder letters, Marks memo
archive, 段永平 雪球 留言精选) live in seed_books.py under kind='book'
so the user can browse them as books too.

Selection criteria:
  - Public source URL (no paywall).
  - Each digest is the ESSENCE — lead with the takeaway, then
    explain.

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
        "source_url": "https://fs.blog/great-talks/a-lesson-on-worldly-wisdom/",
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

    # ── Peter Lynch / Beating the Street ──────────────────────────

    # ── Ben Graham / 价值投资始祖 ──────────────────────────────────

    # ── Damodaran (NYU) ──────────────────────────────────────────────

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

]


def all_classics() -> List[Dict[str, Any]]:
    """Return classic entries. Wrapped so callers don't mutate the const."""
    return list(CLASSICS)
