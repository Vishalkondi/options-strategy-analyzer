import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { CaptureStatus, LivePosition, PnlSnapshot, SystemEvent } from '../lib/api'

type Health = 'CONNECTED' | 'DISCONNECTED' | 'WAITING' | 'ERROR'

const HEALTH_COLOR: Record<Health, string> = {
  CONNECTED: 'var(--color-profit)',
  WAITING: 'var(--color-warn)',
  DISCONNECTED: 'var(--color-ink-faint)',
  ERROR: 'var(--color-loss)',
}

function Light({ label, state, detail }: { label: string; state: Health; detail?: string }) {
  return (
    <div className="flex items-center gap-2 min-w-[150px]">
      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: HEALTH_COLOR[state] }} />
      <div className="leading-tight">
        <div className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--color-ink-faint)' }}>
          {label}
        </div>
        <div className="text-[12px] font-mono" style={{ color: HEALTH_COLOR[state] }}>
          {state}{detail ? ` · ${detail}` : ''}
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--color-ink-faint)' }}>
        {label}
      </div>
      <div className="text-[15px] font-mono" style={{ color: tone || 'var(--color-ink)' }}>{value}</div>
    </div>
  )
}

function ago(iso: string | null): string {
  if (!iso) return 'never'
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 0) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  return `${Math.floor(seconds / 3600)}h ago`
}

/**
 * Database-backed capture panel.
 *
 * Every number here is read from the backend, which reads it from DuckDB.
 * Nothing is generated in the browser, so a value on screen means a row on
 * disk. If capture stops, these stop changing — which is the point.
 */
