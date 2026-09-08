import { Fragment, useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Trade, TradesResponse } from '../lib/api'
import { Card, PnlValue, EmptyState, Button, ProvenanceTag } from '../components/ui'

const PAGE_SIZE = 20

export function TradeExplorerPage() {
  const [data, setData] = useState<TradesResponse | null>(null)
  const [outcome, setOutcome] = useState<string>('')
  const [exitReason, setExitReason] = useState<string>('')
  const [page, setPage] = useState(0)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    api.trades({ outcome: outcome || undefined, exit_reason: exitReason || undefined, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
      .then(setData)
  }, [outcome, exitReason, page])

  const trades: Trade[] = data?.trades ?? []
  const total = data?.total ?? 0
  const hasNext = (page + 1) * PAGE_SIZE < total

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <h2 className="font-display font-bold text-2xl mb-1" style={{ color: 'var(--color-ink)' }}>Trade Explorer</h2>
        <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>
          A global, sortable, paginated trade table across all runs — with per-trade leg detail.
        </p>
      </div>

      <Card>
        <div className="flex items-center gap-3 mb-4">
          <select
            value={outcome}
            onChange={(e) => { setOutcome(e.target.value); setPage(0) }}
            className="rounded-lg border px-3 py-1.5 text-[13px] outline-none"
            style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
          >
            <option value="">All outcomes</option>
            <option value="win">Wins</option>
            <option value="loss">Losses</option>
          </select>
          <select
            value={exitReason}
            onChange={(e) => { setExitReason(e.target.value); setPage(0) }}
            className="rounded-lg border px-3 py-1.5 text-[13px] outline-none"
            style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
          >
            <option value="">All exit reasons</option>
            <option value="target">Target</option>
            <option value="stop">Stop</option>
            <option value="expiry">Expiry</option>
            <option value="end_of_data">End of data</option>
          </select>
          <span className="ml-auto text-[12px] font-mono" style={{ color: 'var(--color-ink-faint)' }}>{total} trade{total === 1 ? '' : 's'}</span>
          <ProvenanceTag kind="demo" />
        </div>

        {trades.length === 0 ? (
          <EmptyState
            icon={<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18M9 10v10" /></svg>}
            title="No trades yet"
            description="Run a backtest from Strategy Runner to generate trades."
          />
        ) : (
          <>
            <div className="overflow-x-auto thin-scroll">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left" style={{ color: 'var(--color-ink-faint)' }}>
                    {['Symbol', 'Strategy', 'Entry', 'Exit', 'Net P&L', 'Exit reason', ''].map((h) => (
                      <th key={h} className="font-medium px-3 py-2 text-[11px] uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t) => (
                    <Fragment key={t.trade_id}>
                      <tr className="border-t cursor-pointer" style={{ borderColor: 'var(--color-border)' }}
                        onClick={() => setExpanded(expanded === t.trade_id ? null : t.trade_id)}>
                        <td className="px-3 py-2.5 font-mono font-medium" style={{ color: 'var(--color-ink)' }}>{t.symbol}</td>
                        <td className="px-3 py-2.5 font-mono text-[12px]" style={{ color: 'var(--color-ink-muted)' }}>{t.strategy_side}</td>
                        <td className="px-3 py-2.5 font-mono text-[12px]" style={{ color: 'var(--color-ink-muted)' }}>{t.entry_date}</td>
                        <td className="px-3 py-2.5 font-mono text-[12px]" style={{ color: 'var(--color-ink-muted)' }}>{t.exit_date}</td>
                        <td className="px-3 py-2.5"><PnlValue value={t.net_pnl} size="sm" /></td>
                        <td className="px-3 py-2.5 font-mono text-[12px]" style={{ color: 'var(--color-ink-muted)' }}>{t.exit_reason}</td>
                        <td className="px-3 py-2.5 text-[12px]" style={{ color: 'var(--color-accent)' }}>{expanded === t.trade_id ? 'hide legs' : 'view legs'}</td>
                      </tr>
                      {expanded === t.trade_id && (
                        <tr style={{ background: 'var(--color-paper)' }}>
                          <td colSpan={7} className="px-3 py-3">
                            <div className="font-mono text-[12px] space-y-1" style={{ color: 'var(--color-ink-muted)' }}>
                              {t.legs.map((l) => (
                                <div key={l.leg_id}>
                                  {l.action.toUpperCase()} {l.strike} {l.option_type} (exp {l.expiry}) @ {l.entry_price.toFixed(2)} → {l.exit_price?.toFixed(2) ?? '—'}
                                </div>
                              ))}
                              <div style={{ color: 'var(--color-ink-faint)' }}>lot_size={t.lot_size} · lots={t.lots} · gross={t.gross_pnl.toFixed(2)} · costs={t.costs.toFixed(2)}</div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between mt-4">
              <span className="text-[12px] font-mono" style={{ color: 'var(--color-ink-faint)' }}>
                {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <Button variant="secondary" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button variant="secondary" disabled={!hasNext} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
