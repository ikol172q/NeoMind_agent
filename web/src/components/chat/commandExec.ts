/**
 * Execute a slash command locally when possible. Returns a rendered
 * Markdown / text string suitable for display in the chat as an
 * assistant bubble. Returns null if the command should fall through
 * to the fleet LLM.
 */
import { COMMANDS } from './commandRegistry'
import { fmtNum, fmtCap } from '@/lib/utils'

export interface ExecResult {
  ok: boolean
  markdown: string
}

async function jsonOrText(url: string, init?: RequestInit): Promise<any> {
  const r = await fetch(url, init)
  const text = await r.text()
  if (!r.ok) {
    try {
      const j = JSON.parse(text)
      return { __error: j.detail ?? text }
    } catch {
      return { __error: text.slice(0, 200) }
    }
  }
  try { return JSON.parse(text) } catch { return { __text: text } }
}

export async function execCommand(input: string): Promise<ExecResult | null> {
  const parts = input.trim().split(/\s+/)
  const name = parts[0]
  const args = parts.slice(1)
  const cmd = COMMANDS.find(c => c.name === name)
  if (!cmd) return null

  switch (name) {
    case '/help': {
      const lines = ['**可用命令：**', '']
      for (const c of COMMANDS) {
        lines.push(`- \`${c.name} ${c.args}\` — ${c.description}${c.example ? `\n   例：\`${c.example}\`` : ''}`)
      }
      return { ok: true, markdown: lines.join('\n') }
    }

    case '/quote': {
      if (!args[0]) return { ok: false, markdown: '用法：`/quote AAPL`' }
      const q = await jsonOrText(`/api/quote/${encodeURIComponent(args[0])}`)
      if (q.__error) return { ok: false, markdown: `✗ ${q.__error}` }
      const chg = q.change ?? 0
      const pct = q.change_pct ?? 0
      const arrow = chg >= 0 ? '▲' : '▼'
      return { ok: true, markdown:
        `**${q.symbol}** ${q.name ? `· ${q.name}` : ''}\n\n` +
        `Price: **$${fmtNum(q.price)}**  ${arrow} ${fmtNum(chg)} (${fmtNum(pct)}%)\n` +
        `High/Low: $${fmtNum(q.high)} / $${fmtNum(q.low)}\n` +
        `Volume: ${q.volume?.toLocaleString?.() ?? '—'}\n` +
        `Source: \`${q.source ?? '?'}\``
      }
    }

    case '/cn': {
      if (!args[0] || !/^\d{6}$/.test(args[0])) {
        return { ok: false, markdown: '用法：`/cn 600519`（六位 A 股代码）' }
      }
      const q = await jsonOrText(`/api/cn/quote/${args[0]}`)
      if (q.__error) return { ok: false, markdown: `✗ ${q.__error}` }
      const pct = q.change_pct ?? 0
      const arrow = (pct ?? 0) >= 0 ? '▲' : '▼'
      return { ok: true, markdown:
        `**${q.symbol}** A股\n\n` +
        `Price: **¥${fmtNum(q.price)}**  ${arrow} ${fmtNum(q.change)} (${fmtNum(pct)}%)\n` +
        `今开 / 昨收: ¥${fmtNum(q.open)} / ¥${fmtNum(q.prev_close)}\n` +
        `最高 / 最低: ¥${fmtNum(q.high)} / ¥${fmtNum(q.low)}\n` +
        `成交量: ${q.volume?.toLocaleString?.() ?? '—'}  换手率: ${fmtNum(q.turnover_rate_pct, 2)}%\n` +
        `涨停 / 跌停: ¥${fmtNum(q.limit_up)} / ¥${fmtNum(q.limit_down)}`
      }
    }

    case '/info': {
      if (!args[0] || !/^\d{6}$/.test(args[0])) {
        return { ok: false, markdown: '用法：`/info 600519`' }
      }
      const i = await jsonOrText(`/api/cn/info/${args[0]}`)
      if (i.__error) return { ok: false, markdown: `✗ ${i.__error}` }
      return { ok: true, markdown:
        `**${i.name}** (${i.symbol})\n\n` +
        `行业: ${i.industry ?? '—'}\n` +
        `总市值: ${fmtCap(i.market_cap)}  ·  流通市值: ${fmtCap(i.float_market_cap)}\n` +
        `总股本: ${i.total_shares?.toLocaleString?.() ?? '—'}\n` +
        `流通股: ${i.float_shares?.toLocaleString?.() ?? '—'}\n` +
        `上市: ${i.listed_date ?? '—'}`
      }
    }

    case '/news': {
      const qs = new URLSearchParams()
      qs.set('limit', '10')
      if (args[0]) qs.set('symbols', args[0])
      const n = await jsonOrText(`/api/news?${qs}`)
      if (n.__error) return { ok: false, markdown: `✗ ${n.__error}` }
      if (!n.entries?.length) return { ok: true, markdown: '_（没有最近新闻；Miniflux 里加订阅源。）_' }
      const lines = [`**最近 ${n.entries.length} 条新闻：**`, '']
      for (const e of n.entries.slice(0, 10)) {
        lines.push(`- [${e.title}](${e.url})  _${e.feed_title ?? ''}_`)
      }
      return { ok: true, markdown: lines.join('\n') }
    }

    case '/paper': {
      const sub = args[0] ?? 'account'
      const projectId = 'fin-core'  // TODO: make configurable
      if (sub === 'account') {
        const a = await jsonOrText(`/api/paper/account?project_id=${projectId}`)
        if (a.__error) return { ok: false, markdown: `✗ ${a.__error}` }
        return { ok: true, markdown:
          `**Paper Account** · ${projectId}\n\n` +
          `Cash: **$${fmtNum(a.cash)}**\n` +
          `Equity: **$${fmtNum(a.equity)}**\n` +
          `Total PnL: $${fmtNum(a.total_pnl)} (${fmtNum(a.total_pnl_pct)}%)\n` +
          `Realized: $${fmtNum(a.realized_pnl)}  ·  Unrealized: $${fmtNum(a.unrealized_pnl)}\n` +
          `Trades: ${a.total_trades} (${fmtNum(a.win_rate, 0)}% win)`
        }
      }
      if (sub === 'positions') {
        const p = await jsonOrText(`/api/paper/positions?project_id=${projectId}`)
        if (p.__error) return { ok: false, markdown: `✗ ${p.__error}` }
        if (!p.positions?.length) return { ok: true, markdown: '_（无持仓。）_' }
        const rows = p.positions.map((x: any) =>
          `- **${x.symbol}** ${x.side} ${x.quantity} @ $${fmtNum(x.entry_price)} → $${fmtNum(x.current_price)} PnL $${fmtNum(x.unrealized_pnl)} (${fmtNum(x.unrealized_pnl_pct)}%)`,
        )
        return { ok: true, markdown: `**Positions**\n\n${rows.join('\n')}` }
      }
      if (sub === 'trades') {
        const t = await jsonOrText(`/api/paper/trades?project_id=${projectId}&limit=10`)
        if (t.__error) return { ok: false, markdown: `✗ ${t.__error}` }
        if (!t.trades?.length) return { ok: true, markdown: '_（无历史成交。）_' }
        const rows = t.trades.slice(0, 10).map((x: any) =>
          `- ${(x.timestamp||'').slice(0, 16)}  **${x.symbol}**  ${x.side} ${x.quantity} @ $${fmtNum(x.price)}  PnL $${fmtNum(x.pnl)}`,
        )
        return { ok: true, markdown: `**Recent trades**\n\n${rows.join('\n')}` }
      }
      return { ok: false, markdown: '用法：`/paper account|positions|trades`' }
    }

    case '/audit': {
      const n = parseInt(args[0] ?? '5', 10) || 5
      const r = await jsonOrText(`/api/audit/recent?limit=${n}`)
      if (r.__error) return { ok: false, markdown: `✗ ${r.__error}` }
      if (!r.entries?.length) return { ok: true, markdown: '_（no audit entries yet）_' }
      const rows = r.entries.slice(0, n).map((e: any) => {
        const p = e.payload ?? {}
        const len = e.kind === 'response'
          ? `${(p.content || '').length}c · ${p.duration_ms ?? '?'}ms · ${p.usage?.total_tokens ?? '?'}tok`
          : `${(p.messages || []).length} turns`
        return `- [\`${e.kind}\`] ${e.ts.slice(11, 19)} · ${e.req_id.slice(0, 8)} · ${len}`
      })
      return { ok: true, markdown: `**Last ${r.entries.length} audit entries**\n\n${rows.join('\n')}\n\n→ 完整详情去 Audit tab` }
    }

    case '/analyze': {
      // Fall through: returning null signals "send as-is to fleet agent"
      return null
    }
  }
  return null
}
