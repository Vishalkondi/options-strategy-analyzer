import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { StrategySpec, RunRecord, Trade } from '../lib/api'
import { Card, CardTitle, CardSubtitle, Button, ProvenanceTag, PnlValue, StatBlock, Spinner, EmptyState } from '../components/ui'

export function StrategyRunnerPage() {
  const [strategies, setStrategies] = useState<StrategySpec[]>([])
  const [symbols, setSymbols] = useState<string[]>([])
  const [selectedStrategy, setSelectedStrategy] = useState<string>('')
  const [selectedSymbol, setSelectedSymbol] = useState<string>('')
  const [dateStart, setDateStart] = useState('')
  const [dateEnd, setDateEnd] = useState('')
  const [params, setParams] = useState<Record<string, number>>({})
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<RunRecord | null>(null)
  const [trades, setTrades] = useState<Trade[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.strategies().then((s) => {
      setStrategies(s)
      if (s.length && !selectedStrategy) {
        setSelectedStrategy(s[0].file)
        setParams(Object.fromEntries(Object.entries(s[0].parameters).map(([k, v]) => [k, v.default])))
      }
    })
    api.symbols().then(setSymbols)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const strategy = strategies.find((s) => s.file === selectedStrategy)

  function onStrategyChange(file: string) {
    setSelectedStrategy(file)
    const s = strategies.find((x) => x.file === file)
    if (s) setParams(Object.fromEntries(Object.entries(s.parameters).map(([k, v]) => [k, v.default])))
  }

  async function handleRun() {
    setRunning(true)
    setError(null)
    setResult(null)
    setTrades(null)
    try {
      const run = await api.createRun({
        strategy_file: selectedStrategy,
        symbol: selectedSymbol,
        date_start: dateStart || undefined,
        date_end: dateEnd || undefined,
        params,
      })
      setResult(run)
      if (run.status === 'success') {
        const t = await api.runTrades(run.run_id)
        setTrades(t)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }

  const canRun = selectedStrategy && selectedSymbol && !running

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.18em] mb-2" style={{ color: 'var(--color-accent)' }}>Research workspace / 01</div>
            <h2 className="font-display font-bold text-3xl mb-1" style={{ color: 'var(--color-ink)' }}>Strategy Runner</h2>
            <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>
              Turn a market hypothesis into a reproducible backtest.
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider" style={{ borderColor: 'var(--color-border)', color: 'var(--color-ink-muted)', background: 'var(--color-surface)' }}>
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'var(--color-warn)' }} />
            Historical mode
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6 items-start">
        <div className="space-y-6">
          <Card>
            <CardTitle>Strategy</CardTitle>
            {strategies.length === 0 ? (
              <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>No strategies registered.</p>
            ) : (
              <>
                <select
                  value={selectedStrategy}
                  onChange={(e) => onStrategyChange(e.target.value)}
                  className="w-full rounded-lg border px-3.5 py-2 text-[13.5px] outline-none mb-2"
                  style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
                >
                  {strategies.map((s) => <option key={s.file} value={s.file}>{s.name} (v{s.version})</option>)}
                </select>
                <ProvenanceTag kind="demo" />
              </>
            )}
          </Card>

          <Card>
            <CardTitle>Symbol &amp; date range</CardTitle>
            {symbols.length === 0 ? (
              <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>No data imported. Use the Data Manager first.</p>
            ) : (
              <div className="space-y-3">
                <select
                  value={selectedSymbol}
                  onChange={(e) => setSelectedSymbol(e.target.value)}
                  className="w-full rounded-lg border px-3.5 py-2 text-[13.5px] outline-none"
                  style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
                >
                  <option value="">Select a symbol…</option>
                  {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] uppercase tracking-wider mb-1 block" style={{ color: 'var(--color-ink-faint)' }}>Start</label>
                    <input type="date" value={dateStart} onChange={(e) => setDateStart(e.target.value)}
                      className="w-full rounded-lg border px-3 py-2 text-[13px] font-mono outline-none"
                      style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }} />
                  </div>
                  <div>
                    <label className="text-[11px] uppercase tracking-wider mb-1 block" style={{ color: 'var(--color-ink-faint)' }}>End</label>
                    <input type="date" value={dateEnd} onChange={(e) => setDateEnd(e.target.value)}
                      className="w-full rounded-lg border px-3 py-2 text-[13px] font-mono outline-none"
                      style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }} />
                  </div>
                </div>
              </div>
            )}
          </Card>

          {strategy && (
            <Card>
              <CardTitle>Parameters</CardTitle>
              <CardSubtitle>Generated from the strategy descriptor.</CardSubtitle>
              <div className="grid grid-cols-2 gap-4">
                {Object.entries(strategy.parameters).map(([key, spec]) => (
                  <div key={key}>
                    <label className="text-[11px] uppercase tracking-wider mb-1 block font-mono" style={{ color: 'var(--color-ink-faint)' }}>
                      {key}
                    </label>
                    <input
                      type="number"
                      step="any"
                      min={spec.min}
                      max={spec.max}
                      value={params[key] ?? spec.default}
                      onChange={(e) => setParams((p) => ({ ...p, [key]: Number(e.target.value) }))}
                      className="w-full rounded-lg border px-3 py-1.5 text-[13px] font-mono outline-none"
                      style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
                    />
                    {spec.description && (
                      <div className="text-[11px] mt-1" style={{ color: 'var(--color-warn)' }}>{spec.description}</div>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Button onClick={handleRun} disabled={!canRun} className="w-full py-3">
            {running ? <Spinner size={14} /> : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7-11-7Z" /></svg>
            )}
            Run backtest
          </Button>
          {error && <div className="text-[13px]" style={{ color: 'var(--color-loss)' }}>{error}</div>}
        </div>

        <div className="space-y-6">
          {!result ? (
            <Card className="h-full flex items-center justify-center">
              <EmptyState
                icon={<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="9" /><path d="M10 9l5 3-5 3V9Z" /></svg>}
                title="No run yet"
                description="Configure a strategy and symbol, then run a backtest to see results here."
              />
            </Card>
          ) : (
            <>
              <Card>
                <div className="flex items-center justify-between mb-4">
                  <CardTitle>Run result</CardTitle>
                  <ProvenanceTag kind={result.status === 'blocked' ? 'blocked' : 'demo'} />
                </div>
                {result.status === 'blocked' ? (
                  <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>{result.error_message}</p>
                ) : (
                  <div className="grid grid-cols-3 gap-5">
                    <StatBlock label="Net P&L" value={<PnlValue value={result.total_net_pnl} size="lg" />} mono={false} />
                    <StatBlock label="Trades" value={result.num_trades ?? 0} />
                    <StatBlock label="Win rate" value={result.win_rate !== null ? `${(result.win_rate * 100).toFixed(0)}%` : '—'} />
                  </div>
                )}
                <div className="mt-4 pt-4 border-t text-[11px] font-mono space-y-1" style={{ borderColor: 'var(--color-border)', color: 'var(--color-ink-faint)' }}>
                  <div>run_id: {result.run_id}</div>
                  <div>params_hash: {result.params_hash} · data_snapshot: {result.data_snapshot_id ?? '—'}</div>
                  <div>duration: {result.duration_ms}ms</div>
                </div>
              </Card>

              {trades && trades.length > 0 && (
                <Card>
                  <CardTitle>Trades</CardTitle>
                  <div className="space-y-2 mt-3">
                    {trades.map((t) => (
                      <div key={t.trade_id} className="rounded-lg border p-3" style={{ borderColor: 'var(--color-border)' }}>
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-mono text-[12px]" style={{ color: 'var(--color-ink-muted)' }}>
                            {t.strategy_side} · {t.entry_date} → {t.exit_date} · {t.exit_reason}
                          </span>
                          <PnlValue value={t.net_pnl} size="sm" />
                        </div>
                        <div className="text-[12px] font-mono space-y-0.5" style={{ color: 'var(--color-ink-faint)' }}>
                          {t.legs.map((l) => (
                            <div key={l.leg_id}>
                              {l.action.toUpperCase()} {l.strike} {l.option_type} @ {l.entry_price.toFixed(2)} → {l.exit_price?.toFixed(2) ?? '—'}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
              {trades && trades.length === 0 && (
                <Card>
                  <EmptyState title="No trades generated" description="No entry signal fired for this symbol/date range/parameter combination." />
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
