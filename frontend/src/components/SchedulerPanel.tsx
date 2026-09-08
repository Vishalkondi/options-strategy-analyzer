import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { CaptureCycle, SchedulerStatus } from '../lib/api'

const STATUS_COLOR: Record<string, string> = {
  SUCCESS: 'var(--color-profit)',
  PARTIAL: 'var(--color-warn)',
  FAILED: 'var(--color-loss)',
  RUNNING: 'var(--color-ink-faint)',
}

function when(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function countdown(iso: string | null): string {
  if (!iso) return '—'
  const seconds = Math.floor((new Date(iso).getTime() - Date.now()) / 1000)
  if (seconds <= 0) return 'due now'
  const m = Math.floor(seconds / 60)
  return m > 0 ? `in ${m}m ${seconds % 60}s` : `in ${seconds}s`
}

/**
 * Scheduled capture, read entirely from capture_cycles.
 *
 * Every row here is a database record of a cycle that actually ran, including
 * the failures — a scheduler that only showed successes would hide exactly the
 * thing you need to see.
 */
export function SchedulerPanel() {
  const [status, setStatus] = useState<SchedulerStatus | null>(null)
  const [cycles, setCycles] = useState<CaptureCycle[]>([])
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(false)

  async function refresh() {
    try {
      const [s, c] = await Promise.all([api.schedulerStatus(), api.schedulerCycles(20)])
      setStatus(s)
      setCycles(c.cycles)
    } catch { /* backend down; the capture panel already reports that */ }
  }

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 5000)
    return () => clearInterval(timer)
  }, [])

  async function runNow() {
    setBusy(true)
    try { await api.schedulerRunNow(); await refresh() } finally { setBusy(false) }
  }

  if (!status) return null

  const schedState = !status.enabled ? 'DISABLED' : status.running ? 'RUNNING' : 'STOPPED'
  const schedColor = !status.enabled
    ? 'var(--color-ink-faint)'
    : status.running ? 'var(--color-profit)' : 'var(--color-loss)'

  return (
    <div className="rounded-lg border mb-4" style={{ borderColor: 'var(--color-rule)' }}>
      <div className="px-4 py-3 flex items-center gap-3 flex-wrap border-b"
           style={{ borderColor: 'var(--color-rule)' }}>
        <span className="w-2 h-2 rounded-full" style={{ background: schedColor }} />
        <span className="text-[12px] font-semibold uppercase tracking-wide">
          Scheduled capture
        </span>
        <span className="font-mono text-[12px]" style={{ color: schedColor }}>
          {schedState} · every {status.interval_minutes}m
        </span>
        <span className="font-mono text-[11px]" style={{ color: 'var(--color-ink-faint)' }}>
          next {countdown(status.next_run_at)} · market {status.market_open ? 'OPEN' : 'CLOSED'}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={runNow} disabled={busy}
                  className="px-3 py-1 rounded text-[12px] font-medium disabled:opacity-50"
                  style={{ background: 'var(--color-ink)', color: 'var(--color-paper)' }}>
            {busy ? 'Running...' : 'Run now'}
          </button>
          <button onClick={() => setExpanded((v) => !v)} className="text-[11px] underline"
                  style={{ color: 'var(--color-ink-faint)' }}>
            {expanded ? 'Hide cycles' : 'Show cycles'}
          </button>
        </div>
      </div>

      <div className="px-4 py-3 grid grid-cols-2 sm:grid-cols-4 gap-4 border-b"
           style={{ borderColor: 'var(--color-rule)' }}>
        {[
          ['Cycles run', status.cycles_total],
          ['Succeeded', status.cycles_succeeded],
          ['Failed', status.cycles_failed],
          ['Records captured', status.records_captured_total.toLocaleString()],
        ].map(([label, value], i) => (
          <div key={label as string}>
            <div className="text-[10px] uppercase tracking-wide"
                 style={{ color: 'var(--color-ink-faint)' }}>{label}</div>
            <div className="text-[15px] font-mono" style={{
              color: i === 2 && Number(value) > 0 ? 'var(--color-loss)' : 'var(--color-ink)',
            }}>{value}</div>
          </div>
        ))}
      </div>

      {status.last_cycle?.error && (
        <div className="px-4 py-2 text-[11px] font-mono border-b"
             style={{ borderColor: 'var(--color-rule)', color: 'var(--color-loss)' }}>
          Last cycle {status.last_cycle.status}: {status.last_cycle.error}
        </div>
      )}

      {expanded && (
        <div className="px-4 py-3 max-h-72 overflow-y-auto">
          <table className="w-full text-[11px] font-mono">
            <thead>
              <tr style={{ color: 'var(--color-ink-faint)' }}>
                <th className="text-left font-normal">#</th>
                <th className="text-left font-normal">Started</th>
                <th className="text-left font-normal">Status</th>
                <th className="text-right font-normal">Ticks</th>
                <th className="text-right font-normal">Bars</th>
                <th className="text-right font-normal">Total</th>
                <th className="text-right font-normal">ms</th>
              </tr>
            </thead>
            <tbody>
              {cycles.map((c) => (
                <tr key={c.cycle_id} title={c.error || ''}>
                  <td>{c.cycle_number}</td>
                  <td>{when(c.started_at)}</td>
                  <td style={{ color: STATUS_COLOR[c.status] }}>{c.status}</td>
                  <td className="text-right">{c.ticks_inserted}</td>
                  <td className="text-right">{c.bars_inserted}</td>
                  <td className="text-right">{c.total_records}</td>
                  <td className="text-right">{c.duration_ms ?? '—'}</td>
                </tr>
              ))}
              {cycles.length === 0 && (
                <tr><td colSpan={7} style={{ color: 'var(--color-ink-faint)' }}>
                  No cycles recorded yet.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
