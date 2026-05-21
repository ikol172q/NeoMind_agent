"""Curated whale profile encyclopedia — bilingual (中/EN).

Hand-written background you need to LEARN from each operator: their
strategy, big wins, big losses (often more instructive than wins),
quirks, and primary sources to follow them over time.

Augmentation strategy:
- This file holds the slow-changing curated content.
- /api/regime/whales/{key}/profile JOINs this with:
   · live 13F latest moves (from your signal_events)
   · live Tavily web search results (recent news)
   · current style/horizon/bias from whale_scanner.WHALES

Adding more whales:
- Top 13 curated below. Add a new entry by following the schema.
- If a whale_key is missing here, the API returns curated=None and
  the UI shows just the live data + a "no curation yet" notice.

User intent (2026-05-19):
- Bilingual for clear understanding
- Include FAILURES on equal footing with successes
- Anchored sources (letters_url, books, X handles) for future updates
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class _BilingualStr(TypedDict, total=False):
    zh: str
    en: str


class _Event(TypedDict, total=False):
    year: str
    title_zh: str
    title_en: str
    body_zh: str
    body_en: str


class _Quirk(TypedDict, total=False):
    title_zh: str
    title_en: str
    body_zh: str
    body_en: str


class _Link(TypedDict, total=False):
    type: str        # 'letters' | 'book' | 'interview' | 'podcast' | 'wiki' | 'x' | 'paper'
    label: str
    url: str


class _Profile(TypedDict, total=False):
    summary: _BilingualStr
    strategy: _BilingualStr        # 2-3 paragraphs deep-dive
    wins: List[_Event]              # famous trades / decisions that worked
    losses: List[_Event]            # equally instructive failures
    must_know: List[_Quirk]         # quirks / biases / unique features
    links: List[_Link]


# ────────────────────────────────────────────────────────────────────


PROFILES: Dict[str, _Profile] = {

    # ═══════════════════════════════════════════════════════════════
    "buffett": {
        "summary": {
            "zh": "全球最著名的价值投资者; 集中持有, 永远不卖. 73年股神, 从纺织厂到 $9000 亿帝国.",
            "en": "World's most famous value investor; concentrated holds forever. 73-year track record turning a textile mill into a $900B empire.",
        },
        "strategy": {
            "zh": (
                "**核心**: Margin of Safety + Compound Forever. 只买「看得懂」的伟大企业, 在估值「合理」时进场, "
                "然后 hold 几十年让复利做事. 不预测市场, 不做日内, 不做衍生品 (除非超大尺度).\n\n"
                "**圈子**: 早期严格价值 (Graham 系); 1990s 后接受了「以合理价格买伟大公司」(Munger 影响). 关键转折点是 1988 Coca-Cola, "
                "他第一次为「品牌护城河」付了一个看似不便宜的价格. 2016 AAPL 是第二次转折 — 终于接受了科技股, 但只买他能理解的消费电子.\n\n"
                "**心态**: 极度耐心 + 极度集中. 持仓 90 家公司里, top 10 占 80%+ AUM. 名言: \"Our favorite holding period is forever.\""
            ),
            "en": (
                "**Core**: Margin of safety + compound forever. Only buy 'great businesses you understand' at reasonable prices, "
                "then hold for decades letting compounding work. Doesn't predict markets, doesn't day-trade, avoids derivatives "
                "(except at massive scale).\n\n"
                "**Circle**: Early strict-value (Graham school); from 1990s onward embraced 'wonderful company at fair price' "
                "(Munger's influence). Pivotal moment: 1988 Coca-Cola, his first time paying a seemingly-rich price for a brand moat. "
                "2016 AAPL was the second pivot — finally accepted tech, but only consumer electronics he understood.\n\n"
                "**Temperament**: Extreme patience + extreme concentration. ~90 holdings; top 10 = 80%+ AUM. Quote: 'Our favorite "
                "holding period is forever.'"
            ),
        },
        "wins": [
            {"year": "1988", "title_zh": "可口可乐 — 第一次付溢价", "title_en": "Coca-Cola — first time paying up",
             "body_zh": "$1.3B 买入, 至今未卖. 35 年里收到分红超过买入本金 6 倍, 持仓市值 ~$25B. 教训: 伟大品牌的复利价值远超价值派的「便宜」定义.",
             "body_en": "$1.3B initial buy, never sold. Over 35 years, dividends alone exceeded initial cost 6×; position now ~$25B. Lesson: Compound value of great brands far exceeds the value-school's 'cheap' definition."},
            {"year": "2016", "title_zh": "AAPL — 史上最大单笔投资", "title_en": "AAPL — largest single investment ever",
             "body_zh": "从 $30B 加到 $160B 峰值, 占 BRK 投资组合 50%+. 一改'不懂科技股不买'的几十年原则. 关键判断: AAPL 是消费电子+生态护城河, 不是技术周期股. 2024 后逐步减仓 (税收+集中度).",
             "body_en": "Built from $30B to $160B peak, 50%+ of BRK portfolio at peak. Broke decades-old 'no tech' rule. Key insight: AAPL is consumer electronics + ecosystem moat, NOT a tech cycle stock. Trimming since 2024 (tax + concentration)."},
            {"year": "2009", "title_zh": "金融危机的 BNSF + GS 救援", "title_en": "Financial crisis: BNSF + GS rescue",
             "body_zh": "2009 全美恐慌时 $44B 全资收购 BNSF 铁路; 同期给 Goldman 注资 $5B (10% 优先股 + 认股权). 教训: 'Be greedy when others are fearful.' 危机就是定价错误最严重的时候.",
             "body_en": "At peak panic in 2009, paid $44B for BNSF railroad outright; same period injected $5B into Goldman (10% preferred + warrants). Lesson: 'Be greedy when others are fearful.' Crises are when mispricing is most extreme."},
        ],
        "losses": [
            {"year": "1989", "title_zh": "USAir — 真正的'value trap'", "title_en": "USAir — true 'value trap'",
             "body_zh": "买了 $358M 优先股, 后股价跌 75%. Buffett 自评: '航空公司根本就不该投资, 我应该看着 Wright 兄弟试飞时把他们打下来'. 教训: 行业结构 (高资本+低 ROIC) 比单家公司质量重要.",
             "body_en": "Bought $358M in preferred, share price -75%. Buffett's own quote: 'Airlines should never have been invested in. I should have shot the Wright brothers'. Lesson: Industry structure (high capex + low ROIC) trumps individual company quality."},
            {"year": "2011-2018", "title_zh": "IBM — 价值陷阱+错过技术拐点", "title_en": "IBM — value trap + missed tech inflection",
             "body_zh": "$10.7B 买入 IBM (2011), 7 年后认输, 减仓损失 ~$1B. 当时 Buffett 说看好 IBM 转型 cloud, 但实际 IBM 转型严重落后 AWS/Azure. 教训: 即使是大象转型, 平台战争不能输得太晚.",
             "body_en": "$10.7B into IBM in 2011, exited at loss ~$1B over 7 years. Bet was on IBM cloud transition; reality was IBM lost the cloud platform war to AWS/Azure. Lesson: Even elephants pivoting matter — platform wars don't reward late entries."},
            {"year": "1993", "title_zh": "Dexter Shoe — 用 BRK 股票收购的代价", "title_en": "Dexter Shoe — paying with BRK stock",
             "body_zh": "用 BRK 股票换购 Dexter ($433M), 公司业务后来归零. Buffett 自评年报: '用变得越来越值钱的钱买了变得不值钱的东西, 那才是真的灾难.' 教训: 用稀缺资本买东西必须更挑剔.",
             "body_en": "Acquired Dexter Shoe using BRK stock ($433M); the company went to zero. Buffett's annual letter mea culpa: 'Paying with increasingly valuable currency for an increasingly worthless asset — that's the real disaster.' Lesson: Even more selective when paying with scarce capital."},
        ],
        "must_know": [
            {"title_zh": "他的接班人 Greg Abel 正在变化 BRK", "title_en": "His successor Greg Abel is reshaping BRK",
             "body_zh": "2024 年 Abel 接 CEO. 2026 年 Q1 BRK 大幅减仓 GOOGL (-80%) 和 AAPL — 这是 Buffett 仍在世但放手的过渡期, **不要把 BRK 的最新动作完全视为 Buffett 个人观点**. 看 Abel 上任后致股东信判断.",
             "body_en": "Abel took CEO in 2024. Q1 2026 BRK heavily trimmed GOOGL (-80%) and AAPL — this is the transition period where Buffett's alive but stepping back. **Don't read latest BRK moves as Buffett's personal view alone**. Track Abel's shareholder letters."},
            {"title_zh": "他的'circle of competence' 比你想的小", "title_en": "His 'circle of competence' is smaller than you think",
             "body_zh": "Buffett 拒绝过 Google IPO, 错过 Amazon 20 年. 他不是没看到 — 是承认看不懂. 'Knowing what you DON'T know.' 这是他成功的核心, 但也是他错过最大复合机会的原因.",
             "body_en": "Buffett passed on the Google IPO, missed Amazon for 20 years. Not blind — he admits he doesn't understand. 'Knowing what you DON'T know.' This is core to his success — and the reason he missed the biggest compounders."},
            {"title_zh": "他的实际操作 ≠ 他的公开建议", "title_en": "His actual trades ≠ his public advice",
             "body_zh": "公开多次推 S&P 500 ETF 给普通人, 但自己永远做集中. 给 BRK 股东的建议: '别学我'. 给 wife 信托的建议: 90% S&P 500. 这种 '我能做但你别做' 的诚实少见也重要.",
             "body_en": "Publicly recommends S&P 500 ETF for retail; runs his own concentrated. Advice to BRK shareholders: 'Don't try to copy me.' His will instructs wife's trust to be 90% S&P 500. Rare and important honesty: 'I can do this, you shouldn't try.'"},
        ],
        "links": [
            {"type": "letters", "label": "Berkshire Annual Letters (1965-2026)", "url": "https://www.berkshirehathaway.com/letters/letters.html"},
            {"type": "book", "label": "The Snowball: Warren Buffett and the Business of Life (Alice Schroeder)", "url": "https://en.wikipedia.org/wiki/The_Snowball:_Warren_Buffett_and_the_Business_of_Life"},
            {"type": "book", "label": "Poor Charlie's Almanack (Munger's wisdom)", "url": "https://en.wikipedia.org/wiki/Poor_Charlie%27s_Almanack"},
            {"type": "wiki", "label": "Wikipedia: Warren Buffett", "url": "https://en.wikipedia.org/wiki/Warren_Buffett"},
            {"type": "interview", "label": "Annual Berkshire Meeting Q&A (CNBC archive)", "url": "https://www.cnbc.com/warren-buffett-archive/"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "klarman": {
        "summary": {
            "zh": "深度价值 + 困境资产专家; 写过《Margin of Safety》(已绝版). 看不到机会时持 30%+ 现金, 极度耐心.",
            "en": "Deep value + distressed specialist; wrote 'Margin of Safety' (out of print). Holds 30%+ cash when no opportunity, extreme patience.",
        },
        "strategy": {
            "zh": (
                "**核心**: 找'被定价错的复杂资产' — 破产债权、特殊情况、被遗忘的小盘. 不是看 PE 低就买, 而是看 risk/reward 严重不对称.\n\n"
                "**资本结构**: Baupost ~$30B AUM, 极度低调, 不接受新投资者多年. LP 主要是大学 endowment + 家族办公室. 锁定期 5 年 → "
                "可以做长达数年的不流动 distressed 头寸.\n\n"
                "**性格**: 写信很谨慎, 几乎不公开露面. 1991 自费出版《Margin of Safety》, 后来'不愿继续印刷' — 二手书炒到 $2000+. "
                "想读他的思想: 学他书的电子版 + 偶尔的 Sohn Conference 演讲."
            ),
            "en": (
                "**Core**: Find 'mispriced complex assets' — bankruptcy claims, special situations, forgotten small caps. Not just 'low PE = buy', "
                "but severely asymmetric risk/reward.\n\n"
                "**Capital structure**: Baupost ~$30B AUM, extremely low profile, closed to new investors for years. LPs mostly university "
                "endowments + family offices. 5-year lockup → enables multi-year illiquid distressed positions.\n\n"
                "**Personality**: Writes letters cautiously, almost never appears publicly. Self-published 'Margin of Safety' (1991), later "
                "stopped reprinting — used copies trade for $2000+. To learn from him: read leaked PDFs of the book + occasional Sohn talks."
            ),
        },
        "wins": [
            {"year": "1980-90s", "title_zh": "美国储贷危机 (S&L Crisis)", "title_en": "U.S. Savings & Loan Crisis",
             "body_zh": "1980s 末美国储贷危机, 政府接管几千家银行. Baupost 买入 RTC (清算公司) 卖出的资产包, 几年内回报数倍. 教训: 监管驱动的资产抛售 = 价值挖掘机会.",
             "body_en": "Late 1980s S&L crisis, govt took over thousands of banks. Baupost bought asset packages from RTC (Resolution Trust Corp), multi-bagger returns in 3-5 years. Lesson: Regulatory-forced asset sales = deep value opportunities."},
            {"year": "2008-2009", "title_zh": "金融危机 distressed 信用", "title_en": "2008-09 Distressed Credit",
             "body_zh": "金融危机时 Baupost 持有大量 cash, 危机后大笔买入 distressed mortgage securities + 银行优先股. 2010-2011 翻倍. 教训: 危机前的耐心 = 危机中的购买力.",
             "body_en": "Held large cash going INTO the crisis. Post-crisis, bought distressed mortgage securities + bank preferreds at fire-sale prices. Doubled by 2010-2011. Lesson: Patience pre-crisis = buying power in crisis."},
            {"year": "2013", "title_zh": "Tribune Co — 报纸 distressed 翻身", "title_en": "Tribune Co — newspaper distressed turnaround",
             "body_zh": "买入破产中的 Tribune (LA Times 母公司) 债权, 重组后分到股权 + 房地产, 长期持有获得多倍回报. 复杂的多层资本结构很多人不愿研究, Klarman 反而见到机会.",
             "body_en": "Bought Tribune debt in bankruptcy (LA Times parent), got equity + real estate post-restructure, held long-term for multi-bagger. Complex multi-layer capital stack most won't study — Klarman saw opportunity there."},
        ],
        "losses": [
            {"year": "2014-2018", "title_zh": "Pyxus International (烟草农业)", "title_en": "Pyxus International (tobacco agriculture)",
             "body_zh": "传统 deep value 买入烟草供应链公司, 但 ESG 资金外流 + 行业结构性萎缩, 持仓多年大幅缩水. 教训: 即使 'cheap on paper', 行业 secular decline 会吞噬一切价值.",
             "body_en": "Classic deep-value buy into a tobacco supply chain firm, but ESG outflows + secular industry decline ate position over years. Lesson: Even 'cheap on paper' can't survive secular industry decline."},
            {"year": "2011-2015", "title_zh": "BP — 'doctrine' 失误", "title_en": "BP — 'doctrine' miss",
             "body_zh": "BP 漏油事件后 Klarman 大手买入, 押法律责任有限 + 资产价值 floor. 几年下来法律责任远超预期, 股价多年低迷. 教训: 'doctrinal' (法律理论上的)上限 ≠ 实际责任上限.",
             "body_en": "Heavily bought BP after the oil spill, betting legal liability had a cap + asset value floor. Years later, legal liability massively exceeded expectations; price stayed flat for years. Lesson: 'Doctrinal' (legal theoretic) cap ≠ actual liability cap."},
        ],
        "must_know": [
            {"title_zh": "对当前 AI 行情有意见", "title_en": "Has views on current AI rally",
             "body_zh": "Klarman 2024-2025 letters 已暗示对'AI 估值'警惕, 但不公开 short. 不要默认他在 NVDA/AAPL 上反向 — 但他的进场严选会让他在 mega-cap tech 缺席.",
             "body_en": "Klarman's 2024-2025 letters hinted at caution on 'AI valuations' but doesn't publicly short. Don't assume he's opposite-side on NVDA/AAPL — his strict entry criteria simply make him absent from mega-cap tech."},
            {"title_zh": "他的书《Margin of Safety》读起来比表面深", "title_en": "His book 'Margin of Safety' is deeper than it looks",
             "body_zh": "不是讲 PE 比率, 而是讲思维模型 — 如何对决策不确定性建模, 如何接受不知道, 如何在缺乏信息时使用保守边界. 跟 Munger 的 mental models 是姊妹篇.",
             "body_en": "Not about PE ratios — about mental models for handling decision uncertainty, accepting not-knowing, using conservative bounds when info is sparse. Sister text to Munger's mental models."},
        ],
        "links": [
            {"type": "book", "label": "Margin of Safety (1991, OOP) — leaked PDFs widely available", "url": "https://en.wikipedia.org/wiki/Margin_of_Safety_(book)"},
            {"type": "wiki", "label": "Wikipedia: Seth Klarman", "url": "https://en.wikipedia.org/wiki/Seth_Klarman"},
            {"type": "wiki", "label": "Wikipedia: Baupost Group", "url": "https://en.wikipedia.org/wiki/The_Baupost_Group"},
            {"type": "interview", "label": "Sohn Investment Conference talks (search)", "url": "https://www.sohnconference.org/"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "marks": {
        "summary": {
            "zh": "Oaktree 创始人, 长期写 memos 几十年, 主题: 市场周期 + 投资者心理学.",
            "en": "Founder of Oaktree, decades of memos focused on market cycles + investor psychology.",
        },
        "strategy": {
            "zh": (
                "**核心**: '你预测不了, 但你能准备'. 不预测市场涨跌, 而是问 '我们现在在周期的什么位置, 我的仓位是否反映这个位置.'\n\n"
                "**Oaktree**: 信用主导基金 (~$170B AUM), 专精 distressed debt. 实际 13F (美股) 是他们的小子集; 大头在欧亚信用市场.\n\n"
                "**写作**: 1990 年开始写 memo, 现在每年 5-6 篇, 是机构投资人必读. 不是给散户的鸡汤, 是 PE/HF 高管圈认真讨论的素材. "
                "Buffett 公开说 Marks 是他每个 memo 必读的人."
            ),
            "en": (
                "**Core**: 'You can't predict, but you can prepare.' Doesn't forecast market direction, asks 'where are we in the cycle "
                "and does my positioning reflect that?'\n\n"
                "**Oaktree**: Credit-focused fund (~$170B AUM), specialty in distressed debt. The 13F (US equities) is a small subset; "
                "bulk is in Euro/Asia credit markets.\n\n"
                "**Writing**: Started memos in 1990, now 5-6/year, required reading for institutional investors. Not retail-pop content "
                "— what PE/HF principals seriously discuss. Buffett has publicly said Marks is his must-read."
            ),
        },
        "wins": [
            {"year": "2008", "title_zh": "Distressed debt 在金融危机的部署", "title_en": "Distressed deployment in financial crisis",
             "body_zh": "Oaktree 2007 年清盘旧基金等待时机; 2008 年 9-10 月雷曼倒后大举进场 distressed bonds. 几年回报 80%+. 教训: 信用周期顶点之前先变现, 然后等危机里部署.",
             "body_en": "Oaktree wound down old fund in 2007 to wait; deployed massively into distressed bonds Sep-Oct 2008 post-Lehman. Multi-year returns 80%+. Lesson: Liquidate before credit cycle top, deploy in the crisis."},
            {"year": "2014-2016", "title_zh": "能源/大宗商品 distressed", "title_en": "Energy/commodity distressed",
             "body_zh": "油价从 $100 跌到 $30, Oaktree 部署在能源公司 distressed debt. 2017-2018 油价反弹收割回报. 教训: 周期看的不是单一价格, 是估值与基本面比.",
             "body_en": "Oil dropped from $100 to $30; Oaktree deployed in energy company distressed debt. Reaped returns as oil bounced 2017-2018. Lesson: Cycles aren't just price — it's valuation relative to fundamentals."},
        ],
        "losses": [
            {"year": "2015-2017", "title_zh": "新兴市场亚洲信贷判断保守", "title_en": "Conservative on EM Asian credit",
             "body_zh": "Marks 看空亚洲信贷已数年, 但 EM 信贷在 2014-2018 整体表现强劲. 教训: 周期判断可以对, 但 timing 可以错很久 — 持续看空意味着错过中间的实质收益.",
             "body_en": "Marks bearish on Asian credit for years; EM credit actually delivered strong returns 2014-2018. Lesson: Cycle calls can be right but timing wrong for years — persistent bearishness means missing real intermediate gains."},
        ],
        "must_know": [
            {"title_zh": "他的 memo 比他的基金回报更出名", "title_en": "His memos are more famous than his fund returns",
             "body_zh": "Oaktree 净回报对 LP 不算顶级 (年化 ~12-13%, 高于市场但低于明星 HF). 你跟着他学的是 thinking framework, 不是 trade-following.",
             "body_en": "Oaktree net returns to LPs aren't top-tier (~12-13% annualized, beats market but trails star HFs). What you learn from him is thinking framework, NOT trade-following."},
            {"title_zh": "「pendulum」是他的核心隐喻", "title_en": "'Pendulum' is his core metaphor",
             "body_zh": "市场情绪在 fear → greed 之间像钟摆来回. 投资者要做的不是预测钟摆停哪, 而是逆着钟摆当前方向调仓. 简单但实战极难做到.",
             "body_en": "Market sentiment swings between fear and greed like a pendulum. Investors don't predict where it stops — they position AGAINST current direction. Simple but extremely hard in practice."},
        ],
        "links": [
            {"type": "letters", "label": "Howard Marks Memos (full archive 1990-present)", "url": "https://www.oaktreecapital.com/insights/howard-marks-memos"},
            {"type": "book", "label": "The Most Important Thing (2011)", "url": "https://en.wikipedia.org/wiki/The_Most_Important_Thing_(book)"},
            {"type": "book", "label": "Mastering the Market Cycle (2018)", "url": "https://en.wikipedia.org/wiki/Mastering_the_Market_Cycle"},
            {"type": "wiki", "label": "Wikipedia: Howard Marks (investor)", "url": "https://en.wikipedia.org/wiki/Howard_Marks_(investor)"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "grantham": {
        "summary": {
            "zh": "GMO 联合创始人, 知名 '泡沫预言家'. 喊过 2000 互联网、2008 房地产、2022 'super bubble' 3 次大顶. 当前 (2024-2026) 喊 AI 泡沫.",
            "en": "GMO co-founder, famous 'bubble caller'. Called 2000 dot-com, 2008 housing, 2022 'super bubble' tops. Currently (2024-2026) calling AI bubble.",
        },
        "strategy": {
            "zh": (
                "**核心**: Mean reversion 是市场的'重力'. 估值偏离均值 → 终归回归. 不预测精确顶, 但**预测均值回归的方向和幅度.\n\n"
                "**GMO**: 资产配置基金 (~$60B AUM), 不是单一选股. 他的策略是降低 US equity 暴露、加 EM + 高质量 value. 对个人投资者: 看他 quarterly letters 学 framework, 不要直接 copy 配置 (你不能像 GMO 那样跨资产平衡).\n\n"
                "**对 AI-tech 集中持仓者的关键**: 重仓 AI tech 是单方向 bet. Grantham 是**必须 audit** 的反向声音 = '应该看的对立证据', 不是 '应该跟随的人'."
            ),
            "en": (
                "**Core**: Mean reversion is market 'gravity'. Valuations deviate from mean → must eventually return. Doesn't predict "
                "exact tops, but **predicts direction + magnitude of reversion**.\n\n"
                "**GMO**: Asset allocation fund (~$60B AUM), not single-stock. Strategy is to reduce US equity exposure, add EM + "
                "high-quality value. For retail: read his quarterly letters for framework, don't directly copy allocation (you can't "
                "rebalance across assets like GMO can).\n\n"
                "**Key for YOU**: Your heavy AI tech is a one-way bet. Grantham is the contrarian voice you **must audit**. He's "
                "'opposing evidence I should review', NOT 'someone I should follow'."
            ),
        },
        "wins": [
            {"year": "2000", "title_zh": "互联网泡沫顶 — 连续多年看空 tech 后被证明对", "title_en": "Dot-com top — bearish tech years before, vindicated",
             "body_zh": "1997-1999 Grantham 连续两年称 tech 是泡沫, GMO 重仓 value + EM. 1998-1999 跑输市场 30%+. 客户大量赎回 — 然后 2000-2002 tech 崩盘, 他的 framework 一战封神. 教训: '对' 和 '及时' 是两件事.",
             "body_en": "1997-1999 Grantham called tech a bubble years in advance, GMO positioned in value + EM. Underperformed by 30%+ in 1998-1999; clients pulled money — then 2000-2002 tech crashed, his framework was legendary. Lesson: 'Right' and 'on time' are different things."},
            {"year": "2007", "title_zh": "美国房地产次贷预警", "title_en": "U.S. housing/subprime warning",
             "body_zh": "2006-2007 letters 持续警告房地产 + 信贷扩张过度. 2008 危机后 GMO 部署在 distressed credit 获利可观. 这次和 2000 不同的是: 他 timing 几乎对.",
             "body_en": "2006-2007 letters consistently warned on housing + credit expansion. Post-2008 crisis, GMO deployed in distressed credit and profited substantially. Unlike 2000, this time his timing was almost spot-on."},
        ],
        "losses": [
            {"year": "2010-2020", "title_zh": "2010s 整个十年 underperform", "title_en": "Underperformed the entire 2010s decade",
             "body_zh": "金融危机后 Grantham 持续警告 'overvalued', 但 QE 时代 US growth stocks 翻倍再翻倍. GMO 7-year forecasts 持续负数, 持续被打脸. 客户 AUM 缩水. 教训: 长期对的人不一定每个十年都对.",
             "body_en": "Post-2008, Grantham kept warning 'overvalued', but in the QE era US growth stocks doubled and doubled again. GMO's 7-year forecasts stayed negative, kept getting beaten. AUM shrunk. Lesson: Long-term right doesn't mean every-decade right."},
            {"year": "2022-2024", "title_zh": "「Super bubble」看空 — 部分对 + 反弹超预期", "title_en": "'Super bubble' call — partly right + reversion overshoot",
             "body_zh": "2022 年初 Grantham 喊 'super bubble'. 当年 SPX -19%, NASDAQ -33%, 部分对. 但 2023-2024 反弹超过历史前高, 他的 framework 没预测到 AI capex 的力度. 教训: 即使 framework 对, 黑天鹅 (AI) 可以暂时压倒它.",
             "body_en": "Early 2022 Grantham called 'super bubble'. That year SPX -19%, NASDAQ -33%, partly vindicated. But 2023-2024 rallied past prior highs; framework didn't predict the AI capex force. Lesson: Even a right framework can be temporarily overpowered by a black swan (AI)."},
        ],
        "must_know": [
            {"title_zh": "他 87 岁了, 不是想退休的语调", "title_en": "He's 87 and writes like he won't retire",
             "body_zh": "2026 年仍在写, 风格越来越直接, 越来越关心气候+AI风险, 不再纯估值视角. 他的 quarterly letters 现在带有遗产 (legacy) 写作的味道.",
             "body_en": "Still writing in 2026, style increasingly direct, increasingly focused on climate + AI risks, not pure valuation. His quarterly letters now carry a legacy-writing tone."},
            {"title_zh": "最关键: 他没说'AI 全错', 他说'估值过高'", "title_en": "Key point: He doesn't say AI is wrong, he says valuations are too high",
             "body_zh": "Grantham 公开承认 AI 是真技术革命, 但他的论点是'真革命也会有泡沫', 类似 1990s 互联网 = 真的, NASDAQ 5000 = 泡沫. 不要把他当 anti-AI; 当 anti-overvaluation.",
             "body_en": "Grantham publicly acknowledges AI is a real revolution. His argument is 'real revolutions still have bubbles' — like 1990s internet was real, NASDAQ 5000 was bubble. Don't think of him as anti-AI; think anti-overvaluation."},
        ],
        "links": [
            {"type": "letters", "label": "GMO Quarterly Letters", "url": "https://www.gmo.com/americas/research-library/"},
            {"type": "interview", "label": "Grantham 2024 'Super Bubble' interviews (search YouTube)", "url": "https://www.youtube.com/results?search_query=Jeremy+Grantham+super+bubble+2024"},
            {"type": "wiki", "label": "Wikipedia: Jeremy Grantham", "url": "https://en.wikipedia.org/wiki/Jeremy_Grantham"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "hussman": {
        "summary": {
            "zh": "估值学派 '永远 bear' 代表; 2009 后基本错过整个牛市. 但他的 framework 严谨, 是你 thesis 的诚实压力测试.",
            "en": "Valuation school 'perma-bear'; missed most of the bull market since 2009. But his framework is rigorous and a serious stress test for your thesis.",
        },
        "strategy": {
            "zh": (
                "**核心**: 他的 'Margin-Adjusted CAPE' (调整后的 Shiller PE) 指标当前 (2025) 在历史最高位, 比 1929 + 2000 + 2007 都高. "
                "据此他的基金长期空头.\n\n"
                "**问题**: 他的预测在 2009-2020 几乎一直错, AUM 大幅缩水. 但他持续公开 + 详细解释为什么. 这种诚实是稀缺的.\n\n"
                "**价值**: 重仓 AI 时, 读 Hussman 周评 = 强制接触'估值视角'. 他可能错, 但他的论证必须能被反驳."
            ),
            "en": (
                "**Core**: His 'Margin-Adjusted CAPE' (modified Shiller PE) is at all-time high in 2025, exceeding 1929 + 2000 + 2007. "
                "Based on this, his funds are persistently bearish/hedged.\n\n"
                "**Problem**: His forecasts were almost continuously wrong 2009-2020; AUM shrunk dramatically. But he keeps publishing "
                "+ explaining why in detail. That honesty is rare.\n\n"
                "**Value to you**: When you're heavy AI, reading Hussman weekly = forced exposure to 'valuation perspective'. He may be "
                "wrong, but you must be able to refute his arguments."
            ),
        },
        "wins": [
            {"year": "2000", "title_zh": "互联网泡沫前后期 hedged", "title_en": "Dot-com bubble — hedged into the crash",
             "body_zh": "1999-2000 期间 Hussman 基金大幅 hedged, 2000-2002 跌市中表现优异. 历史最佳时刻, 之后多年没有重现.",
             "body_en": "1999-2000 funds were heavily hedged, outperformed massively during 2000-2002 crash. His best moment historically, never repeated since."},
            {"year": "2007-2008", "title_zh": "金融危机前防御", "title_en": "Defensive before financial crisis",
             "body_zh": "2007 年开始减仓 + hedge, 2008 危机中基金跌幅小于市场. 之后又陷入 '永远 bear' 困局.",
             "body_en": "Started reducing + hedging in 2007, fund drawdown was less than market in 2008. Then fell back into 'perma-bear' trap."},
        ],
        "losses": [
            {"year": "2009-2024", "title_zh": "15 年错过整个牛市", "title_en": "Missed an entire 15-year bull market",
             "body_zh": "Strategic Growth Fund 从 2009 年开始, 年化大约 1-3%, 同期 SPX ~13% 年化. 客户 AUM 从 $7B 缩到 $400M. 教训: 'Right framework' + 'Wrong regime' 可以摧毁 fund.",
             "body_en": "Strategic Growth Fund from 2009 onwards: ~1-3% annualized vs SPX ~13% annualized. AUM shrank from $7B to $400M. Lesson: 'Right framework' + 'Wrong regime' can destroy a fund."},
        ],
        "must_know": [
            {"title_zh": "为啥还要读他?", "title_en": "Why read him at all?",
             "body_zh": "他持续输不代表他的 framework 错 — 可能代表 framework 对但 regime 改变 (QE/AI capex 是新的力量). 你要的是 framework: 当估值这么极端时, 任何 mean-reversion 都会很疼. 这是你 hedge plan 的输入.",
             "body_en": "His persistent losses don't mean his framework is wrong — could mean framework is right but regime changed (QE/AI capex are new forces). What you want is the framework: at this extreme valuation, ANY mean reversion will hurt badly. This is input to your hedge plan."},
            {"title_zh": "他不卖空个股, 他卖空指数", "title_en": "Doesn't short individual stocks, shorts index",
             "body_zh": "Hussman 通过 SPX put / 空指数对冲, 不是分析单家公司. 不要期望他给出 NVDA 或 META 的个股看法.",
             "body_en": "Hussman hedges via SPX puts / index shorts, doesn't analyze individual companies. Don't expect his views on NVDA or META."},
        ],
        "links": [
            {"type": "letters", "label": "Weekly Market Commentary (Hussman Funds)", "url": "https://www.hussmanfunds.com/comment/"},
            {"type": "interview", "label": "Hussman interview archives", "url": "https://www.hussmanfunds.com/category/in-the-news/"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "druckenmiller": {
        "summary": {
            "zh": "Stanley Druckenmiller, 历史上最稳定的宏观对冲基金经理, 30 年无负回报年. 现在是 family office (Duquesne), 自由发声.",
            "en": "Stanley Druckenmiller, most consistent macro hedge fund manager in history — 30 years without a down year. Now family office (Duquesne), speaks freely.",
        },
        "strategy": {
            "zh": (
                "**核心**: 'Never invest in the present. The picture has to be 18 months out.' 主题驱动 + 集中下注 + 愿意 flip 180°.\n\n"
                "**经典模板**: 看到大趋势 → 用集中头寸 + 杠杆下注 → 错了立刻平 → 对了加码. 他自己说: '不是我有多对, 是我对的时候 size 够大, 错的时候认输够快.'\n\n"
                "**最关键的事**: 他敢空仓. Duquesne 历史上多次拿 60%+ cash 等待时机. 这是大多数基金经理因业绩压力做不到的."
            ),
            "en": (
                "**Core**: 'Never invest in the present. The picture has to be 18 months out.' Theme-driven + concentrated + willing to flip 180°.\n\n"
                "**Classic template**: See big trend → bet via concentrated position + leverage → wrong, cut immediately → right, add. "
                "His quote: 'It's not that I'm so right — it's that when I'm right I size big, when I'm wrong I quit fast.'\n\n"
                "**Critical**: He's not afraid of cash. Duquesne historically held 60%+ cash waiting for setups. Most fund managers "
                "can't do this due to performance pressure."
            ),
        },
        "wins": [
            {"year": "1992", "title_zh": "破英镑 — 与 Soros 的合作", "title_en": "Breaking the Pound — partnership with Soros",
             "body_zh": "Druckenmiller 是 Soros Quantum Fund 当时的实际 trade 操盘手. 1992 年看到英国试图维持 ERM 汇率不可持续, 一周内卖空英镑 $10B+, 单日盈利 $1B+. 教训: 当政府政策与经济基本面冲突时, 政府终归输.",
             "body_en": "Druckenmiller was the actual trade operator at Soros Quantum Fund at the time. Saw UK's ERM peg as unsustainable in 1992; shorted GBP $10B+ in a week, made $1B+ in a day. Lesson: When govt policy fights fundamentals, govt eventually loses."},
            {"year": "1999", "title_zh": "互联网 long → 顶部空, 半年赚 $1B", "title_en": "Internet long → top short, made $1B in 6 months",
             "body_zh": "1999 中期他改为重仓 tech long, 半年赚 35%. 然后到 2000 年 4 月看到顶, 几周内反向重空 — 但这次时机错了, 他 short 在底部上方反弹时被打损了 5 亿. 教训: 大趋势的最后 inning 最危险, 即使方向对.",
             "body_en": "Mid-1999 went heavily long tech, made 35% in 6 months. Then April 2000 saw the top, reversed to short within weeks — but timing was wrong, got squeezed for $500M. Lesson: Last inning of a megatrend is the most dangerous, even if direction is right."},
            {"year": "2020", "title_zh": "新冠后转 gold + crypto + tech", "title_en": "Post-COVID: gold + crypto + tech",
             "body_zh": "2020 年 3 月底 Fed 开 QE 后, 他立刻看出'通胀 + 美元贬值'故事, 大量加仓黄金 + bitcoin + 持续 long tech. 2021 年获利可观.",
             "body_en": "Late March 2020 once Fed announced QE, immediately saw 'inflation + dollar devaluation' story. Loaded into gold + bitcoin + continued long tech. Substantial profit in 2021."},
        ],
        "losses": [
            {"year": "2000", "title_zh": "互联网顶部反转太早", "title_en": "Internet top — reversed too early",
             "body_zh": "见上 wins 中, $500M 损失是顶部反转 timing 失误. 这是他职业生涯中最痛苦的一年, 他自己说 '是我做交易的一个低点'.",
             "body_en": "See above wins — $500M loss from mistimed top reversal. His most painful year; he says 'a low point in my trading career'."},
            {"year": "2022", "title_zh": "看错通胀回落速度", "title_en": "Misjudged inflation pullback speed",
             "body_zh": "2022 年初 short equity + long inflation hedge, 部分对. 但 2023 年 inflation 回落比他预期快, 美股反弹超预期. Duquesne 错过部分反弹. 教训: 即使大方向对, regime 切换的速度可以做空 timing 失误.",
             "body_en": "Early 2022 short equity + long inflation hedge, partly right. But 2023 inflation cooled faster than he expected, equity rallied harder. Duquesne missed part of the rebound. Lesson: Even right direction, regime-switch speed can break timing."},
        ],
        "must_know": [
            {"title_zh": "他 2024-2026 重仓 AI 半导体", "title_en": "Heavy in AI semis 2024-2026",
             "body_zh": "5/15 13F: 新建 ARM/AVGO/MU/TSM (AI 半导体方向). 但 GOOGL 清仓. 值得思考: 为什么要 ARM 但不要 GOOGL?",
             "body_en": "5/15 13F: New positions in ARM/AVGO/MU/TSM, aligns with your direction. But exited GOOGL. Think: why does he want ARM but not GOOGL?"},
            {"title_zh": "他自由发声 (不再管理外部 LP)", "title_en": "Speaks freely (no longer manages outside LPs)",
             "body_zh": "2010 关闭对外基金后, Druckenmiller 在 CNBC/podcasts 上很愿意分享 thesis. 不像 Klarman/Marks 那么收敛. 跟着他比跟着 Buffett 有时更有信息量.",
             "body_en": "After closing outside fund in 2010, Druckenmiller is willing to share thesis on CNBC/podcasts. Less guarded than Klarman/Marks. Sometimes more informational to follow than Buffett."},
        ],
        "links": [
            {"type": "interview", "label": "Druckenmiller CNBC archive", "url": "https://www.cnbc.com/stanley-druckenmiller/"},
            {"type": "podcast", "label": "Druckenmiller on 'Invest Like the Best' (Patrick O'Shaughnessy)", "url": "https://www.joincolossus.com/episodes/"},
            {"type": "wiki", "label": "Wikipedia: Stanley Druckenmiller", "url": "https://en.wikipedia.org/wiki/Stanley_Druckenmiller"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "leopold": {
        "summary": {
            "zh": "Leopold Aschenbrenner, 27 岁创立 Situational Awareness LP (2024). AGI 2027-2030 thesis 公开发表'Situational Awareness'长文. ~$1.5B AUM.",
            "en": "Leopold Aschenbrenner, age 27 founded Situational Awareness LP (2024). AGI by 2027-2030 thesis published in 'Situational Awareness' essay. ~$1.5B AUM.",
        },
        "strategy": {
            "zh": (
                "**核心论点**: AGI 在 2027-2030 出现 → 万亿美元算力建设 → AI 半导体 + AI 电力基础设施 都将大幅重新定价.\n\n"
                "**仓位结构**: 13F 显示集中在 AI 半导体 (NVDA / AVGO / MU / TSM / AMD). 但他公开 thesis 大头是 power/grid (CEG / VST / TLN / "
                "BWXT). 这部分 13F 不显示 — 大概率通过 swap 持仓. 估计真实暴露 13F 只能看到 50%.\n\n"
                "**背景**: 前 OpenAI Superalignment team 研究员, 2024 年 4 月被解雇, 6 月发表长文 (situational-awareness.ai 整个网站). "
                "投资者: Collison 兄弟 (Stripe) + Daniel Gross + Nat Friedman."
            ),
            "en": (
                "**Core thesis**: AGI by 2027-2030 → $T-scale compute buildout → AI semis + AI power infrastructure both massively rerated.\n\n"
                "**Positioning**: 13F shows concentration in AI semis (NVDA / AVGO / MU / TSM / AMD). But his public thesis is heavy on "
                "power/grid (CEG / VST / TLN / BWXT). That part doesn't show in 13F — likely held via swaps. Estimate visible 13F = "
                "~50% of true exposure.\n\n"
                "**Background**: Former OpenAI Superalignment researcher, fired April 2024, published essay June 2024 (entire "
                "situational-awareness.ai site). Investors: Collison brothers (Stripe) + Daniel Gross + Nat Friedman."
            ),
        },
        "wins": [
            {"year": "2024 H2", "title_zh": "Q1 2026 之前 AVGO trade 抓住涨势", "title_en": "Caught AVGO rally before Q1 2026",
             "body_zh": "Q2 2025 新建 AVGO 700k 股, Q3 加仓 70% 到 1.19M 股, Q4 减仓 80% 到 230k 股. AVGO 在这期间上涨 + 期间利润. 但同期 Q4 2025 清仓 + Q1 2026 又新建 — 显示他根据估值在频繁 rotate, 不是 buy-and-hold.",
             "body_en": "Q2 2025 new AVGO 700k shares, Q3 added 70% to 1.19M, Q4 trimmed 80% to 230k. AVGO appreciated during this period. But same period Q4 exit + Q1 2026 re-entry — suggests valuation-based rotation, NOT buy-and-hold."},
        ],
        "losses": [
            {"year": "TBD", "title_zh": "策略未经过完整周期考验", "title_en": "Strategy unproven through full cycle",
             "body_zh": "基金成立 18 个月, 大部分时间在 AI 上涨周期里. 没经过 AI bear market. AGI thesis 如果到 2027 没兑现 → 基金 + 论文都将面临考验.",
             "body_en": "Fund is 18 months old, mostly during AI bull period. Hasn't faced AI bear market. If AGI thesis doesn't materialize by 2027 → fund + manifesto will be tested."},
        ],
        "must_know": [
            {"title_zh": "他的'Situational Awareness'长文是必读", "title_en": "His 'Situational Awareness' essay is must-read",
             "body_zh": "150+ 页, 详细推演 AGI 时间线 + 算力需求 + 能源需求 + 地缘政治. 不是单纯炒股, 是完整世界观. 对 AI-bull 视角是核心读物, 但 2027 timeline 极其激进.",
             "body_en": "150+ pages, detailed reasoning on AGI timeline + compute demand + energy demand + geopolitics. Not just stock-pitching, full worldview. Aligns with your AI thesis, but he's much more aggressive (2027 timeline)."},
            {"title_zh": "他的 visible 持仓 = ~50% 真实仓", "title_en": "Visible holdings = ~50% true exposure",
             "body_zh": "Power infra (CEG/VST/TLN) 不在 13F. 不要以为他只看好 NVDA 不看好电力 — 完全反过来. 看他的 essay 找真实 thesis 分布.",
             "body_en": "Power infra (CEG/VST/TLN) not in 13F. Don't think he's pro-NVDA anti-power — it's opposite. Read his essay for true thesis distribution."},
            {"title_zh": "他在 Twitter 极活跃", "title_en": "Very active on Twitter/X",
             "body_zh": "@leopoldasch 频繁分享 thesis 更新 + 学术讨论 + 政治 take. 跟着 X 比等季度 13F 信息更及时.",
             "body_en": "@leopoldasch posts frequent thesis updates + academic discussions + political takes. Following his X is more timely than waiting quarterly 13F."},
        ],
        "links": [
            {"type": "paper", "label": "'Situational Awareness' essay (2024) — 150 pages", "url": "https://situational-awareness.ai/"},
            {"type": "x", "label": "@leopoldasch on X (twitter.com)", "url": "https://x.com/leopoldasch"},
            {"type": "interview", "label": "Dwarkesh Patel podcast appearance (June 2024)", "url": "https://www.dwarkeshpatel.com/p/leopold-aschenbrenner"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "ackman": {
        "summary": {
            "zh": "Pershing Square 创始人 Bill Ackman, 高度集中 (8-12 持仓), 'concentrated activist'. 公开活跃于 X, 政治+商业评论.",
            "en": "Pershing Square founder Bill Ackman, extremely concentrated (8-12 holdings), 'concentrated activist'. Publicly very active on X with political + business commentary.",
        },
        "strategy": {
            "zh": (
                "**核心**: 极度集中 + 长持有期 + 选择性活动家. 每个 position 都是几年研究 + 详细 thesis. 不像 Loeb 那么频繁发 poison-pen 信, "
                "他主要在他认为能改变公司方向时介入 (Canadian Pacific, Lowe's).\n\n"
                "**资本**: Pershing Square Tontine (PSTH) 是他用 SPAC 创新尝试 — 失败了, $4B 退还投资者. 但他的主基金继续表现.\n\n"
                "**性格**: 极度自信, 公开承认错误也很坦率. Valeant 2015-2017 是他职业最大灾难, 他写了详细的 mea culpa. 这种透明度在 PM 圈是稀有的."
            ),
            "en": (
                "**Core**: Extreme concentration + long holds + selective activism. Each position is years of research + detailed thesis. "
                "Less frequent than Loeb with poison-pen letters; intervenes when he thinks he can change company direction (Canadian "
                "Pacific, Lowe's).\n\n"
                "**Capital**: Pershing Square Tontine (PSTH) was his SPAC innovation attempt — failed, $4B returned to investors. "
                "Main fund continues to perform.\n\n"
                "**Personality**: Extremely confident, also publicly candid about mistakes. Valeant 2015-2017 was his career's biggest "
                "disaster — he wrote detailed mea culpa. This transparency is rare in PM circles."
            ),
        },
        "wins": [
            {"year": "2010-2014", "title_zh": "Canadian Pacific — 经典 activist 案例", "title_en": "Canadian Pacific — classic activist case",
             "body_zh": "Ackman 14% 仓位 + 换 CEO (Hunter Harrison) + 把效率最差的北美铁路变成最好的. 2014 退出时获利 $2.6B (4x return). 教训: 真活动家不是写信, 是改变 actual operations.",
             "body_en": "Ackman 14% stake + CEO change (Hunter Harrison) + transformed worst-performing North American railroad into best. Exited 2014 with $2.6B profit (4x return). Lesson: Real activism isn't letter-writing, it's changing actual operations."},
            {"year": "2020", "title_zh": "新冠 CDS 对冲 — 1 周赚 $2.6B", "title_en": "COVID CDS hedge — $2.6B in a week",
             "body_zh": "2020 年 3 月初买入 $27M 的 CDS (信用违约掉期), 一周后市场崩盘, 平仓获利 $2.6B (100x). 教训: 系统性事件之前买保险, 即使保险本身看似贵.",
             "body_en": "Early March 2020 bought $27M in CDS (credit default swaps), week later market crashed, closed for $2.6B profit (100x). Lesson: Buy systemic-event insurance before, even if insurance itself looks expensive."},
        ],
        "losses": [
            {"year": "2015-2017", "title_zh": "Valeant — 职业生涯最大灾难", "title_en": "Valeant — career's biggest disaster",
             "body_zh": "$4B 投入 Valeant Pharmaceuticals, 公司涉嫌欺诈 + 监管打击, 股价从 $260 跌到 $11, Pershing Square 净亏 $4B. Ackman 完整 mea culpa: 没 due diligence 商业模式, 没看到 special-pharmacy 红旗.",
             "body_en": "$4B into Valeant Pharmaceuticals; company hit by fraud allegations + regulatory crackdown, stock fell $260 to $11, Pershing lost $4B net. Ackman's full mea culpa: didn't due-diligence the business model, missed special-pharmacy red flags."},
            {"year": "2014-2018", "title_zh": "Herbalife 多空大战 — $1B 输给 Icahn", "title_en": "Herbalife battle — lost $1B to Icahn",
             "body_zh": "Ackman 公开 short Herbalife 几年, 称它是金字塔骗局. Carl Icahn 跟他对赌, 长期 long. 最终 Ackman 平空亏损 $1B. 教训: 'right thesis' 不能跟 retail+activist 群体 + 强 short interest 的轧空对抗.",
             "body_en": "Ackman publicly shorted Herbalife for years, calling it a pyramid scheme. Carl Icahn opposed with long. Eventually Ackman covered with $1B loss. Lesson: 'Right thesis' can't fight a retail+activist crowd + heavy short-interest squeeze."},
        ],
        "must_know": [
            {"title_zh": "他 X (twitter) 非常活跃 + 经常错", "title_en": "Very active on X (twitter) + often wrong",
             "body_zh": "@BillAckman 频繁发表政治 + 投资观点. 关注但带怀疑 — 他在 X 上的 take 命中率不如他基金内部的 thesis 严谨度.",
             "body_en": "@BillAckman posts frequently on politics + investing. Worth following with skepticism — his X takes hit rate is lower than his fund-internal thesis rigor."},
            {"title_zh": "Q1 2026 新建 MSFT", "title_en": "Q1 2026 new MSFT position",
             "body_zh": "11 个持仓里新加一个 = 极强信号. 看他下次年报或 investor day 谈 MSFT thesis.",
             "body_en": "Adding to an 11-position portfolio = strong signal. Watch for his next annual report or investor day discussing MSFT thesis."},
        ],
        "links": [
            {"type": "letters", "label": "Pershing Square Annual Reports", "url": "https://pershingsquareholdings.com/company-reports/"},
            {"type": "x", "label": "@BillAckman on X", "url": "https://x.com/BillAckman"},
            {"type": "interview", "label": "Ackman 'Invest Like the Best' (Colossus)", "url": "https://www.joincolossus.com/episodes/"},
            {"type": "wiki", "label": "Wikipedia: Bill Ackman", "url": "https://en.wikipedia.org/wiki/Bill_Ackman"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "valueact": {
        "summary": {
            "zh": "ValueAct Capital, '建设性 activist' 代表; 跟管理层合作而非对抗. Mason Morfit 现任 CEO.",
            "en": "ValueAct Capital, 'constructive activist' archetype; works WITH management vs hostile. Mason Morfit current CEO.",
        },
        "strategy": {
            "zh": (
                "**核心**: 'Constructive activist' — 不发 poison pen, 不挑骂战. 他们买 5-10% 仓位, 进 board, 帮公司做战略转型. "
                "持有期 3-5 年是常态.\n\n"
                "**最有名案例**: Microsoft 2013 — 他们持 0.8% 占 Microsoft 上市公司 ~$10B, Jeff Ubben 进了董事会, 帮 Steve Ballmer 退休 + Satya Nadella 接 CEO + cloud 战略转型. 这是历史上最大的 activist 价值创造.\n\n"
                "**风格**: 极低调, 几乎不上电视, 不公开骂 CEO. 但内部影响力极大."
            ),
            "en": (
                "**Core**: 'Constructive activist' — no poison pen, no shouting matches. They take 5-10% positions, get board seats, "
                "help with strategic transformations. 3-5 year holds are standard.\n\n"
                "**Most famous case**: Microsoft 2013 — held 0.8% (~$10B at the time), Jeff Ubben got board seat, helped engineer "
                "Ballmer's retirement + Satya Nadella succession + cloud transformation. Largest activist value creation in history.\n\n"
                "**Style**: Very low-profile, almost no TV appearances, no public CEO bashing. But internal influence is huge."
            ),
        },
        "wins": [
            {"year": "2013-2017", "title_zh": "Microsoft — Ballmer → Nadella + cloud 转型", "title_en": "Microsoft — Ballmer → Nadella + cloud pivot",
             "body_zh": "ValueAct 持有 0.8% ($10B+), Jeff Ubben 2013 进 board, 推动 Ballmer 退休 + cloud + Office 365 SaaS 模式. MSFT 在他们任期内股价从 $34 涨到 $80+. 教训: 大 cap tech 也能转型, 需要 board 层面的 catalyst.",
             "body_en": "0.8% position (~$10B), Jeff Ubben got board seat 2013, drove Ballmer retirement + cloud + Office 365 SaaS pivot. MSFT went from $34 to $80+ during their tenure. Lesson: Mega-cap tech CAN transform, but needs board-level catalyst."},
            {"year": "2018-2024", "title_zh": "Seven & i (7-Eleven 母公司)", "title_en": "Seven & i Holdings (7-Eleven parent)",
             "body_zh": "ValueAct 多年持仓 Seven & i, 推动剥离非便利店业务. 2024 年 Couche-Tard 试图收购 — 部分回报 ValueAct 几年研究的成果.",
             "body_en": "Long-held position in Seven & i, pushed for divesting non-convenience-store businesses. 2024 Couche-Tard takeover attempt — partly reward for ValueAct's years of research."},
        ],
        "losses": [
            {"year": "2010-2015", "title_zh": "Adobe 转型 — 早期 underperform", "title_en": "Adobe transition — early underperformance",
             "body_zh": "ValueAct 推动 Adobe 从 perpetual license 转 Creative Cloud subscription. 转型期 (2013-2014) 收入大幅下降, 股价滞涨, 投资者怀疑. 但事后回看是经典 SaaS 转型. 教训: 长期对的 activism 短期看起来像失败.",
             "body_en": "ValueAct drove Adobe's transition from perpetual license to Creative Cloud subscription. During transition (2013-2014) revenue dropped, stock stagnated, investors doubted. In hindsight: classic SaaS pivot. Lesson: Long-term right activism looks like failure short-term."},
        ],
        "must_know": [
            {"title_zh": "Jeff Ubben 离开了, Mason Morfit 现任", "title_en": "Jeff Ubben left, Mason Morfit now runs",
             "body_zh": "Ubben 2019 离开 ValueAct 创立 Inclusive Capital (ESG-focused activist). Morfit 接 CEO 后风格基本延续, 但加了更多 governance + ESG 考量.",
             "body_en": "Ubben left ValueAct in 2019 to found Inclusive Capital (ESG-focused activism). Morfit took over CEO; style continues but adds more governance + ESG considerations."},
        ],
        "links": [
            {"type": "wiki", "label": "Wikipedia: ValueAct Capital", "url": "https://en.wikipedia.org/wiki/ValueAct_Capital"},
            {"type": "interview", "label": "Mason Morfit interviews (Bloomberg/CNBC search)", "url": "https://www.bloomberg.com/search?query=Mason+Morfit+ValueAct"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "soroban": {
        "summary": {
            "zh": "Eric Mandelblatt 创办, 重仓 power / utilities / 基础设施. AI 电力需求 thesis 的最佳 13F 代理.",
            "en": "Founded by Eric Mandelblatt, heavy in power / utilities / infrastructure. Best 13F proxy for your AI power demand thesis.",
        },
        "strategy": {
            "zh": (
                "**核心**: 长/空, ~25 集中持仓. 专精传统能源 + 公用事业 + 通用 infra. 不是 ESG 基金 — 他们看运营 + 估值 + 资本回报.\n\n"
                "**相关性**: 这是 13F 上最能看到 'AI driven power demand' 暴露的基金. Aschenbrenner 通过 swap 持 power, Soroban 直接持公司. "
                "CEG (Constellation Energy) 2022-2024 涨 +500% 大部分是核电 + 数据中心 thesis 驱动的, Soroban 是 CEG 大股东之一.\n\n"
                "**性格**: 低调, 极少公开发言. Mandelblatt 从 TPG-Axon (Dinakar Singh) 出来, 风格类似 — 深度行业研究."
            ),
            "en": (
                "**Core**: Long/short, ~25 concentrated positions. Specializes in traditional energy + utilities + general infrastructure. "
                "NOT an ESG fund — they care about operations + valuation + capital returns.\n\n"
                "**Relevance to you**: This is the 13F-visible fund closest to 'AI-driven power demand' exposure. Aschenbrenner holds "
                "power via swaps; Soroban holds directly. CEG (Constellation Energy) +500% 2022-2024 was mostly nuclear + data center "
                "thesis driven, and Soroban is a large CEG holder.\n\n"
                "**Personality**: Low-profile, rarely public. Mandelblatt came from TPG-Axon (Dinakar Singh), similar style — deep "
                "industry research."
            ),
        },
        "wins": [
            {"year": "2022-2024", "title_zh": "Constellation Energy (CEG) — 核电 + AI 数据中心 thesis", "title_en": "Constellation Energy (CEG) — nuclear + AI data center thesis",
             "body_zh": "Soroban 在 CEG 上 2022 年开始建仓 ~$20/股, 持续加仓. 2024 年股价突破 $300. AI 数据中心需要 24/7 稳定电源, 核电是最匹配的, CEG 是最大独立核电公司. Soroban 提前看到这个.",
             "body_en": "Soroban started building CEG ~$20/share in 2022, kept adding. Stock broke $300 in 2024. AI data centers need 24/7 baseload, nuclear is the match, CEG is the largest pure-play nuclear operator. Soroban saw this early."},
        ],
        "losses": [
            {"year": "2020", "title_zh": "新冠初期能源股暴跌", "title_en": "Early COVID energy stocks crash",
             "body_zh": "2020 年 3 月油价负值时 Soroban 持有大量传统能源, 单月跌幅 40%+. 但他们没割肉, 后续反弹捕获了大部分.",
             "body_en": "March 2020 when oil went negative, Soroban held heavy traditional energy, single-month drawdown 40%+. But they didn't cut, caught most of the rebound."},
        ],
        "must_know": [
            {"title_zh": "他们的 short book 同样重要", "title_en": "Their short book matters equally",
             "body_zh": "Soroban 是 long/short, 13F 只显示 long. 'Soroban 加仓 CEG' 是一面, 你看不到他们在 short 什么. 不要把 13F 当全画.",
             "body_en": "Soroban is long/short; 13F only shows longs. 'Soroban added CEG' is one side; you can't see what they're shorting. Don't treat 13F as the whole picture."},
            {"title_zh": "AI 电力 thesis 的最强机构表达", "title_en": "Strongest institutional expression of AI-power thesis",
             "body_zh": "信 AI-power thesis 的话, 值得研究 power utilities (CEG/VST/TLN/BWXT). Soroban 是 ground truth — 他们是 utilities 专家.",
             "body_en": "If you believe your thesis, you should consider 5-10% to power utilities (CEG/VST/TLN/BWXT). Soroban is ground truth — they're utilities specialists."},
        ],
        "links": [
            {"type": "wiki", "label": "Wikipedia: Soroban Capital Partners", "url": "https://en.wikipedia.org/wiki/Soroban_Capital_Partners"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "cascade": {
        "summary": {
            "zh": "Bill Gates 家族办公室. Michael Larson 运营 30 年. 核心 = MSFT + 多元化基础设施 (铁路, 农业, 核电).",
            "en": "Bill Gates family office. Run by Michael Larson for 30 years. Core = MSFT + diversified infrastructure (rail, agriculture, nuclear).",
        },
        "strategy": {
            "zh": (
                "**核心**: 极长期 (10-20+ 年) + 跨资产. Cascade 不是 hedge fund — 是 family office 长期资本配置.\n\n"
                "**Anchor**: MSFT (Gates 创始持仓 50+ 年) + BRK-B (Buffett 友谊). 这两个 ~半数资产, 几十年没动过.\n\n"
                "**多元化**: Republic Services (废物处理), BNSF (Buffett 的铁路), AutoNation, 大量美国农田 (~270K 英亩, 美国最大私人农田主). "
                "TerraPower (Gates 投资的小型模块化核反应堆公司). 跟 AI 电力 thesis 相关 — Gates 长期看好核电.\n\n"
                "**性格**: 极低调, 几乎从不接受采访 (Michael Larson). 通过 13F 才能看到他们持仓."
            ),
            "en": (
                "**Core**: Extremely long-term (10-20+ years) + cross-asset. Cascade is NOT a hedge fund — it's a family-office long-term "
                "capital allocator.\n\n"
                "**Anchor**: MSFT (Gates' founder position 50+ years) + BRK-B (Buffett friendship). These two ~50% of assets, untouched "
                "for decades.\n\n"
                "**Diversification**: Republic Services (waste), BNSF (Buffett's railroad), AutoNation, massive US farmland (~270K acres, "
                "largest private farmland owner in US). TerraPower (Gates' small modular nuclear reactor company). Relevant to your AI "
                "power thesis — Gates long bullish on nuclear.\n\n"
                "**Personality**: Extremely low-profile, almost no Michael Larson interviews. 13F is the only window into their positions."
            ),
        },
        "wins": [
            {"year": "1990s-present", "title_zh": "MSFT 50 年持有 — 复利奇迹", "title_en": "50-year MSFT hold — compounding miracle",
             "body_zh": "Gates 从 IPO 持有 MSFT 至今, 早期持仓现在价值 $200B+. 教训: 真正的复利不是寻找下一个 100x, 是抓住第一个 100x 然后不卖.",
             "body_en": "Gates held MSFT from IPO to now; original stake worth $200B+. Lesson: True compounding isn't finding the next 100x, it's catching the first 100x and not selling."},
            {"year": "2010-2020", "title_zh": "美国农田收购", "title_en": "US farmland acquisition",
             "body_zh": "Cascade 10+ 年间收购 ~270K 英亩美国农田, 成为美国最大私人农田主. 长期通胀对冲 + 实物资产. 教训: 顶级 family office 在通胀来之前 10 年部署实物资产.",
             "body_en": "Cascade acquired ~270K acres of US farmland over 10+ years, became largest private farmland owner. Long-term inflation hedge + real asset. Lesson: Top family offices deploy real assets 10 years before inflation hits."},
        ],
        "losses": [
            {"year": "Various", "title_zh": "公开很少, 内部不透明", "title_en": "Few publicly known, internally opaque",
             "body_zh": "Cascade 极少披露具体回报, 也没公开过失败案例. 这是 family office 风格 — 不需要 LP, 不公开战绩.",
             "body_en": "Cascade rarely discloses specific returns, no publicly known losses. This is family-office style — no LPs to report to, no public scorecard."},
        ],
        "must_know": [
            {"title_zh": "Gates 看好核电 → TerraPower", "title_en": "Gates bullish on nuclear → TerraPower",
             "body_zh": "Cascade 13F 看不到 TerraPower (私人公司). Gates 个人 + Cascade 直接投资 TerraPower 已 20 年. 跟 AI 电力 thesis 高度对齐 — 但 Gates 玩的是 20 年 horizon 不是 13F 季报.",
             "body_en": "Cascade 13F doesn't show TerraPower (private). Gates personally + Cascade has invested in TerraPower for 20 years. Aligns with your AI power thesis — but Gates plays a 20-year horizon, not 13F quarters."},
            {"title_zh": "Larson 比 Gates 决定具体配置", "title_en": "Larson, not Gates, makes specific allocations",
             "body_zh": "Bill Gates 不亲自管投资. Michael Larson (前 Putnam, 1994 加入) 实际执行. 这是 family office 标准做法.",
             "body_en": "Bill Gates doesn't personally manage investments. Michael Larson (former Putnam, joined 1994) actually executes. Standard family-office practice."},
        ],
        "links": [
            {"type": "wiki", "label": "Wikipedia: Cascade Investment", "url": "https://en.wikipedia.org/wiki/Cascade_Investment"},
            {"type": "wiki", "label": "Wikipedia: TerraPower (Gates' nuclear company)", "url": "https://en.wikipedia.org/wiki/TerraPower"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "coatue": {
        "summary": {
            "zh": "Philippe Laffont (Tiger Cub) 创办. Tech-only 长/空, public + venture cross-over ~$80B AUM. Top tech 投资思想家之一.",
            "en": "Founded by Philippe Laffont (Tiger Cub). Tech-only long/short, public + venture crossover ~$80B AUM. One of the top tech investment thinkers.",
        },
        "strategy": {
            "zh": (
                "**核心**: 'TMT specialist with global reach.' 主要看 mid-late stage 科技 (从 SaaS 到半导体), 不太涉足 deep tech / hard science. "
                "Long/short, 经常 long US 大 tech + short 中国 tech (或反过来).\n\n"
                "**资本结构**: 多个基金 — Public fund (13F 可见) + Coatue Cardinal (venture+public) + Coatue Climate (新). 13F 只看到 public fund.\n\n"
                "**重要的'Laffont rules'**: 1) TMT 是 secular growth, 不是 cyclical (大方向永远 long). 2) Concentration > diversification (top "
                "10 持仓占大头). 3) Public + private 互补 (private 看 trend, public 兑现)."
            ),
            "en": (
                "**Core**: 'TMT specialist with global reach.' Mainly mid-late stage tech (SaaS to semis), less deep-tech / hard science. "
                "Long/short, often long US big tech + short China tech (or vice versa).\n\n"
                "**Capital structure**: Multiple funds — Public fund (13F-visible) + Coatue Cardinal (venture+public) + Coatue Climate "
                "(new). 13F only shows public fund.\n\n"
                "**Key 'Laffont rules'**: 1) TMT is secular growth, not cyclical (always long the big direction). 2) Concentration > "
                "diversification (top 10 dominate). 3) Public + private complement each other (private for trend, public for execution)."
            ),
        },
        "wins": [
            {"year": "2010s", "title_zh": "Early SaaS — Workday/ServiceNow/Salesforce", "title_en": "Early SaaS — Workday/ServiceNow/Salesforce",
             "body_zh": "Laffont 早期看好 SaaS 转型, 持仓多年获得多倍回报. 至 2010s 中期 Coatue 大幅增长.",
             "body_en": "Laffont bullish on SaaS pivot early, held positions multi-year for multi-bagger returns. Coatue grew significantly through mid-2010s."},
            {"year": "2020-2021", "title_zh": "NVDA + 半导体 cycle", "title_en": "NVDA + semi cycle",
             "body_zh": "2020 年 Coatue 是 NVDA 早期机构持仓之一. 当年 NVDA 从 $60 到 $300+ — 单一仓位贡献巨大回报.",
             "body_en": "2020 Coatue was an early institutional NVDA holder. NVDA went $60 → $300+ that year — single position contributed massive returns."},
        ],
        "losses": [
            {"year": "2022", "title_zh": "Private mark-down 痛苦", "title_en": "Private mark-down pain",
             "body_zh": "2022 年 Coatue 私募投资组合大幅 mark down — Stripe, Instacart, etc 估值砍半. 13F (public) 也跌 30%+. LP 信心受打击, 但他们 ride 过来了.",
             "body_en": "2022 Coatue's private portfolio took major mark-downs — Stripe, Instacart, etc valued ~50% lower. 13F (public) also -30%+. LP confidence hit, but they rode through it."},
        ],
        "must_know": [
            {"title_zh": "Tiger Cub 家族 — 学 Laffont 也学 Robertson", "title_en": "Tiger Cub lineage — learn from Laffont also learn Robertson",
             "body_zh": "Coatue, D1 (Sundheim), Tiger Global (Coleman), Lone Pine (Mandel), Viking (Halvorsen) 都从 Julian Robertson 的 Tiger Management 出来. 这一脉相承的方法论很重要 — '集中 + 长持' + 'public/private 通吃'.",
             "body_en": "Coatue, D1 (Sundheim), Tiger Global (Coleman), Lone Pine (Mandel), Viking (Halvorsen) all from Julian Robertson's Tiger Management. This lineage's methodology matters — 'concentrate + hold long' + 'public/private both'."},
            {"title_zh": "他们的 LP letters 偶尔泄漏", "title_en": "Their LP letters occasionally leak",
             "body_zh": "Coatue 不公开 letters, 但每年 LP 总有人转发到投资圈. Search Google 'Coatue annual letter' 偶尔能找到 PDF.",
             "body_en": "Coatue doesn't publish letters publicly, but LP letters leak annually. Google 'Coatue annual letter' occasionally finds PDFs."},
        ],
        "links": [
            {"type": "wiki", "label": "Wikipedia: Coatue Management", "url": "https://en.wikipedia.org/wiki/Coatue_Management"},
            {"type": "wiki", "label": "Wikipedia: Philippe Laffont", "url": "https://en.wikipedia.org/wiki/Philippe_Laffont"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "altimeter": {
        "summary": {
            "zh": "Brad Gerstner 创办. 公开 vocal AI 多头, 频繁出现在 podcast + X + CNBC. 重点 mid/late stage tech, ~20 集中仓位.",
            "en": "Founded by Brad Gerstner. Publicly vocal AI bull, frequently on podcasts + X + CNBC. Focuses on mid/late-stage tech, ~20 concentrated positions.",
        },
        "strategy": {
            "zh": (
                "**核心**: 集中 mid/late-stage 科技 growth. 不是 venture, 是公开市场上 high-conviction names. 不像 Tiger Global 那样多元化, "
                "更像 Pershing Square 的科技版本.\n\n"
                "**对 AI-bull 视角**: Gerstner 是公开最 vocal 的 AI bull 之一. 他的 podcast (Invest Like the Best, BG2) 是教育素材. 但要分辨: "
                "他在 podcast 讲的是 marketing 版本, 实际持仓可能没那么 aggressive — 看 13F 自己判断.\n\n"
                "**重要历史**: 2020 年 Altimeter 跟 Reid Hoffman 合作 SPAC 投资 Grab, Grab 从 $11 跌到 $3. 这次失败让 Gerstner 暂时谦虚, 但他很快又开始公开 promote."
            ),
            "en": (
                "**Core**: Concentrated mid/late-stage tech growth. Not venture, public-market high-conviction names. Less diversified "
                "than Tiger Global, more like Pershing Square's tech version.\n\n"
                "**Alignment to you**: Gerstner is one of the most publicly vocal AI bulls. His podcast (BG2 with Bill Gurley, also on "
                "'Invest Like the Best') is educational. But distinguish: what he says on podcast is the marketing version; his actual "
                "holdings may be less aggressive — read 13F yourself.\n\n"
                "**Important history**: 2020 Altimeter partnered with Reid Hoffman on SPAC investing Grab, Grab went $11 → $3. The "
                "failure made Gerstner briefly humble, but he soon resumed public promotion."
            ),
        },
        "wins": [
            {"year": "2020-2021", "title_zh": "Snowflake IPO + early Snowflake position", "title_en": "Snowflake IPO + early Snowflake position",
             "body_zh": "Altimeter 是 Snowflake IPO 关键投资者, 也是上市后大持有者. Snowflake 多年表现亮眼.",
             "body_en": "Altimeter was a key Snowflake IPO investor + sustained holder post-IPO. Strong multi-year performer."},
            {"year": "2022-2024", "title_zh": "Meta turnaround bet", "title_en": "Meta turnaround bet",
             "body_zh": "META 2022 年从 $380 跌到 $90, Altimeter 公开 vocal 看多 (Gerstner CNBC 多次), 从底部加仓. 2024 年 META $700+ , 2-3 倍盈利.",
             "body_en": "META fell $380 to $90 in 2022; Altimeter vocally bought the bottom (Gerstner on CNBC repeatedly). META $700+ by 2024, 2-3x profit."},
        ],
        "losses": [
            {"year": "2020-2022", "title_zh": "Altimeter Growth SPAC (Grab)", "title_en": "Altimeter Growth SPAC (Grab)",
             "body_zh": "Altimeter 跟 Hoffman 创立 2 个 SPAC, 第一个并 Grab 后 Grab 从 $11 跌到 $3. 第二个 (NextGen Aviation) 没找到目标退还资本.",
             "body_en": "Altimeter partnered with Hoffman on 2 SPACs; first merged with Grab, fell $11 → $3. Second (NextGen Aviation) found no target, returned capital."},
        ],
        "must_know": [
            {"title_zh": "听他 podcast 但读他 13F 验证", "title_en": "Listen to his podcast but verify with 13F",
             "body_zh": "BG2 podcast 是接触 AI macro+VC 视角的好渠道. 但 Brad 说话比他持仓激进. 永远 cross-check.",
             "body_en": "BG2 podcast is good for AI macro+VC perspective. But Brad talks more aggressively than his portfolio. Always cross-check."},
            {"title_zh": "他参与 ByteDance/TikTok 救援讨论", "title_en": "Involved in ByteDance/TikTok rescue discussions",
             "body_zh": "2024-2025 Gerstner 公开参与 TikTok 在美国 ban 后的资本结构讨论, 想做 US buyer. 这种公开高调是 attention-seeking, 多过实际仓位.",
             "body_en": "2024-2025 Gerstner publicly involved in TikTok-US ban capital structure talks, wants to be US buyer. This public profile is attention-seeking more than actual positioning."},
        ],
        "links": [
            {"type": "podcast", "label": "BG2 Pod (Brad Gerstner + Bill Gurley)", "url": "https://www.youtube.com/@BG2Pod"},
            {"type": "x", "label": "@altcap on X", "url": "https://x.com/altcap"},
            {"type": "interview", "label": "Altimeter CNBC archive", "url": "https://www.cnbc.com/brad-gerstner/"},
            {"type": "wiki", "label": "Wikipedia: Altimeter Capital", "url": "https://en.wikipedia.org/wiki/Altimeter_Capital"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════
    "dalio": {
        "summary": {
            "zh": "Ray Dalio, Bridgewater 创办者. 'All Weather' + 'Pure Alpha' 策略. 写 'Principles', 业内最系统化的投资思想家.",
            "en": "Ray Dalio, Bridgewater founder. 'All Weather' + 'Pure Alpha' strategies. Author of 'Principles', most systematic investment thinker in the industry.",
        },
        "strategy": {
            "zh": (
                "**核心**: 'Don't predict, diversify across regimes.' 把经济分成 4 种状态 (增长↑/通胀↑, 增长↑/通胀↓, 增长↓/通胀↑, 增长↓/通胀↓), "
                "持有在每种状态下表现好的资产组合 (Risk Parity).\n\n"
                "**'All Weather' fund**: 设计目标是任何宏观环境下都不会崩盘. 不追求最高回报, 追求最低 drawdown.\n\n"
                "**'Pure Alpha' fund**: 主动 macro trades, 短期 (季度) 风险偏移. 2008 +14%, 2020 +33%, 2022 -7% (难得失利的一年).\n\n"
                "**重要警告**: Bridgewater 大量使用 swap/futures/FX 衍生品, 13F (美股) 只是真实暴露的 ~30-50%."
            ),
            "en": (
                "**Core**: 'Don't predict, diversify across regimes.' Splits economy into 4 states (growth↑/inflation↑, growth↑/inflation↓, "
                "growth↓/inflation↑, growth↓/inflation↓), holds assets that perform well in each (Risk Parity).\n\n"
                "**'All Weather' fund**: Designed to never blow up in any macro environment. Doesn't chase max returns, chases min drawdown.\n\n"
                "**'Pure Alpha' fund**: Active macro trades, short-term (quarterly) risk-shifting. 2008 +14%, 2020 +33%, 2022 -7% "
                "(rare losing year).\n\n"
                "**Important warning**: Bridgewater uses massive swap/futures/FX derivatives. 13F (US equity) is only ~30-50% of true exposure."
            ),
        },
        "wins": [
            {"year": "2008", "title_zh": "金融危机 +14%", "title_en": "Financial crisis +14%",
             "body_zh": "All Weather + Pure Alpha 都在 2008 正回报, 同期 SPX -38%. 这是 Bridgewater 正名战役.",
             "body_en": "Both All Weather + Pure Alpha positive in 2008, vs SPX -38%. Bridgewater's defining moment."},
            {"year": "1971", "title_zh": "尼克松解除金本位 — Dalio 第一次大警告", "title_en": "Nixon ends gold standard — Dalio's first big warning",
             "body_zh": "Dalio 当时是大学生 trader, 提前预判 dollar 贬值. 这次成功让他终生关注'纸币贬值'的宏观大主题.",
             "body_en": "Dalio was a college trader, predicted dollar devaluation ahead. This early success made him career-long focused on 'paper money devaluation' macro theme."},
        ],
        "losses": [
            {"year": "2020 spring", "title_zh": "新冠初期 All Weather -14%", "title_en": "Early COVID All Weather -14%",
             "body_zh": "All Weather 设计是任何环境不崩, 但 2020 年 3 月股+债同跌让它 1 个月跌 14%. Dalio 公开承认 risk parity 在 'correlation 失常' 时受伤.",
             "body_en": "All Weather designed to never crash, but March 2020 stocks+bonds fell together, dropping it 14% in one month. Dalio publicly acknowledged risk parity fails when 'correlation breaks'."},
            {"year": "2022", "title_zh": "Pure Alpha -7%", "title_en": "Pure Alpha -7%",
             "body_zh": "30 年来罕见的负回报年. Bridgewater 看错通胀回落速度.",
             "body_en": "Rare losing year in 30. Bridgewater misjudged inflation pullback speed."},
        ],
        "must_know": [
            {"title_zh": "Dalio 自己已经退居二线", "title_en": "Dalio has stepped back",
             "body_zh": "2022 年 Dalio 把 CEO 交给团队, 自己专注写作. 现在 Bridgewater 不完全代表 Dalio 个人观点.",
             "body_en": "Dalio handed CEO to team in 2022, now focused on writing. Current Bridgewater doesn't fully represent Dalio's personal view."},
            {"title_zh": "他的书《Principles》是系统化思维教材", "title_en": "His 'Principles' book is a systems-thinking textbook",
             "body_zh": "看这本书不是为了学交易, 是为了学如何 '机器化' 自己的决策过程 — 把每个决策的输入条件 + 输出 + 后续反馈都记录下来形成可迭代的 framework.",
             "body_en": "Read this book not for trading — for learning to 'machine-ify' your own decision process: record every decision's inputs + outputs + feedback to build an iterable framework."},
        ],
        "links": [
            {"type": "letters", "label": "principles.com (Dalio's frameworks)", "url": "https://www.principles.com/"},
            {"type": "book", "label": "Principles (Dalio's autobiography + system)", "url": "https://en.wikipedia.org/wiki/Principles_(book)"},
            {"type": "book", "label": "Principles for Dealing with the Changing World Order (2021)", "url": "https://en.wikipedia.org/wiki/Principles_for_Dealing_with_the_Changing_World_Order"},
            {"type": "wiki", "label": "Wikipedia: Ray Dalio", "url": "https://en.wikipedia.org/wiki/Ray_Dalio"},
        ],
    },
}


def get_profile(key: str) -> Optional[_Profile]:
    """Look up curated profile by whale_key. Returns None if not curated."""
    return PROFILES.get(key)


def list_curated_keys() -> List[str]:
    return list(PROFILES.keys())
