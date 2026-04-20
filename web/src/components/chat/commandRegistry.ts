/**
 * Slash-command registry for the chat panel.
 *
 * Each command can either:
 *  - execute entirely locally (hits a /api/* endpoint and returns a rendered result), OR
 *  - fall through to the fleet agent (/api/chat) as free-form prompt.
 *
 * Local-first execution means "quote AAPL" returns data instantly
 * instead of waiting 20s for DeepSeek-R1's chain of thought.
 */

export interface Command {
  name: string
  args: string            // short arg hint shown in the menu
  description: string
  example?: string
}

export const COMMANDS: Command[] = [
  // ── Workflow commands (stream with dashboard context injected) ──
  { name: '/brief',   args: '',                    description: '上班前简报：市场温度 + 持仓 + 未来 14 天财报', example: '/brief' },
  { name: '/prep',    args: 'SYMBOL',              description: '单股财报前 playbook（IV vs 历史走势 + 技术 + 持仓建议）', example: '/prep AAPL' },
  { name: '/check',   args: '',                    description: '组合健康扫描：亏损 / 财报临近 / 红色板块', example: '/check' },

  // ── Quick data-lookup commands (render inline, no LLM) ──
  { name: '/quote',   args: 'SYMBOL',             description: '美股/ETF 实时报价',   example: '/quote AAPL' },
  { name: '/cn',      args: '6-digit code',        description: 'A股/港股实时报价',    example: '/cn 600519' },
  { name: '/info',    args: '6-digit code',        description: 'A股 基本面 / 市值 / 行业', example: '/info 600519' },
  { name: '/news',    args: '[SYMBOLS]',           description: '最新新闻；可按 ticker 过滤', example: '/news AAPL,TSLA' },
  { name: '/analyze', args: 'SYMBOL',              description: '调用 fleet 做结构化分析（signal/confidence）', example: '/analyze AAPL' },
  { name: '/paper',   args: '[account|positions|trades]', description: '查看纸面交易状态', example: '/paper positions' },
  { name: '/audit',   args: '[N]',                 description: '最近 N 条 LLM audit（默认 5）', example: '/audit 10' },
  { name: '/help',    args: '',                    description: '列出全部命令',         example: '/help' },
]

export function findCommand(input: string): Command | null {
  const first = input.split(/\s+/)[0]
  return COMMANDS.find(c => c.name === first) ?? null
}

export function filterCommands(query: string): Command[] {
  if (!query.startsWith('/')) return []
  const rest = query.slice(1).toLowerCase()
  return COMMANDS.filter(c => c.name.slice(1).toLowerCase().startsWith(rest))
}
