import { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { api } from '../lib/api'
import type { RunRecord, CompareRun } from '../lib/api'
import { Card, CardTitle, CardSubtitle, PnlValue, BlockedNotice, ProvenanceTag } from '../components/ui'

const LINE_COLORS = ['#4F6EF7', '#16A34A', '#D97706', '#DC2626', '#9333EA']

export function CompareRunsPage() {
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [comparison, setComparison] = useState<CompareRun[] | null>(null)

  useEffect(() => { api.listRuns().then((r) => setRuns(r.filter((x) => x.status === 'success'))) }, [])

  useEffect(() => {
    if (selected.length >= 2) {
      api.compareRuns(selected).then(setComparison)
    } else {
      setComparison(null)
    }
  }, [selected])

  function toggle(runId: string) {
    setSelected((s) => (s.includes(runId) ? s.filter((x) => x !== runId) : [...s, runId]))
  }

  if (runs.length < 2) {
    return (
      <div className="max-w-4xl space-y-6">
        <div>
          <h2 className="font-display font-bold text-2xl mb-1" style={{ color: 'var(--color-ink)' }}>Compare Runs</h2>
          <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>
            Select two or more saved runs and compare total P&amp;L, trade count, win rate, average holding
            period, P&amp;L by stock, and cumulative P&amp;L. Comparison reads saved run results only — strategies are never re-executed.
          </p>
        </div>
        <BlockedNotice
          title="Blocked — required input not supplied"
          reasons={[`At least 2 completed backtest runs (found ${runs.length})`]}
        />
      </div>
    )
  }

  // merge cumulative series by date for the chart
  const chartData: Record<string, Record<string, number | string>> = {}
  comparison?.forEach((run, idx) => {
    run.cumulative_pnl.forEach((point) => {
      if (!chartData[point.date]) chartData[point.date] = { date: point.date }
      chartData[point.date][`run${idx}`] = point.cumulative_pnl
    })
  })
  const chartArr = Object.values(chartData).sort((a, b) => String(a.date).localeCompare(String(b.date)))

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <h2 className="font-display font-bold text-2xl mb-1" style={{ color: 'var(--color-ink)' }}>Compare Runs</h2>
        <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>
          Select two or more saved runs. Comparison reads saved run results only — strategies are never re-executed.
        </p>
      </div>

      <Card>
        <CardTitle>Select runs</CardTitle>
        <div className="space-y-2 mt-2">
          {runs.map((r) => (
            <label key={r.run_id} className="flex items-center gap-3 p-2 rounded-lg cursor-pointer" style={{ background: selected.includes(r.run_id) ? 'var(--color-border)' : 'transparent' }}>
              <input type="checkbox" checked={selected.includes(r.run_id)} onChange={() => toggle(r.run_id)} />
              <span className="font-mono text-[12px]" style={{ color: 'var(--color-ink-muted)' }}>{r.run_id.slice(0, 8)}</span>
              <span className="text-[13px]" style={{ color: 'var(--color-ink)' }}>{r.strategy_id} v{r.strategy_version}</span>
              <span className="text-[12px] font-mono" style={{ color: 'var(--color-ink-faint)' }}>{new Date(r.created_at).toLocaleString()}</span>
              <span className="ml-auto"><PnlValue value={r.total_net_pnl} size="sm" /></span>
            </label>
          ))}
        </div>
      </Card>

      {comparison && (
        <>
          <Card>
            <div className="flex items-center justify-between mb-4">
              <CardTitle>Metrics</CardTitle>
              <ProvenanceTag kind="demo" />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left" style={{ color: 'var(--color-ink-faint)' }}>
                    <th className="font-medium px-3 py-2 text-[11px] uppercase tracking-wider">Run</th>
                    <th className="font-medium px-3 py-2 text-[11px] uppercase tracking-wider">Net P&amp;L</th>
                    <th className="font-medium px-3 py-2 text-[11px] uppercase tracking-wider">Trades</th>
                    <th className="font-medium px-3 py-2 text-[11px] uppercase tracking-wider">Win rate</th>
                    <th className="font-medium px-3 py-2 text-[11px] uppercase tracking-wider">Avg holding (days)</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.map((r, idx) => (
                    <tr key={r.run_id} className="border-t" style={{ borderColor: 'var(--color-border)' }}>
                      <td className="px-3 py-2.5 flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full" style={{ background: LINE_COLORS[idx % LINE_COLORS.length] }} />
                        <span className="font-mono text-[12px]" style={{ color: 'var(--color-ink)' }}>{r.run_id.slice(0, 8)}</span>
                      </td>
                      <td className="px-3 py-2.5"><PnlValue value={r.total_net_pnl} /></td>
                      <td className="px-3 py-2.5 font-mono" style={{ color: 'var(--color-ink-muted)' }}>{r.num_trades}</td>
                      <td className="px-3 py-2.5 font-mono" style={{ color: 'var(--color-ink-muted)' }}>{r.win_rate !== null ? `${(r.win_rate * 100).toFixed(0)}%` : '—'}</td>
                      <td className="px-3 py-2.5 font-mono" style={{ color: 'var(--color-ink-muted)' }}>{r.avg_holding_days?.toFixed(1) ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card>
            <CardTitle>Cumulative P&amp;L</CardTitle>
            <CardSubtitle>By trade exit date, per run.</CardSubtitle>
            <div style={{ height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartArr}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fontFamily: 'JetBrains Mono' }} stroke="var(--color-ink-faint)" />
                  <YAxis tick={{ fontSize: 11, fontFamily: 'JetBrains Mono' }} stroke="var(--color-ink-faint)" />
                  <Tooltip contentStyle={{ fontFamily: 'JetBrains Mono', fontSize: 12, background: 'var(--color-surface)', border: '1px solid var(--color-border)' }} />
                  {comparison.map((_, idx) => (
                    <Line key={idx} type="monotone" dataKey={`run${idx}`} stroke={LINE_COLORS[idx % LINE_COLORS.length]} strokeWidth={2} dot={false} connectNulls />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