export function CapturePanel({ kiteConnected }: { kiteConnected: boolean }) {
  const [status, setStatus] = useState<CaptureStatus | null>(null)
  const [positions, setPositions] = useState<LivePosition[]>([])
  const [pnl, setPnl] = useState<PnlSnapshot | null>(null)
  const [events, setEvents] = useState<SystemEvent[]>([])
  const [reachable, setReachable] = useState(true)
  const [showEvents, setShowEvents] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const [s, p, l] = await Promise.all([
          api.captureStatus(), api.livePositions(), api.livePnl(),
        ])
        if (cancelled) return
        setStatus(s)
        setPositions(p.positions)
        setPnl(l.current)
        setReachable(true)
      } catch {
        if (!cancelled) setReachable(false)
      }
    }
    poll()
    const timer = setInterval(poll, 3000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [])

  useEffect(() => {
    if (!showEvents) return
    api.systemEvents(20).then((r) => setEvents(r.events)).catch(() => {})
  }, [showEvents])

  const dbState: Health = !reachable ? 'ERROR' : 'CONNECTED'
  const kiteState: Health = kiteConnected ? 'CONNECTED' : 'DISCONNECTED'

  let captureState: Health = 'DISCONNECTED'
  if (status?.capturing) {
    const writerFailed = Object.values(status.writers).some((w) => w.failed > 0)
    captureState = writerFailed ? 'ERROR' : (status.last_tick_at ? 'CONNECTED' : 'WAITING')
  }

  const session = status?.active_sessions?.[0]
  const openPositions = positions.filter((p) => p.status === 'OPEN')
  const pnlTone = (pnl?.total_pnl ?? 0) >= 0 ? 'var(--color-profit)' : 'var(--color-loss)'

  return (
    <div className="rounded-lg border mb-4" style={{ borderColor: 'var(--color-rule)' }}>
      <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-rule)' }}>
        <div className="flex items-center justify-between mb-3">
          <span className="text-[12px] font-semibold uppercase tracking-wide">
            Live capture — database
          </span>
          <button
            onClick={() => setShowEvents((v) => !v)}
            className="text-[11px] underline"
            style={{ color: 'var(--color-ink-faint)' }}
          >
            {showEvents ? 'Hide log' : 'Event log'}
          </button>
        </div>

        <div className="flex flex-wrap gap-4">
          <Light label="Kite" state={kiteState} />
          <Light label="Database" state={dbState} />
          <Light
            label="Capture"
            state={captureState}
            detail={session ? `${session.symbol}` : undefined}
          />
        </div>
      </div>

      <div className="px-4 py-3 grid grid-cols-2 sm:grid-cols-4 gap-4 border-b"
           style={{ borderColor: 'var(--color-rule)' }}>
        <Stat label="Ticks stored" value={status?.totals.ticks.toLocaleString() ?? '—'} />
        <Stat label="Bars stored" value={status?.totals.bars.toLocaleString() ?? '—'} />
        <Stat label="Last tick" value={ago(status?.last_tick_at ?? null)} />
        <Stat label="Last DB write" value={ago(status?.last_db_write_at ?? null)} />
      </div>

      <div className="px-4 py-3 grid grid-cols-2 sm:grid-cols-4 gap-4 border-b"
           style={{ borderColor: 'var(--color-rule)' }}>
        <Stat label="Open positions" value={openPositions.length} />
        <Stat label="Realized P&L" value={pnl ? pnl.realized_pnl.toFixed(2) : '—'} />
        <Stat label="Unrealized P&L" value={pnl ? pnl.unrealized_pnl.toFixed(2) : '—'} />
        <Stat label="Total P&L" value={pnl ? pnl.total_pnl.toFixed(2) : '—'} tone={pnlTone} />
      </div>

      {status && Object.values(status.writers).some((w) => w.pending > 0 || w.failed > 0) && (
        <div className="px-4 py-2 text-[11px] font-mono border-b"
             style={{ borderColor: 'var(--color-rule)', color: 'var(--color-ink-faint)' }}>
          {Object.entries(status.writers).map(([name, w]) => (
            <span key={name} className="mr-4">
              {name}: {w.pending} buffered · {w.written} written
              {w.dropped > 0 && <span style={{ color: 'var(--color-warn)' }}> · {w.dropped} dropped</span>}
              {w.failed > 0 && <span style={{ color: 'var(--color-loss)' }}> · {w.failed} failed</span>}
            </span>
          ))}
        </div>
      )}

      {openPositions.length > 0 && (
        <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-rule)' }}>
          <table className="w-full text-[12px] font-mono">
            <thead>
              <tr style={{ color: 'var(--color-ink-faint)' }}>
                <th className="text-left font-normal">Symbol</th>
                <th className="text-left font-normal">Side</th>
                <th className="text-right font-normal">Entry</th>
                <th className="text-right font-normal">LTP</th>
                <th className="text-right font-normal">Unrealized</th>
              </tr>
            </thead>
            <tbody>
              {openPositions.slice(0, 5).map((p) => (
                <tr key={p.paper_trade_id}>
                  <td>{p.symbol}</td>
                  <td>{p.side}</td>
                  <td className="text-right">{p.entry_price?.toFixed(2) ?? '—'}</td>
                  <td className="text-right">{p.ltp?.toFixed(2) ?? '—'}</td>
                  <td className="text-right" style={{
                    color: (p.unrealized_pnl ?? 0) >= 0 ? 'var(--color-profit)' : 'var(--color-loss)',
                  }}>
                    {p.unrealized_pnl?.toFixed(2) ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showEvents && (
        <div className="px-4 py-3 max-h-48 overflow-y-auto text-[11px] font-mono">
          {events.length === 0 && (
            <div style={{ color: 'var(--color-ink-faint)' }}>No events recorded yet.</div>
          )}
          {events.map((e, i) => (
            <div key={i} className="flex gap-2 py-0.5">
              <span style={{ color: 'var(--color-ink-faint)' }}>{e.event_ts.slice(11, 19)}</span>
              <span style={{
                color: e.severity === 'ERROR' ? 'var(--color-loss)'
                  : e.severity === 'WARNING' ? 'var(--color-warn)' : 'var(--color-ink-faint)',
              }}>
                {e.category}/{e.event}
              </span>
              {e.detail && <span className="truncate" style={{ color: 'var(--color-ink-faint)' }}>{e.detail}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
