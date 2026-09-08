import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { StrategySpec, KiteTokenStatus, LiveWatch, LiveSocketEvent, PaperTrade, LiveStatus } from '../lib/api'
import { Card, CardTitle, CardSubtitle, Button, ProvenanceTag, PnlValue, Spinner, EmptyState, Pill } from '../components/ui'
import { DataSourceBanner } from '../components/DataSourceBanner'
import { CapturePanel } from '../components/CapturePanel'
import { SchedulerPanel } from '../components/SchedulerPanel'

interface FeedEvent extends LiveSocketEvent {
  id: string
}

export function LiveMonitorPage() {
  const [tokenStatus, setTokenStatus] = useState<KiteTokenStatus | null>(null)
  const [requestToken, setRequestToken] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)

  const [strategies, setStrategies] = useState<StrategySpec[]>([])
  const [availableSymbols, setAvailableSymbols] = useState<string[]>([])
  // The feed pill must state where the numbers actually come from. Hardcoding
  // 'LIVE DATA' claimed a Zerodha feed even when the source was stored bars.
  const [feedSource, setFeedSource] = useState<'kite' | 'replay' | 'simulated'>('simulated')
  const [selectedStrategy, setSelectedStrategy] = useState('')
  const [symbol, setSymbol] = useState('')
  const [params, setParams] = useState<Record<string, number>>({})
  const [watching, setWatching] = useState(false)
  const [watchError, setWatchError] = useState<string | null>(null)
  const [activeWatches, setActiveWatches] = useState<LiveWatch[]>([])

  const [feed, setFeed] = useState<FeedEvent[]>([])
  const [lastPrice, setLastPrice] = useState<number | null>(null)
  const [openTrades, setOpenTrades] = useState<PaperTrade[]>([])
  const [connected, setConnected] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)
  const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null)
  const [liveRows, setLiveRows] = useState<LiveSocketEvent[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const socketActiveRef = useRef(false)

  function refreshTokenStatus() {
    api.kiteTokenStatus().then(setTokenStatus).catch(() => {})
  }
  function refreshWatchlist() {
    api.liveWatchlist().then(setActiveWatches).catch(() => {})
  }
  function refreshSignals(sym: string) {
    api.liveSignals(sym).then((rows) => setOpenTrades(rows.filter((r) => r.status === 'OPEN'))).catch(() => {})
  }

  useEffect(() => {
    refreshTokenStatus()
    refreshWatchlist()
    api.symbols().then(setAvailableSymbols).catch(() => {})
    api.strategies().then((s) => {
      setStrategies(s)
      if (s.length) {
        setSelectedStrategy(s[0].file)
        setParams(Object.fromEntries(Object.entries(s[0].parameters).map(([k, v]) => [k, v.default])))
      }
    })
    const poll = setInterval(refreshWatchlist, 8000)
    const statusPoll = setInterval(() => api.liveStatus().then(setLiveStatus).catch(() => {}), 5000)
    // Keeps the feed provenance pill honest: it follows the backend's reported
    // source instead of claiming LIVE DATA unconditionally.
    const readSource = () =>
      api.liveMarket().then((snap) => setFeedSource(snap.source ?? 'simulated')).catch(() => {})
    const sourcePoll = setInterval(readSource, 3000)
    readSource()
    api.liveStatus().then(setLiveStatus).catch(() => {})
    return () => { clearInterval(poll); clearInterval(statusPoll); clearInterval(sourcePoll) }
  }, [])

  const strategy = strategies.find((s) => s.file === selectedStrategy)

  function onStrategyChange(file: string) {
    setSelectedStrategy(file)
    const s = strategies.find((x) => x.file === file)
    if (s) setParams(Object.fromEntries(Object.entries(s.parameters).map(([k, v]) => [k, v.default])))
  }

  async function handleConnectZerodha() {
    setAuthBusy(true)
    setAuthError(null)
    try {
      const { login_url } = await api.kiteLoginUrl()
      window.open(login_url, '_blank', 'noopener')
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e))
    } finally {
      setAuthBusy(false)
    }
  }

  async function handleSubmitRequestToken() {
    if (!requestToken.trim()) return
    setAuthBusy(true)
    setAuthError(null)
    try {
      await api.kiteLoginCallback(requestToken.trim())
      setRequestToken('')
      refreshTokenStatus()
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e))
    } finally {
      setAuthBusy(false)
    }
  }

  function openSocket() {
    if (!socketActiveRef.current) return

    // Detach handlers before closing: a superseded socket's onclose must not
    // schedule a reconnect that then closes the socket replacing it. In React's
    // dev StrictMode the component mounts twice, and without this guard the two
    // sockets closed each other in a loop -- one connect/disconnect every two
    // seconds, forever, which is what filled the server log.
    const previous = wsRef.current
    if (previous) {
      previous.onclose = null
      previous.onerror = null
      previous.onmessage = null
      previous.close()
    }

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${window.location.host}/api/live/ws`)
    ws.onopen = () => {
      if (wsRef.current !== ws) return
      setConnected(true)
      setReconnecting(false)
    }
    ws.onclose = () => {
      // Only the socket we currently own may trigger a reconnect.
      if (wsRef.current !== ws || !socketActiveRef.current) return
      setConnected(false)
      setReconnecting(true)
      reconnectRef.current = setTimeout(openSocket, 2000)
    }
    ws.onerror = () => { if (wsRef.current === ws) setConnected(false) }
    ws.onmessage = (event) => {
      if (wsRef.current !== ws) return
      try {
        const payload = JSON.parse(event.data) as LiveSocketEvent
        setFeed((f) => [{ ...payload, id: `${Date.now()}-${f.length}` }, ...f].slice(0, 40))
        if (payload.type === 'market_tick') setLastPrice(payload.price)
        if (payload.type === 'market_tick') setLiveRows((rows) => [payload, ...rows].slice(0, 50))
        if (payload.type === 'signal' && payload.symbol) refreshSignals(payload.symbol)
      } catch (e) {
        console.error('Failed to parse live event:', e)
      }
    }
    wsRef.current = ws
  }

  useEffect(() => {
    socketActiveRef.current = true
    openSocket()
    return () => {
      socketActiveRef.current = false
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [])

  async function handleGoLive() {
    if (!symbol || !selectedStrategy) return
    setWatching(true)
    setWatchError(null)
    try {
      const result = await api.liveWatch({ symbol, strategy_file: selectedStrategy, params })
      refreshWatchlist()
      refreshSignals(result.symbol)
    } catch (e) {
      setWatchError(e instanceof Error ? e.message : String(e))
    } finally {
      setWatching(false)
    }
  }

  async function handleStop(w: LiveWatch) {
    await api.liveUnwatch(w.instrument_token)
    refreshWatchlist()
  }

  useEffect(() => () => wsRef.current?.close(), [])

  const canGoLive = !!symbol && !!selectedStrategy && !watching && !!tokenStatus?.has_valid_token

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] mb-2" style={{ color: 'var(--color-accent)' }}>Live workspace</div>
        <h2 className="font-display font-bold text-3xl mb-1" style={{ color: 'var(--color-ink)' }}>Live Monitor</h2>
        <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>
          Watch a strategy against real Zerodha Kite ticks. Same entry/exit engine as backtests — see the note on
          the P&amp;L card about how live P&amp;L is currently approximated. Without a Kite subscription you can still
          run the full pipeline by replaying stored bars.
        </p>
      </div>

      <DataSourceBanner symbols={availableSymbols} strategies={strategies} />

      <CapturePanel kiteConnected={Boolean(tokenStatus?.ticker_running)} />

      <SchedulerPanel />

      <Card>
        <div className="flex items-center justify-between mb-3">
          <div>
            <CardTitle>Zerodha connection</CardTitle>
            <CardSubtitle>The API secret and access token never leave the backend.</CardSubtitle>
          </div>
          {tokenStatus?.has_valid_token ? (
            <span className="inline-flex items-center gap-1.5 font-mono text-[11px]" style={{ color: 'var(--color-profit)' }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--color-profit)' }} />
              Token valid{tokenStatus.ticker_running ? ' · ticker running' : ''}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 font-mono text-[11px]" style={{ color: 'var(--color-warn)' }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--color-warn)' }} />
              Not authenticated
            </span>
          )}
        </div>
        {!tokenStatus?.has_valid_token && (
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="secondary" onClick={handleConnectZerodha} disabled={authBusy}>
              {authBusy ? <Spinner size={14} /> : null} Open Zerodha login
            </Button>
            <span className="text-[12px]" style={{ color: 'var(--color-ink-faint)' }}>then paste the redirected request_token:</span>
            <input
              value={requestToken}
              onChange={(e) => setRequestToken(e.target.value)}
              placeholder="request_token"
              className="rounded-lg border px-3 py-1.5 text-[13px] font-mono outline-none"
              style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
            />
            <Button onClick={handleSubmitRequestToken} disabled={authBusy || !requestToken.trim()}>Authenticate</Button>
          </div>
        )}
        {authError && <div className="mt-3 text-[13px]" style={{ color: 'var(--color-loss)' }}>{authError}</div>}
      </Card>

      <div className="grid grid-cols-2 gap-6 items-start">
        <div className="space-y-6">
          <Card>
            <CardTitle>Strategy &amp; symbol</CardTitle>
            {strategies.length === 0 ? (
              <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>No strategies registered.</p>
            ) : (
              <div className="space-y-3">
                <select
                  value={selectedStrategy}
                  onChange={(e) => onStrategyChange(e.target.value)}
                  className="w-full rounded-lg border px-3.5 py-2 text-[13.5px] outline-none"
                  style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
                >
                  {strategies.map((s) => <option key={s.file} value={s.file}>{s.name} (v{s.version})</option>)}
                </select>
                <input
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  placeholder="NSE trading symbol, e.g. RELIANCE"
                  className="w-full rounded-lg border px-3.5 py-2 text-[13.5px] font-mono outline-none"
                  style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
                />
              </div>
            )}
          </Card>

          {strategy && (
            <Card>
              <CardTitle>Parameters</CardTitle>
              <CardSubtitle>Same schema the backtest runner uses — this is the same engine, not a copy.</CardSubtitle>
              <div className="grid grid-cols-2 gap-4">
                {Object.entries(strategy.parameters).map(([key, spec]) => (
                  <div key={key}>
                    <label className="text-[11px] uppercase tracking-wider mb-1 block font-mono" style={{ color: 'var(--color-ink-faint)' }}>{key}</label>
                    <input
                      type="number" step="any" min={spec.min} max={spec.max}
                      value={params[key] ?? spec.default}
                      onChange={(e) => setParams((p) => ({ ...p, [key]: Number(e.target.value) }))}
                      className="w-full rounded-lg border px-3 py-1.5 text-[13px] font-mono outline-none"
                      style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
                    />
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Button onClick={handleGoLive} disabled={!canGoLive} className="w-full py-3">
            {watching ? <Spinner size={14} /> : (
              <span className="w-2 h-2 rounded-full" style={{ background: 'var(--color-accent-ink)' }} />
            )}
            Go live
          </Button>
          {!tokenStatus?.has_valid_token && (
            <div className="text-[12px]" style={{ color: 'var(--color-ink-faint)' }}>Connect to Zerodha above first.</div>
          )}
          {watchError && <div className="text-[13px]" style={{ color: 'var(--color-loss)' }}>{watchError}</div>}

          <Card>
            <CardTitle>Active watches</CardTitle>
            {activeWatches.length === 0 ? (
              <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>Nothing being watched right now.</p>
            ) : (
              <div className="space-y-2 mt-2">
                {activeWatches.map((w) => (
                  <div key={w.instrument_token} className="flex items-center justify-between rounded-lg border p-2.5" style={{ borderColor: 'var(--color-border)' }}>
                    <div>
                      <div className="font-mono text-[13px] font-medium" style={{ color: 'var(--color-ink)' }}>{w.symbol}</div>
                      <div className="text-[11px]" style={{ color: 'var(--color-ink-faint)' }}>{w.strategy_id} v{w.strategy_version}{w.open_trade_id ? ' · position open' : ''}</div>
                    </div>
                    <Button variant="ghost" onClick={() => handleStop(w)}>Stop</Button>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <div className="flex items-center justify-between mb-3">
              <CardTitle>{symbol || 'Live feed'}</CardTitle>
              <div className="flex items-center gap-2">
                <ProvenanceTag kind={feedSource === 'kite' ? 'live' : feedSource} />
                {connected ? (
                  <span className="inline-flex items-center gap-1 text-[11px] font-mono" style={{ color: 'var(--color-profit)' }}>
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--color-profit)' }} />Connected
                  </span>
                ) : (
                  <span className="text-[11px] font-mono" style={{ color: reconnecting ? 'var(--color-warn)' : 'var(--color-ink-faint)' }}>
                    {reconnecting ? 'Reconnecting...' : 'Disconnected'}
                  </span>
                )}
              </div>
            </div>
            {lastPrice !== null && (
              <div className="font-display text-3xl font-bold mb-2" style={{ color: 'var(--color-ink)' }}>{lastPrice.toFixed(2)}</div>
            )}

            {liveStatus && (
              <div className="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-[11px] font-mono" style={{ color: 'var(--color-ink-faint)' }}>
                <span>{liveStatus.total_records.toLocaleString()} records</span>
                <span>{liveStatus.csv_watcher.running ? 'CSV watcher active' : 'CSV watcher stopped'}</span>
                {liveStatus.last_received_timestamp && <span>latest {new Date(liveStatus.last_received_timestamp).toLocaleTimeString()}</span>}
              </div>
            )}

            {liveRows.length > 0 && (
              <div className="mb-4 overflow-x-auto rounded-lg border" style={{ borderColor: 'var(--color-border)' }}>
                <table className="w-full text-[11px] font-mono">
                  <thead style={{ color: 'var(--color-ink-faint)', background: 'var(--color-paper)' }}>
                    <tr>{['Symbol', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume'].map((heading) => <th key={heading} className="px-2 py-2 text-left font-medium">{heading}</th>)}</tr>
                  </thead>
                  <tbody>
                    {liveRows.slice(0, 8).map((row, index) => (
                      <tr key={`${row.timestamp}-${index}`} className="border-t" style={{ borderColor: 'var(--color-border)' }}>
                        <td className="px-2 py-2" style={{ color: 'var(--color-ink)' }}>{row.symbol}</td>
                        <td className="px-2 py-2" style={{ color: 'var(--color-ink-faint)' }}>{new Date(row.timestamp).toLocaleTimeString()}</td>
                        <td className="px-2 py-2" style={{ color: 'var(--color-ink-muted)' }}>{row.open?.toFixed(2) ?? '—'}</td>
                        <td className="px-2 py-2" style={{ color: 'var(--color-ink-muted)' }}>{row.high?.toFixed(2) ?? '—'}</td>
                        <td className="px-2 py-2" style={{ color: 'var(--color-ink-muted)' }}>{row.low?.toFixed(2) ?? '—'}</td>
                        <td className="px-2 py-2" style={{ color: 'var(--color-ink)' }}>{row.close?.toFixed(2) ?? row.price.toFixed(2)}</td>
                        <td className="px-2 py-2" style={{ color: 'var(--color-ink-muted)' }}>{row.volume?.toLocaleString() ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {openTrades.length > 0 && (
              <div className="mb-4 space-y-2">
                {openTrades.map((t) => (
                  <div key={t.paper_trade_id} className="rounded-lg border p-3 flex items-center justify-between" style={{ borderColor: 'var(--color-border)' }}>
                    <div>
                      <Pill tone="accent">{t.side.toUpperCase()}</Pill>
                      <span className="ml-2 font-mono text-[12px]" style={{ color: 'var(--color-ink-muted)' }}>entry @ {t.entry_price.toFixed(2)}</span>
                    </div>
                    {lastPrice !== null && (
                      <PnlValue value={t.side === 'bull' ? lastPrice - t.entry_price : t.entry_price - lastPrice} size="sm" />
                    )}
                  </div>
                ))}
              </div>
            )}

            {feed.length === 0 ? (
              <EmptyState
                icon={<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 18V6m0 12h16M7 15l3-3 2 2 5-6" /></svg>}
                title="No live events yet"
                description="Go live on a symbol above to start streaming ticks and signals here."
              />
            ) : (
              <div className="space-y-1.5 max-h-105 overflow-auto">
                {feed.map((e) => (
                  <div key={e.id} className="flex items-center justify-between rounded-lg px-3 py-2 text-[12px] font-mono" style={{ background: 'var(--color-paper)' }}>
                    {e.type === 'signal' ? (
                      <span style={{ color: e.action === 'ENTRY' ? 'var(--color-profit)' : 'var(--color-loss)' }}>
                        {e.action} · {String(e.reason?.direction ?? e.reason?.exit_reason ?? '')}
                      </span>
                    ) : (
                      <span style={{ color: 'var(--color-ink-faint)' }}>tick</span>
                    )}
                    <span style={{ color: 'var(--color-ink-muted)' }}>{e.price.toFixed(2)}</span>
                    <span style={{ color: 'var(--color-ink-faint)' }}>{new Date(e.timestamp).toLocaleTimeString()}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <div className="text-[11px] leading-relaxed rounded-xl border p-4" style={{ borderColor: 'var(--color-border)', color: 'var(--color-ink-faint)' }}>
            Live P&amp;L above is tracked on the underlying's price move as a proxy for the debit-spread premium —
            pricing the real option legs live would require a separate live options-chain tick stream. The
            backtest engine still prices real stored option legs; this simplification only applies to the live
            path. See <span className="font-mono">server/signals.py</span>.
          </div>
        </div>
      </div>
    </div>
  )
}
