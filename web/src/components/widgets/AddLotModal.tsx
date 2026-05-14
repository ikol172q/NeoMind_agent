/**
 * AddLotModal — manual lot entry form (Phase 1B).
 *
 * Per plan §11 OQ "manual UI" default. Simple form for ticker / qty
 * / cost basis / open date. CSV import is a future Phase 1C.
 */
import { useState } from 'react'
import { useAddLot } from '@/lib/api'
import { X } from 'lucide-react'

const TODAY = new Date().toISOString().slice(0, 10)

export function AddLotModal({
  initialTicker,
  onClose,
  onSuccess,
}: {
  initialTicker?: string
  onClose: () => void
  onSuccess?: (ticker: string) => void
}) {
  const [symbol, setSymbol] = useState(initialTicker || '')
  const [qty, setQty]       = useState('')
  const [price, setPrice]   = useState('')
  const [date, setDate]     = useState(TODAY)
  const [fees, setFees]     = useState('0')
  const [account, setAccount] = useState('main')
  const [assetClass, setAssetClass] = useState('stock')
  const [market, setMarket] = useState('US')
  const [notes, setNotes]   = useState('')
  const addMu = useAddLot()

  function submit() {
    const trimmedSym = symbol.trim().toUpperCase()
    const qtyN  = parseFloat(qty)
    const priceN = parseFloat(price)
    const feesN = parseFloat(fees) || 0
    if (!trimmedSym || isNaN(qtyN) || qtyN <= 0 || isNaN(priceN) || priceN < 0) {
      alert('需要: ticker / 数量 (>0) / 价格 (≥0)')
      return
    }
    addMu.mutate(
      {
        symbol: trimmedSym,
        market,
        asset_class: assetClass,
        open_date: date,
        open_price: priceN,
        open_quantity: qtyN,
        open_fees: feesN,
        account_id: account.trim() || 'main',
        notes: notes.trim() || undefined,
      },
      {
        onSuccess: () => {
          onSuccess?.(trimmedSym)
          onClose()
        },
        onError: (err) => alert(`add failed: ${err.message}`),
      },
    )
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed top-[10vh] left-1/2 -translate-x-1/2 w-[480px] max-w-[92vw] bg-[var(--color-bg)] border border-[var(--color-border)] rounded shadow-2xl z-50 flex flex-col"
           style={{ maxHeight: '85dvh' }}>
        {/* Header */}
        <div className="flex items-start gap-3 px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-panel)]/60">
          <div className="flex-1">
            <h2 className="text-[14px] font-semibold text-[var(--color-text)]">+ Add lot</h2>
            <div className="text-[10px] text-[var(--color-dim)] mt-0.5">
              手动录入一笔买入. 后续 CSV 导入是 Phase 1C 工作.
            </div>
          </div>
          <button onClick={onClose} className="text-[var(--color-dim)] hover:text-[var(--color-text)] p-1">
            <X size={16} />
          </button>
        </div>

        {/* Form */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 text-[11px]">
          <Row label="Ticker">
            <input
              type="text"
              autoFocus
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="NVDA / AAPL / FSKAX ..."
              className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[12px] font-mono outline-none focus:border-[var(--color-accent)]"
            />
          </Row>

          <div className="grid grid-cols-2 gap-3">
            <Row label="数量 (shares)">
              <input
                type="number"
                step="any"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                placeholder="100"
                className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[12px] font-mono outline-none focus:border-[var(--color-accent)]"
              />
            </Row>
            <Row label="买入价 (USD/share)">
              <input
                type="number"
                step="any"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="420.00"
                className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[12px] font-mono outline-none focus:border-[var(--color-accent)]"
              />
            </Row>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Row label="买入日期">
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[12px] font-mono outline-none focus:border-[var(--color-accent)]"
              />
            </Row>
            <Row label="手续费 (optional)">
              <input
                type="number"
                step="any"
                value={fees}
                onChange={(e) => setFees(e.target.value)}
                placeholder="0"
                className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[12px] font-mono outline-none focus:border-[var(--color-accent)]"
              />
            </Row>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Row label="Account">
              <input
                type="text"
                value={account}
                onChange={(e) => setAccount(e.target.value)}
                placeholder="main / schwab / fidelity-roth"
                className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[11px] font-mono outline-none focus:border-[var(--color-accent)]"
              />
            </Row>
            <Row label="Asset class">
              <select
                value={assetClass}
                onChange={(e) => setAssetClass(e.target.value)}
                className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[11px] outline-none"
              >
                <option value="stock">stock</option>
                <option value="etf">etf</option>
                <option value="mutual_fund">mutual_fund</option>
                <option value="crypto">crypto</option>
                <option value="option">option</option>
                <option value="future">future</option>
              </select>
            </Row>
            <Row label="Market">
              <select
                value={market}
                onChange={(e) => setMarket(e.target.value)}
                className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[11px] outline-none"
              >
                <option value="US">US</option>
                <option value="CN">CN</option>
                <option value="HK">HK</option>
              </select>
            </Row>
          </div>

          <Row label="Notes (optional)">
            <textarea
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="为什么买的 / 哪个 thesis / etc"
              className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[11px] outline-none focus:border-[var(--color-accent)] resize-y"
            />
          </Row>

          {/* Cost basis preview */}
          {qty && price && !isNaN(parseFloat(qty)) && !isNaN(parseFloat(price)) && (
            <div className="text-[11px] text-[var(--color-dim)] mt-2 italic">
              成本基础: ${(parseFloat(qty) * parseFloat(price) + (parseFloat(fees) || 0)).toFixed(2)}
              {' '}({parseFloat(qty)} × ${parseFloat(price)}{fees && parseFloat(fees) > 0 ? ` + $${fees} fees` : ''})
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-2 px-4 py-3 border-t border-[var(--color-border)] bg-[var(--color-panel)]/60">
          <button
            onClick={submit}
            disabled={addMu.isPending}
            className="text-[11px] px-3 py-1 rounded border border-emerald-500/40 hover:bg-emerald-500/10 text-emerald-300 disabled:opacity-50"
          >
            {addMu.isPending ? '保存中…' : 'Add lot'}
          </button>
          <button
            onClick={onClose}
            className="text-[11px] px-3 py-1 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
          >
            Cancel
          </button>
          {addMu.error && (
            <span className="text-[10px] text-red-300 ml-auto">err: {addMu.error.message}</span>
          )}
        </div>
      </div>
    </>
  )
}


function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)] mb-1">
        {label}
      </div>
      {children}
    </div>
  )
}
