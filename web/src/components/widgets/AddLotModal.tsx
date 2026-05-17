/**
 * AddLotModal — manual lot entry / edit.
 *
 * Default mode is "Simple": only ticker + shares required (price
 * auto-fetched from live quote via /api/positions/quick_set). This is
 * the daily-driver path — useful when you just want to track that you
 * hold N shares of X without caring about exact lot accounting.
 *
 * Toggle "Advanced" to expose date / fees / account / asset_class /
 * market / notes — needed for precise tax_lot tracking, wash sales,
 * multi-account portfolios.
 *
 * In edit mode (lot prop given), uses PATCH /api/positions/lots/{id}
 * — only mutable fields shown.
 */
import { useState } from 'react'
import { useAddLot, useQuickSetHoldings, useUpdateLot, type TaxLot } from '@/lib/api'
import { X, Settings } from 'lucide-react'

const TODAY = new Date().toISOString().slice(0, 10)

interface AddLotModalProps {
  initialTicker?: string
  /** When given, the modal is in EDIT mode (PATCH existing lot). */
  lot?: TaxLot
  onClose: () => void
  onSuccess?: (ticker: string) => void
}

export function AddLotModal({ initialTicker, lot, onClose, onSuccess }: AddLotModalProps) {
  const isEdit = !!lot
  const [advanced, setAdvanced] = useState<boolean>(isEdit)

  const [symbol, setSymbol] = useState((lot?.symbol || initialTicker || '').toUpperCase())
  const [qty, setQty]       = useState(lot ? String(lot.open_quantity) : '')
  const [price, setPrice]   = useState(lot ? String(lot.open_price) : '')
  const [date, setDate]     = useState(lot?.open_date || TODAY)
  const [fees, setFees]     = useState(lot ? String(lot.open_fees ?? 0) : '0')
  const [account, setAccount] = useState(lot?.account_id || 'main')
  const [assetClass, setAssetClass] = useState(lot?.asset_class || 'stock')
  const [market, setMarket] = useState(lot?.market || 'US')
  const [notes, setNotes]   = useState(lot?.notes || '')

  const quickMu  = useQuickSetHoldings()
  const addMu    = useAddLot()
  const updateMu = useUpdateLot()

  const busy = quickMu.isPending || addMu.isPending || updateMu.isPending
  const lastError = quickMu.error || addMu.error || updateMu.error

  function submit() {
    const trimmedSym = symbol.trim().toUpperCase()
    const qtyN  = parseFloat(qty)
    if (!trimmedSym || isNaN(qtyN) || qtyN <= 0) {
      alert('需要: ticker + 数量 (>0)')
      return
    }

    if (isEdit && lot) {
      const patch: Record<string, unknown> = { lot_id: lot.lot_id }
      if (qtyN !== lot.open_quantity) patch.open_quantity = qtyN
      const priceN = parseFloat(price)
      if (!isNaN(priceN) && priceN !== lot.open_price) patch.open_price = priceN
      const feesN = parseFloat(fees)
      if (!isNaN(feesN) && feesN !== (lot.open_fees ?? 0)) patch.open_fees = feesN
      if (date && date !== lot.open_date) patch.open_date = date
      if (notes.trim() !== (lot.notes || '')) patch.notes = notes.trim() || null
      if (Object.keys(patch).length === 1) { onClose(); return }
      updateMu.mutate(patch as Parameters<typeof updateMu.mutate>[0], {
        onSuccess: () => { onSuccess?.(trimmedSym); onClose() },
        onError:   (err) => alert(`update failed: ${err.message}`),
      })
      return
    }

    if (!advanced) {
      const priceN = price.trim() ? parseFloat(price) : undefined
      quickMu.mutate(
        { ticker: trimmedSym, shares: qtyN,
          cost_basis: priceN !== undefined && !isNaN(priceN) ? priceN : undefined,
          notes: notes.trim() || undefined },
        {
          onSuccess: () => { onSuccess?.(trimmedSym); onClose() },
          onError:   (err) => alert(`保存失败: ${err.message}`),
        },
      )
      return
    }

    const priceN = parseFloat(price)
    const feesN = parseFloat(fees) || 0
    if (isNaN(priceN) || priceN < 0) {
      alert('advanced 模式需要: 买入价 (≥0)')
      return
    }
    addMu.mutate(
      { symbol: trimmedSym, market, asset_class: assetClass,
        open_date: date, open_price: priceN, open_quantity: qtyN,
        open_fees: feesN, account_id: account.trim() || 'main',
        notes: notes.trim() || undefined },
      {
        onSuccess: () => { onSuccess?.(trimmedSym); onClose() },
        onError:   (err) => alert(`add failed: ${err.message}`),
      },
    )
  }

  const title = isEdit ? `✏️ 修改 ${lot?.symbol}` : (advanced ? '+ Add lot (advanced)' : '+ 加 / 改 持仓')

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed top-[10vh] left-1/2 -translate-x-1/2 w-[480px] max-w-[92vw] bg-[var(--color-bg)] border border-[var(--color-border)] rounded shadow-2xl z-50 flex flex-col"
           style={{ maxHeight: '85dvh' }}
           data-testid="add-lot-modal">
        <div className="flex items-start gap-3 px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-panel)]/60">
          <div className="flex-1">
            <h2 className="text-[14px] font-semibold text-[var(--color-text)]">{title}</h2>
            <div className="text-[10px] text-[var(--color-dim)] mt-0.5">
              {isEdit
                ? '改你的持仓信息. 不变的字段留空.'
                : (advanced
                   ? '完整 lot 记录 (tax 用): 包含日期/手续费/账户等'
                   : '只录 ticker + 股数; 不填买入价 → 用当前市价')}
            </div>
          </div>
          {!isEdit && (
            <button
              onClick={() => setAdvanced(a => !a)}
              title={advanced ? '收起 advanced' : '展开 advanced (tax 精确)'}
              className="text-[10px] px-2 py-1 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)] flex items-center gap-1"
              data-testid="add-lot-advanced-toggle"
            >
              <Settings size={11} /> {advanced ? 'simple' : 'advanced'}
            </button>
          )}
          <button onClick={onClose} className="text-[var(--color-dim)] hover:text-[var(--color-text)] p-1">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3 text-[11px]">
          <Row label="Ticker">
            <input
              type="text" autoFocus disabled={isEdit}
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="NVDA / AAPL / FSKAX ..."
              className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[12px] font-mono outline-none focus:border-[var(--color-accent)] disabled:opacity-50"
              data-testid="add-lot-ticker"
            />
          </Row>

          <div className="grid grid-cols-2 gap-3">
            <Row label="数量 (shares)">
              <input
                type="number" step="any" value={qty}
                onChange={(e) => setQty(e.target.value)}
                placeholder="100"
                className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[12px] font-mono outline-none focus:border-[var(--color-accent)]"
                data-testid="add-lot-qty"
              />
            </Row>
            <Row label={advanced ? "买入价 (USD/share)" : "买入价 (可留空 → 用市价)"}>
              <input
                type="number" step="any" value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder={advanced ? "420.00" : "(留空用市价)"}
                className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[12px] font-mono outline-none focus:border-[var(--color-accent)]"
                data-testid="add-lot-price"
              />
            </Row>
          </div>

          {advanced && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Row label="买入日期">
                  <input
                    type="date" value={date}
                    onChange={(e) => setDate(e.target.value)}
                    className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[12px] font-mono outline-none focus:border-[var(--color-accent)]"
                  />
                </Row>
                <Row label="手续费 (optional)">
                  <input
                    type="number" step="any" value={fees}
                    onChange={(e) => setFees(e.target.value)}
                    placeholder="0"
                    className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[12px] font-mono outline-none focus:border-[var(--color-accent)]"
                  />
                </Row>
              </div>

              {!isEdit && (
                <div className="grid grid-cols-3 gap-3">
                  <Row label="Account">
                    <input
                      type="text" value={account}
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
              )}
            </>
          )}

          <Row label="Notes (optional)">
            <textarea
              rows={2} value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="为什么买的 / 哪个 thesis / etc"
              className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-[11px] outline-none focus:border-[var(--color-accent)] resize-y"
            />
          </Row>

          {qty && price && !isNaN(parseFloat(qty)) && !isNaN(parseFloat(price)) && (
            <div className="text-[11px] text-[var(--color-dim)] mt-2 italic">
              成本基础: ${(parseFloat(qty) * parseFloat(price) + (parseFloat(fees) || 0)).toFixed(2)}
              {' '}({parseFloat(qty)} × ${parseFloat(price)}{advanced && fees && parseFloat(fees) > 0 ? ` + $${fees} fees` : ''})
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 px-4 py-3 border-t border-[var(--color-border)] bg-[var(--color-panel)]/60">
          <button
            onClick={submit}
            disabled={busy}
            className="text-[11px] px-3 py-1 rounded border border-emerald-500/40 hover:bg-emerald-500/10 text-emerald-300 disabled:opacity-50"
            data-testid="add-lot-submit"
          >
            {busy ? '保存中…' : (isEdit ? '保存修改' : (advanced ? 'Add lot' : '保存'))}
          </button>
          <button
            onClick={onClose}
            className="text-[11px] px-3 py-1 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
          >
            Cancel
          </button>
          {lastError && (
            <span className="text-[10px] text-red-300 ml-auto">err: {lastError.message}</span>
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
