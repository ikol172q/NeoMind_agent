/**
 * AlertsBell — 全局「预警 / 提案」铃铛(header).
 *
 * 显示未读(new/pushed)提案数;点开列出 agent_alerts —— 与 Telegram 推送的是
 * **同一张表**(=你要的"dashboard 同步推送")。每条是提案员产物:带证据 + 提议 +
 * "你来定";铃铛只展示 + 标记 seen/acted,**绝不替你下单**。
 */
import { useState, useRef, useEffect } from 'react'
import { Bell } from 'lucide-react'
import { useAlerts, useSetAlertStatus } from '@/lib/api'
import { fmtTs } from '@/lib/utils'

const SEV: Record<string, string> = { P1: 'text-red-400', P2: 'text-amber-400', 破: 'text-red-400', 动摇: 'text-amber-400' }

export function AlertsBell() {
  const { data } = useAlerts()
  const setStatus = useSetAlertStatus()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  const alerts = data?.alerts ?? []
  const unread = alerts.filter(a => a.status === 'new' || a.status === 'pushed').length

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className="relative p-1.5 rounded hover:bg-[var(--color-border)]"
        title="预警 / 提案(与 Telegram 同步)"
      >
        <Bell size={18} />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-amber-500 text-black text-[10px] font-bold flex items-center justify-center">
            {unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-[360px] max-h-[70vh] overflow-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] shadow-xl z-50 p-2">
          <div className="flex items-center justify-between px-1 py-1 text-xs text-[var(--color-dim)]">
            <span>预警 / 提案(与 Telegram 同步)</span>
            {data && !data.chat_ready && <span className="text-amber-400">Telegram 未配 chat</span>}
          </div>
          {alerts.length === 0 && (
            <div className="px-2 py-6 text-center text-sm text-[var(--color-dim)]">暂无提案(论点暂稳)</div>
          )}
          {alerts.map(a => (
            <div key={a.id} className="border-t border-[var(--color-border)] py-2 px-1">
              <div className="flex items-center justify-between">
                <span className={`text-sm font-semibold ${SEV[a.severity] ?? ''}`}>{a.title}</span>
                <span className="text-[10px] text-[var(--color-dim)]">{fmtTs(a.created_at)}</span>
              </div>
              <pre className="whitespace-pre-wrap text-xs text-[var(--color-text)] mt-1 font-sans leading-snug">
                {a.body}
              </pre>
              <div className="flex gap-3 mt-1 items-center">
                {a.status !== 'seen' && a.status !== 'acted' && (
                  <button
                    onClick={() => setStatus.mutate({ id: a.id, status: 'seen' })}
                    className="text-[10px] text-[var(--color-dim)] hover:text-[var(--color-text)]"
                  >
                    标记已读
                  </button>
                )}
                <button
                  onClick={() => setStatus.mutate({ id: a.id, status: 'acted' })}
                  className="text-[10px] text-[var(--color-dim)] hover:text-emerald-400"
                >
                  我已处理
                </button>
                <span className="text-[10px] text-[var(--color-dim)] ml-auto">{a.status}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
