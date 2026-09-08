import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { DataCoverage, RunRecord, Stats } from '../lib/api'
import { Card, CardSubtitle, CardTitle, EmptyState, PnlValue, ProvenanceTag, StatBlock } from '../components/ui'
import { LiveMarketPanel } from '../components/LiveMarketPanel'

export function OverviewPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [symbols, setSymbols] = useState<string[]>([])
  const [coverage, setCoverage] = useState<DataCoverage[]>([])
  const [runs, setRuns] = useState<RunRecord[]>([])

  useEffect(() => {
    Promise.all([api.stats(), api.symbols(), api.listRuns()])
      .then(([nextStats, nextSymbols, nextRuns]) => {
        setStats(nextStats)
        setSymbols(nextSymbols)
        setRuns(nextRuns)
      })
      .catch(() => {
        setStats(null)
        setSymbols([])
        setRuns([])
      })
  }, [])

  useEffect(() => {
    if (!symbols.length) {
      setCoverage([])
      return
    }

    const visibleSymbols = symbols.slice(0, 6)
    Promise.all(visibleSymbols.map((symbol) => api.dataCoverage(symbol)))
      .then(setCoverage)
      .catch(() => setCoverage([]))
  }, [symbols])

  const summary = useMemo(() => {
    const successful = runs.filter((run) => run.status === 'success')
    const latest = successful[0] ?? null
    const totalPnl = successful.reduce((sum, run) => sum + (run.total_net_pnl ?? 0), 0)
    return {
      latest,
      totalPnl,
      successfulCount: successful.length,
    }
  }, [runs])

  return (
    <div className="max-w-6xl space-y-6">
      <div className="overview-hero">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] mb-2" style={{ color: 'var(--color-accent)' }}>Operations overview / 00</div>
        <h2 className="font-display font-bold text-3xl mb-1" style={{ color: 'var(--color-ink)' }}>Market Overview</h2>
        <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>
          High-signal context for the dataset, live coverage, and recent research activity.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="metric-card">
          <StatBlock label="Equity rows" value={stats?.equity_rows ?? '—'} />
        </Card>
        <Card className="metric-card">
          <StatBlock label="Options rows" value={stats?.options_rows ?? '—'} />
        </Card>
        <Card className="metric-card">
          <StatBlock label="Tracked symbols" value={stats?.stocks ?? '—'} />
        </Card>
        <Card className="metric-card">
          <StatBlock label="Saved runs" value={runs.length || '—'} />
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card>
          <div className="flex items-center justify-between mb-4">
            <CardTitle>Coverage snapshot</CardTitle>
            <ProvenanceTag kind="demo" />
          </div>

          {coverage.length === 0 ? (
            <EmptyState
              icon={<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5" /><path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3" /></svg>}
              title="No symbol coverage yet"
              description="Import a dataset or sync live market data to populate this view."
            />
          ) : (
            <div className="space-y-3">
              {coverage.map((item) => (
                <div key={item.symbol} className="rounded-lg border p-3" style={{ borderColor: 'var(--color-border)' }}>
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <div className="font-mono text-[13px]" style={{ color: 'var(--color-ink)' }}>{item.symbol}</div>
                    <span className="text-[11px] font-mono" style={{ color: 'var(--color-ink-faint)' }}>
                      {item.equity_rows} eq · {item.option_rows} opt
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-[12px] font-mono" style={{ color: 'var(--color-ink-muted)' }}>
                    <div>
                      <div style={{ color: 'var(--color-ink-faint)' }}>Equity range</div>
                      <div>{item.equity_start ?? '—'} → {item.equity_end ?? '—'}</div>
                    </div>
                    <div>
                      <div style={{ color: 'var(--color-ink-faint)' }}>Option range</div>
                      <div>{item.option_start ?? '—'} → {item.option_end ?? '—'}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <div className="flex items-center justify-between mb-4">
            <CardTitle>Recent research</CardTitle>
            <ProvenanceTag kind="demo" />
          </div>

          {runs.length === 0 ? (
            <EmptyState
              icon={<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="9" /><path d="M10 9l5 3-5 3V9Z" fill="currentColor" stroke="none" /></svg>}
              title="No runs yet"
              description="Run a strategy backtest to start building a research history."
            />
          ) : (
            <div className="space-y-3">
              {runs.slice(0, 5).map((run) => (
                <div key={run.run_id} className="rounded-lg border p-3" style={{ borderColor: 'var(--color-border)' }}>
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <div className="font-mono text-[12px]" style={{ color: 'var(--color-ink)' }}>{run.strategy_id} v{run.strategy_version}</div>
                    <PnlValue value={run.total_net_pnl} size="sm" />
                  </div>
                  <div className="text-[12px] font-mono" style={{ color: 'var(--color-ink-muted)' }}>
                    {run.selected_stocks || '—'} · {new Date(run.created_at).toLocaleString()}
                  </div>
                  <div className="mt-2 text-[11px] uppercase tracking-wider" style={{ color: 'var(--color-ink-faint)' }}>
                    {run.status} · {run.num_trades ?? 0} trades · {run.win_rate === null ? '—' : `${(run.win_rate * 100).toFixed(0)}%`} win rate
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <LiveMarketPanel />

      <Card>
        <div className="flex items-center justify-between gap-3 mb-3">
          <CardTitle>Strategy health</CardTitle>
          <ProvenanceTag kind="live" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="rounded-lg border p-4" style={{ borderColor: 'var(--color-border)' }}>
            <div className="text-[11px] uppercase tracking-wider mb-2" style={{ color: 'var(--color-ink-faint)' }}>Successful runs</div>
            <div className="font-display text-3xl" style={{ color: 'var(--color-ink)' }}>{summary.successfulCount}</div>
          </div>

          <div className="rounded-lg border p-4" style={{ borderColor: 'var(--color-border)' }}>
            <div className="text-[11px] uppercase tracking-wider mb-2" style={{ color: 'var(--color-ink-faint)' }}>Aggregate P&amp;L</div>
            <div className="font-display text-3xl" style={{ color: 'var(--color-ink)' }}>
              <PnlValue value={summary.totalPnl} size="lg" />
            </div>
          </div>

          <div className="rounded-lg border p-4" style={{ borderColor: 'var(--color-border)' }}>
            <div className="text-[11px] uppercase tracking-wider mb-2" style={{ color: 'var(--color-ink-faint)' }}>Latest result</div>
            <div className="font-mono text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>
              {summary.latest ? `${summary.latest.strategy_id} · ${summary.latest.status}` : 'No result yet'}
            </div>
          </div>
        </div>
        <CardSubtitle>Good operational telemetry is the first signal that a strategy system is healthy before you trust the numbers.</CardSubtitle>
      </Card>
    </div>
  )
}
