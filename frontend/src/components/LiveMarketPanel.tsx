import { useEffect, useRef, useState } from 'react'
import type { LiveMarketSnapshot } from '../lib/api'
import { Card, CardSubtitle, CardTitle, ProvenanceTag, Spinner } from './ui'

interface MarketTicker {
  symbol: string
  price: number
  change: number
  change_percent: number
}

export function LiveMarketPanel() {
  const [tickers, setTickers] = useState<MarketTicker[]>([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/api/ws/market`

    const ws = new WebSocket(url)

    ws.onopen = () => {
      setConnected(true)
      setError(null)
    }

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as LiveMarketSnapshot
        if (payload.type === 'market_snapshot' && payload.symbols) {
          const items = Object.values(payload.symbols).map((s) => ({
            symbol: s.symbol,
            price: s.price,
            change: s.change,
            change_percent: s.change_percent,
          }))
          setTickers(items)
        }
      } catch (e) {
        console.error('Failed to parse market snapshot:', e)
      }
    }

    ws.onerror = () => {
      setConnected(false)
      setError('Connection failed')
    }

    ws.onclose = () => {
      setConnected(false)
    }

    wsRef.current = ws

    return () => {
      ws.close()
    }
  }, [])

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <div>
          <CardTitle>Demo ticker</CardTitle>
          <CardSubtitle>Synthetic price wobble for UI preview — not Zerodha data. Real live data is on the Live Monitor page.</CardSubtitle>
        </div>
        <div className="flex items-center gap-2">
          <ProvenanceTag kind="demo" />
          {connected ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-mono" style={{ color: 'var(--color-profit)' }}>
              <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: 'var(--color-profit)' }} />
              Connected
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-[11px] font-mono" style={{ color: 'var(--color-ink-faint)' }}>
              <Spinner size={12} />
              Connecting…
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 text-[12px] p-3 rounded-lg" style={{ backgroundColor: 'var(--color-loss-bg)', color: 'var(--color-loss)' }}>
          {error}
        </div>
      )}

      {tickers.length === 0 ? (
        <div className="text-center py-8">
          <Spinner size={20} />
          <div className="mt-2 text-[12px]" style={{ color: 'var(--color-ink-muted)' }}>Loading market data…</div>
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {tickers.map((ticker) => {
            const isPositive = ticker.change >= 0
            return (
              <div key={ticker.symbol} className="rounded-lg border p-3" style={{ borderColor: 'var(--color-border)' }}>
                <div className="font-mono text-[12px] font-medium mb-1" style={{ color: 'var(--color-ink)' }}>
                  {ticker.symbol}
                </div>
                <div className="font-display text-[16px] font-bold" style={{ color: 'var(--color-ink)' }}>
                  {ticker.price.toFixed(2)}
                </div>
                <div
                  className="font-mono text-[11px] mt-1"
                  style={{
                    color: isPositive ? 'var(--color-profit)' : 'var(--color-loss)',
                  }}
                >
                  {isPositive ? '+' : ''}{ticker.change.toFixed(2)} ({ticker.change_percent.toFixed(2)}%)
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
