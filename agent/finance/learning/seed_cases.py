"""Hand-curated evergreen case-study seeds.

Ships with the app — populated into ``learning_cases`` on first
ensure_schema() call where the table is empty (or via the manual
``POST /api/learning/seed`` endpoint).

Selection criteria:
- Must teach a transferable mental model (not just X stock went up)
- Half modern Chinese-context, half international classics translated
- Each ≤ 500 chars summary so the user can absorb in one breath
- Each carries source_url to the most authoritative public account

When you add a new seed, give it a stable slug — duplicates by slug
are upserted (the earlier row's content gets overwritten).

Note on Chinese punctuation: ASCII double quotes inside Python
string literals terminate the string. We use Chinese guillemets
《》 for any in-text quoting in summaries to keep the source file
ASCII-quote-clean.
"""
from __future__ import annotations

from typing import Any, Dict, List


SEEDS: List[Dict[str, Any]] = [

    # ── 现代中国 (modern_cn) ──────────────────────────────────────

    {
        "slug": "2021-shuangjian-edtech-collapse",
        "title": "2021 教培双减政策与在线教育板块崩塌",
        "title_zh": "2021 教培双减：一夜之间，整个赛道消失",
        "summary_zh": (
            "2021 年 7 月 24 日，中办国办《关于进一步减轻义务教育阶段学生作业负担和"
            "校外培训负担的意见》落地。新东方、好未来、高途等 K12 在线教育公司股价"
            "单日下跌 50-70%，市值蒸发超 1500 亿美元。教训：在中国市场，政策风险"
            "是估值之外独立的、可以归零的 tail risk。任何依赖政策默许的商业模式"
            "（教培、互联网医疗、虚拟币、互联网金融），DCF 模型再漂亮也要打一个"
            "永远无法对冲的折扣。后续启示：再看到《行业渗透率提升空间巨大》的故事，"
            "先问《政策默许还是政策鼓励》。"
        ),
        "source_url": "http://www.gov.cn/zhengce/2021-07/24/content_5627132.htm",
        "source_name": "国务院·原文件",
        "language": "zh",
        "themes": ["政策风险", "教育板块", "tail risk", "中概股"],
        "tickers": ["EDU", "TAL", "GOTU"],
        "era": "modern_cn",
        "difficulty": "intermediate",
    },

    {
        "slug": "2022-moutai-valuation-vs-growth",
        "title": "2022 茅台跌 35% 与价值/成长 rotation",
        "title_zh": "2022 茅台 -35%：白马也会被估值地心引力拉回",
        "summary_zh": (
            "2021 年初茅台 PE 一度冲到 70 倍，2022 年回落到 30 倍区间，股价从 2600 元"
            "跌到 1700 元附近。同期成长股板块（新能源、医药、半导体）跌幅更大，但"
            "茅台的下跌打破了《消费白马永远涨》的迷思。教训：(1) 再好的公司也有"
            "估值上限——10 年后的现金流无论多确定，折现回今天也只值那么多。"
            "(2) 板块 rotation 是周期，不是末日；2024 年茅台又涨回 2300 元区间。"
            "(3) 看到 PE 60+ 的《长期持有》建议，记得算一下：未来 10 年增速要达到"
            "多少才能消化估值。"
        ),
        "source_url": "https://xueqiu.com/S/SH600519",
        "source_name": "雪球·贵州茅台行情",
        "language": "zh",
        "themes": ["估值", "白马股", "rotation", "消费"],
        "tickers": ["600519.SH"],
        "era": "modern_cn",
        "difficulty": "beginner",
    },

    {
        "slug": "2023-china-special-valuation",
        "title": "2023 中特估行情",
        "title_zh": "2023 中特估：当政策变成投资主题",
        "summary_zh": (
            "2022 年 11 月证监会主席易会满首次提出《探索建立具有中国特色的估值体系》，"
            "2023 年上半年成为 A 股最强主线之一。中字头银行、能源、电信运营商集体"
            "上涨 40-100%。教训：(1) A 股是政策市——一句话能炸出 1 万亿成交量。"
            "(2) 主题驱动的行情来得快也走得快，2023 年 5 月见顶后多数中特估个股回吐"
            "70%+ 涨幅。(3) 政策口风转向时（防止资本无序扩张 → 中特估 → 耐心资本），"
            "对应的是不同板块的进/出，不是 buy & hold。学会读政策口风比读财报重要。"
        ),
        "source_url": "https://www.csrc.gov.cn/csrc/c100028/c7401029/content.shtml",
        "source_name": "证监会·易会满讲话",
        "language": "zh",
        "themes": ["政策", "主题投资", "国企", "估值修复"],
        "tickers": ["601398.SH", "601857.SH", "600028.SH"],
        "era": "modern_cn",
        "difficulty": "intermediate",
    },

    {
        "slug": "2024-china-dividend-strategy",
        "title": "2024 红利低估值策略全面跑赢",
        "title_zh": "2024 红利策略：利率下行环境下的 boring is sexy",
        "summary_zh": (
            "2024 年 10 年期国债收益率从年初 2.6% 一路下行至年末 1.7%，30 年期"
            "国债 ETF 涨超 20%。同期红利低估值 ETF（如 510880）跑赢沪深 300 接近"
            "20 个百分点。煤炭、银行、电力等高股息板块成为最大赢家。教训："
            "(1) 股息率 = 你的最低预期回报——当 10 年期国债 1.7%、煤炭股息率 7%，"
            "套利空间会被市场逐步定价。(2) 利率方向决定大类资产 rotation："
            "降息周期看红利+长债，加息周期看成长股+现金。(3) 美股同期红利策略"
            "跑输 SPX 是因为美国仍在利率高位，环境完全不同——不要无脑套用美股逻辑。"
        ),
        "source_url": "https://www.csindex.com.cn/indices/index-detail/000922",
        "source_name": "中证·上证红利指数",
        "language": "zh",
        "themes": ["红利", "利率", "rotation", "ETF"],
        "tickers": ["510880", "601088.SH", "601398.SH"],
        "era": "recent_2024",
        "difficulty": "intermediate",
    },

    {
        "slug": "2024-cn-ai-compute-cambricon-eoptolink",
        "title": "2024 中国 AI 算力浪潮 — 寒武纪 + 中际旭创",
        "title_zh": "2024 国产 AI 算力：寒武纪 5 倍、中际旭创 3 倍",
        "summary_zh": (
            "2024 全年寒武纪 (688256) 涨幅约 +400%，中际旭创 (300308) +200%，"
            "光模块 / AI 芯片整个产业链 rerated。驱动力：(1) 美国对 H100 / H200 出口"
            "管制，国产替代成为政策主线；(2) DeepSeek-V3 / 阿里 Qwen 等国产大模型"
            "证明算力需求真实存在；(3) 字节、腾讯、阿里资本开支大幅上调。教训："
            "主题股的核心是《是否被外部强制催化》——这一波是美国制裁硬性催化，"
            "不是单纯讲故事。学会区分：催化剂是《故事会发生》还是《已经被强制发生》。"
            "前者高估值合理，后者就只是炒作。"
        ),
        "source_url": "https://xueqiu.com/S/SH688256",
        "source_name": "雪球·寒武纪",
        "language": "zh",
        "themes": ["AI", "算力", "国产替代", "主题投资"],
        "tickers": ["688256.SH", "300308.SZ"],
        "era": "recent_2024",
        "difficulty": "intermediate",
    },

    {
        "slug": "2024-2025-hk-tech-rebound",
        "title": "2024-2025 港股科技股回归",
        "title_zh": "2024-2025 港股科技：从无人问津到全球资金抢筹",
        "summary_zh": (
            "恒生科技指数 2024 年初最低 3000 点，到 2025 年 5 月一度突破 6500 点，"
            "腾讯、阿里、美团各自从底部反弹 80-150%。驱动力：(1) DeepSeek 让全球"
            "重新评估《中国 AI 公司也能做世界级模型》；(2) 中央《市值管理》+《耐心资本》"
            "政策；(3) 中概互联估值长期被压制，反弹空间巨大。教训：(1) 全球资金"
            "Flow 比基本面变化更重要——同样的腾讯，估值在不同情绪下能差 2 倍。"
            "(2) 一个龙头公司被严重低估时，整个板块往往一起被低估。(3) 当所有人都"
            "说《中概不能投》时，往往就是机会窗口（contrarian indicator）。"
        ),
        "source_url": "https://www.hsi.com.hk/eng/indexes/all-indexes/hsTECH",
        "source_name": "Hang Seng Indexes·恒生科技指数",
        "language": "zh",
        "themes": ["港股", "中概股", "AI", "全球资金", "contrarian"],
        "tickers": ["0700.HK", "9988.HK", "3690.HK"],
        "era": "recent_2025",
        "difficulty": "intermediate",
    },

    {
        "slug": "2026-roku-pe-91-puzzle",
        "title": "2026 ROKU PE 91 之谜",
        "title_zh": "2026 ROKU：91 倍市盈率到底贵不贵？",
        "summary_zh": (
            "2026 年 5 月 ROKU 价格 $123.58，市值 $18.3B，trailing PE 91.5、"
            "forward PE 36.6，1 年涨幅 +105%。Q1 财报后跳空 +6%，分析师 PT 从 $115"
            "上调到 $130。但 ROKU 的 10-K Item 1A 列出了 5 大风险，其中《Amazon, "
            "Apple, Google 三家提供 TV 流媒体设备直接竞争》被反复强调。教训："
            "(1) 看高估值要先问：增长能不能消化它——91x PE 意味着 5 年内 EPS 必须"
            "翻 4 倍以上才合理。(2) 财报跳涨 6% 不等于该买，可能恰恰是高位让"
            "套利者出货。(3) 永远把公司自己 10-K 写的风险（不是分析师写的目标价）"
            "放在估值判断的前面。"
        ),
        "source_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001428439&type=10-K",
        "source_name": "SEC EDGAR·ROKU 10-K",
        "language": "zh",
        "themes": ["估值", "流媒体", "PE", "竞争格局"],
        "tickers": ["ROKU", "AMZN", "AAPL", "GOOGL"],
        "era": "recent_2026",
        "difficulty": "intermediate",
    },

    # ── 国际经典 (classic_intl) — 中文版 ──────────────────────────

    {
        "slug": "1988-buffett-coca-cola",
        "title": "1988 Warren Buffett's Coca-Cola Investment",
        "title_zh": "1988 巴菲特买可口可乐：长持的极致案例",
        "summary_zh": (
            "1988 年伯克希尔·哈撒韦投入 13 亿美元买入可口可乐 7% 股权，平均成本约"
            " $5.22/股（拆股调整后）。到 2025 年这笔投资市值超 280 亿美元，35 年"
            "复合回报 ~14% (不含股息) + 累计股息超 100 亿美元。买入逻辑："
            "(1) 品牌护城河 —— 全球认知度无可替代；(2) 资本回报极高 —— ROIC > 20%，"
            "再投资率低，剩余现金回购+分红；(3) 国际扩张空间大 —— 当时人均消费量"
            "印度/中国还在个位数。教训：(1) 永远持有 的真正含义是《找到一家随时间"
            "复合财富的公司》，不是《买什么都不卖》。(2) 极少数公司值得集中重仓 +"
            "永久持有。判断标准就是 Buffett 的 4 条：你懂 + 有护城河 + 管理层诚信 +"
            "价格合理。"
        ),
        "source_url": "https://www.berkshirehathaway.com/letters/1988.html",
        "source_name": "Berkshire 1988 股东信",
        "language": "en",
        "themes": ["护城河", "长持", "复利", "消费品"],
        "tickers": ["KO", "BRK.A"],
        "era": "classic_intl",
        "difficulty": "beginner",
    },

    {
        "slug": "1992-soros-bank-of-england",
        "title": "1992 Soros Breaking the Bank of England",
        "title_zh": "1992 索罗斯做空英镑：宏观对赌的最高水平",
        "summary_zh": (
            "1992 年 9 月 16 日 黑色星期三，索罗斯量子基金借了 100 亿英镑做空，"
            "利用英国央行被迫维持 ERM 汇率机制的背景，赌英镑必须贬值。最终单日盈利"
            "10 亿美元，英镑当日贬值 15% 退出 ERM。教训：(1) 宏观投资 = 找到《政策"
            "和市场逻辑不一致的时刻》—— 英国通胀已起，利率却为了挂钩马克被压低，"
            "结构性矛盾必爆。(2) 杠杆是宏观对赌的核心工具——单纯看对方向只是赚一倍，"
            "10x 杠杆才是 10 倍利润。(3) 但杠杆也是失败的核心 —— 1998 年俄罗斯危机"
            "时索罗斯也被打爆 20 亿。所以宏观策略只适合极小部分能承受归零的资金。"
        ),
        "source_url": "https://en.wikipedia.org/wiki/Black_Wednesday",
        "source_name": "Wikipedia · Black Wednesday",
        "language": "en",
        "themes": ["宏观", "做空", "杠杆", "央行政策"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "advanced",
    },

    {
        "slug": "1998-ltcm-collapse",
        "title": "1998 Long Term Capital Management Collapse",
        "title_zh": "1998 LTCM 倒闭：诺奖得主与杠杆毁灭",
        "summary_zh": (
            "LTCM 由 Solomon Brothers 前债券交易明星 Meriwether 创立，团队含 2 位"
            "诺贝尔经济学奖得主 (Merton/Scholes)，1994-1997 年年化回报 40%+。1998 年"
            "俄罗斯国债违约引发流动性危机，LTCM 25 倍杠杆放大亏损 → 4 个月亏 46 亿"
            "美元 → 美联储紧急组织华尔街救助。教训：(1) 模型基于历史相关性，但"
            "危机时刻所有相关性 → 1 —— 分散化失效。(2) 杠杆放大正反两面 —— 同样"
            "的策略，无杠杆赚 8%/年没事，25x 杠杆遇尾部事件直接归零。(3) 顶级人才"
            "不等于正确判断风险 —— 两位诺奖得主依然死在自己创造的模型局限上。"
        ),
        "source_url": "https://www.federalreserve.gov/boarddocs/testimony/1998/19981001.htm",
        "source_name": "美联储·LTCM 救助证词",
        "language": "en",
        "themes": ["杠杆", "尾部风险", "模型风险", "对冲基金"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "advanced",
    },

    {
        "slug": "2008-paulson-cdo-short",
        "title": "2008 John Paulson's Subprime Short",
        "title_zh": "2008 Paulson 做空次贷：反共识的极致回报",
        "summary_zh": (
            "2007-2008 年 John Paulson 通过 ABX 指数做空次级 MBS / CDO，单笔交易盈利"
            "超 150 亿美元，个人收入 40 亿美元，被称为 史上最伟大单笔交易。"
            "Buy 逻辑：(1) 美国房价基于历史从未全国性下跌的假设；(2) 次级 MBS 的"
            "评级远高于实际信用质量；(3) 没人在做空 —— CDS 价格便宜得离谱。教训："
            "(1) 极致回报必然来自反共识 —— 所有人都同意的事情没有 mispricing。"
            "(2) 做空需要找到《既错又便宜》的赌注 —— 很多人都知道次贷有问题，"
            "但只有 Paulson 找到了 CDS 这个杠杆+便宜的工具。(3) 但 Paulson 后续 10 年"
            "回报平庸，一笔交易封神不等于持续 alpha。"
        ),
        "source_url": "https://en.wikipedia.org/wiki/John_Paulson",
        "source_name": "Wikipedia · John Paulson",
        "language": "en",
        "themes": ["做空", "反共识", "次贷", "CDS"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "advanced",
    },

    {
        "slug": "2021-gamestop-meme-squeeze",
        "title": "2021 GameStop Short Squeeze",
        "title_zh": "2021 GameStop 散户大战：流动性 + meme 的合谋",
        "summary_zh": (
            "2021 年 1 月 GameStop (GME) 股价从 $20 暴涨到盘中 $483，对冲基金 Melvin"
            " Capital 做空被轧空爆仓亏 $7B。Reddit 论坛 r/wallstreetbets 数万散户协调"
            "买入 + 买 OTM call，触发 short squeeze + gamma squeeze 双杀。教训："
            "(1) 流动性 + 杠杆 + 群体协调 = 任何被深度做空的小盘股都可能被轧。"
            "(2) 机构的《危险信号》对散户来说反而是机会 —— short interest > 100% "
            "本身是 setup。(3) 但参与时机至关重要——大部分散户高位接盘，最终盈利"
            "集中在极少数早期参与者。FOMO 进场 = 给庄家送钱。"
        ),
        "source_url": "https://en.wikipedia.org/wiki/GameStop_short_squeeze",
        "source_name": "Wikipedia · GME 事件",
        "language": "en",
        "themes": ["散户行为", "做空挤兑", "流动性", "meme stock"],
        "tickers": ["GME"],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "2022-luna-ftx-collapse",
        "title": "2022 LUNA + FTX Collapse",
        "title_zh": "2022 LUNA & FTX：加密世界的雷曼时刻",
        "summary_zh": (
            "2022 年 5 月 Terra LUNA 和 UST 算法稳定币崩盘归零，蒸发 400 亿美元；"
            "11 月 FTX (估值曾达 $32B) 破产，创始人 SBF 因欺诈+挪用客户资金被判"
            "25 年。教训：(1) 算法稳定币是金融炼金术 —— 靠《信心循环》维持的设计"
            "终归会被某个边际事件打破。(2) 行业明星 + 监管真空 = 完美骗局土壤 —— "
            "SBF 当时是民主党最大金主、登 Forbes 封面，但底层是把客户钱借给自己的"
            " Alameda 做杠杆 long。(3) 不要把《我朋友推荐的》当作 due diligence —— "
            "Sequoia / Tiger / Temasek 全都尽调过 FTX，全部 100% 减记。"
        ),
        "source_url": "https://www.justice.gov/usao-sdny/pr/samuel-bankman-fried-sentenced-25-years-prison",
        "source_name": "美国司法部·SBF 判决书",
        "language": "en",
        "themes": ["加密货币", "稳定币", "庞氏骗局", "尽调", "尾部风险"],
        "tickers": [],
        "era": "classic_intl",
        "difficulty": "intermediate",
    },

    {
        "slug": "2024-nvidia-ai-runup",
        "title": "2024 NVIDIA AI Runup",
        "title_zh": "2024 NVIDIA：万亿美元市值与 GPU 的复利时代",
        "summary_zh": (
            "2024 年 NVIDIA 市值首次突破 $3 万亿美元，超越苹果成为全球最大公司之一。"
            "全年股价涨 +170%，PE 高位 70+，但收入和利润同比+ 100%+ 完全消化估值。"
            "驱动力：(1) ChatGPT 引发的全球 AI 算力竞赛；(2) Hyperscaler "
            "(MSFT/META/GOOGL/AMZN) 资本开支大幅上调；(3) Blackwell 芯片代际优势"
            "继续扩大。教训：(1) 平台型科技公司的《时代红利》—— 巴菲特卖了苹果"
            "买不进 NVIDIA，就是错过这个时代。(2) 高 PE 不等于高估 —— 只要业绩"
            "增速能匹配，PE 永远是相对的。(3) 但要警惕《时代结束》信号 —— AI capex"
            "见顶时第一个砸的就是 NVDA。"
        ),
        "source_url": "https://investor.nvidia.com/financial-info/sec-filings/",
        "source_name": "NVIDIA Investor · SEC Filings",
        "language": "en",
        "themes": ["AI", "算力", "平台公司", "估值", "时代红利"],
        "tickers": ["NVDA"],
        "era": "recent_2024",
        "difficulty": "intermediate",
    },
]


def all_seeds() -> List[Dict[str, Any]]:
    """Return the seed list. Wrapped in a function so callers don't
    accidentally mutate the module-level constant."""
    return list(SEEDS)
