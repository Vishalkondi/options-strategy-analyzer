import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { KiteDiagnostics, MarketSource, ReplayStatus, StrategySpec } from '../lib/api'

const SOURCE_CONFIG: Record<MarketSource, { label: string; bg: string; fg: string; icon: string }> = {
  kite: {
    label: 'LIVE — Zerodha',
    bg: 'var(--color-profit-bg)', fg: 'var(--color-profit)', icon: '●',
  },
  replay: {
    label: 'REPLAY — historical bars',
    bg: 'var(--color-warn-bg)', fg: 'var(--color-warn)', icon: '⏵',
  },
  simulated: {
    label: 'SIMULATED — not real prices',
    bg: 'var(--color-loss-bg)', fg: 'var(--color-loss)', icon: '⚠',
  },
}

interface Props {
  symbols: string[]
  strategies: StrategySpec[]
}

/**
 * Says, unambiguously, where the numbers on screen come from.
 *
 * The backend can serve three things: real Zerodha quotes, a replay of stored
 * bars, or a simulated fallback. Showing all three identically is how a demo
 * turns into a false claim, so the source is always on screen.
 */
export function DataSourceBanner({ symbols, strategies }: Props) {
  const [source, setSource] = useState<MarketSource>('simulated')
  const [detail, setDetail] = useState<string | null>(null)
  const [diagnostics, setDiagnostics] = useState<KiteDiagnostics | null>(null)
  const [replay, setReplay] = useState<ReplayStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showHelp, setShowHelp] = useState(false)

  const [replaySymbol, setReplaySymbol] = useState('')
  const [replayStrategy, setReplayStrategy] = useState('')
  const [speed, setSpeed] = useState(20)

  useEffect(() => {
    if (!replaySymbol && symbols.length) setReplaySymbol(symbols[0])
  }, [symbols, replaySymbol])

  useEffect(() => {
    if (!replayStrategy && strategies.length) setReplayStrategy(strategies[0].file)
  }, [strategies, replayStrategy])

  function refresh() {
    api.liveMarket().then((snapshot) => {
      setSource(snapshot.source ?? 'simulated')
      setDetail(snapshot.source_detail ?? null)
    }).catch(() => {})
    api.replayStatus().then(setReplay).catch(() => {})
  }

  useEffect(() => {
    refresh()
    api.kiteDiagnostics().then(setDiagnostics).catch(() => {})
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [])

  async function startReplay() {
    setBusy(true)
    setError(null)
    try {
      const status = await api.replayStart({
        symbol: replaySymbol, strategy_file: replayStrategy, speed,
      })
      setReplay(status)
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function stopReplay() {
    setBusy(true)
    try {
      setReplay(await api.replayStop())
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const config = SOURCE_CONFIG[source]
  const progress = replay?.running ? Math.round((replay.progress ?? 0) * 100) : 0

  return (
    <div
      className="rounded-lg border mb-4 overflow-hidden"
      style={{ borderColor: config.fg, background: config.bg }}
    >
      <div className="px-4 py-3 flex items-center gap-3 flex-wrap">
        <span className="text-base" style={{ color: config.fg }}>{config.icon}</span>
        <span className="font-semibold text-[13px]" style={{ color: config.fg }}>
          {config.label}
        </span>

        {detail && (
          <span className="font-mono text-[11px] flex-1 min-w-[200px]" style={{ color: config.fg, opacity: 0.85 }}>
            {detail}
          </span>
        )}

        {source !== 'kite' && (
          <button
            onClick={() => setShowHelp((v) => !v)}
            className="text-[11px] underline"
            style={{ color: config.fg }}
          >
            {showHelp ? 'Hide setup' : 'How do I get live data?'}
          </button>
        )}
      </div>

      {showHelp && diagnostics && (
        <div className="px-4 pb-3 text-[12px]" style={{ color: config.fg }}>
          {diagnostics.problems.length > 0 ? (
            <ul className="list-disc pl-5 space-y-1">
              {diagnostics.problems.map((problem) => <li key={problem}>{problem}</li>)}
            </ul>
          ) : (
            <div>{diagnostics.next_step}</div>
          )}
          <div className="mt-2 font-mono text-[11px] opacity-80">
            Verify with: python check_backend.py --live
          </div>
        </div>
      )}

      {/* Replay controls: demonstrate the whole live path with no Kite key. */}
      <div
        className="px-4 py-2.5 flex items-center gap-2 flex-wrap border-t"
        style={{ borderColor: config.fg, opacity: 0.95 }}
      >
        <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: config.fg }}>
          Replay
        </span>

        {replay?.running ? (
          <>
            <span className="font-mono text-[12px]" style={{ color: config.fg }}>
              {replay.symbol} · {replay.bars_sent}/{replay.bars_total} bars · {replay.signals_fired} signals
            </span>
            <div className="h-1.5 w-32 rounded-full overflow-hidden" style={{ background: 'rgba(0,0,0,0.15)' }}>
              <div className="h-full rounded-full" style={{ width: `${progress}%`, background: config.fg }} />
            </div>
            <button
              onClick={stopReplay}
              disabled={busy}
              className="px-3 py-1 rounded text-[12px] font-medium disabled:opacity-50"
              style={{ background: config.fg, color: config.bg }}
            >
              Stop
            </button>
          </>
        ) : (
          <>
            <select
              value={replaySymbol}
              onChange={(e) => setReplaySymbol(e.target.value)}
              className="px-2 py-1 rounded text-[12px] border bg-transparent"
              style={{ borderColor: config.fg, color: config.fg }}
            >
              {symbols.length === 0 && <option value="">no data imported</option>}
              {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>

            <select
              value={replayStrategy}
              onChange={(e) => setReplayStrategy(e.target.value)}
              className="px-2 py-1 rounded text-[12px] border bg-transparent"
              style={{ borderColor: config.fg, color: config.fg }}
            >
              {strategies.map((s) => <option key={s.file} value={s.file}>{s.name}</option>)}
            </select>

            <select
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
              className="px-2 py-1 rounded text-[12px] border bg-transparent"
              style={{ borderColor: config.fg, color: config.fg }}
            >
              <option value={5}>5 bars/sec</option>
              <option value={20}>20 bars/sec</option>
              <option value={60}>60 bars/sec</option>
            </select>

            <button
              onClick={startReplay}
              disabled={busy || !replaySymbol || !replayStrategy}
              className="px-3 py-1 rounded text-[12px] font-medium disabled:opacity-50"
              style={{ background: config.fg, color: config.bg }}
            >
              {busy ? 'Starting...' : 'Start replay'}
            </button>
          </>
        )}

        {(error || replay?.last_error) && (
          <span className="font-mono text-[11px]" style={{ color: 'var(--color-loss)' }}>
            {error || replay?.last_error}
          </span>
        )}
      </div>
    </div>
  )
}
