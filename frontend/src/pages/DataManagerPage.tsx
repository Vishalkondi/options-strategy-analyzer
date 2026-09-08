import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { ImportRecord, Stats, QualityReport, LiveSyncResult, XSentimentResult } from '../lib/api'
import { Card, CardTitle, CardSubtitle, Button, StatBlock, ProvenanceTag, EmptyState, Spinner } from '../components/ui'

export function DataManagerPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [imports, setImports] = useState<ImportRecord[]>([])
  const [path, setPath] = useState('demo')
  const [importing, setImporting] = useState(false)
  const [lastReports, setLastReports] = useState<QualityReport[] | null>(null)
  const [selected, setSelected] = useState<ImportRecord | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [liveSymbol, setLiveSymbol] = useState('')
  const [liveStart, setLiveStart] = useState('')
  const [liveEnd, setLiveEnd] = useState('')
  const [liveExpiry, setLiveExpiry] = useState('')
  const [liveStrikes, setLiveStrikes] = useState('')
  const [syncing, setSyncing] = useState(false)
  const [liveResult, setLiveResult] = useState<LiveSyncResult | null>(null)
  const [sentimentSymbol, setSentimentSymbol] = useState('')
  const [sentimentMax, setSentimentMax] = useState(8)
  const [sentimentLoading, setSentimentLoading] = useState(false)
  const [sentimentResult, setSentimentResult] = useState<XSentimentResult | null>(null)
  const [sentimentError, setSentimentError] = useState<string | null>(null)

  async function refresh() {
    const [s, i] = await Promise.all([api.stats(), api.imports()])
    setStats(s)
    setImports(i)
  }

  useEffect(() => { refresh() }, [])

  useEffect(() => {
    if (!liveSymbol && stats && imports.length >= 0) {
      api.symbols().then((items) => { if (items.length) setLiveSymbol(items[0]) })
    }
    if (!sentimentSymbol && stats && imports.length >= 0) {
      api.symbols().then((items) => { if (items.length) setSentimentSymbol(items[0]) })
    }
  }, [stats, imports, liveSymbol, sentimentSymbol])

  async function handleImport() {
    setImporting(true)
    setError(null)
    try {
      const res = await api.importPath(path)
      setLastReports(res.reports)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setImporting(false)
    }
  }

  async function handleLiveSync() {
    if (!liveSymbol) return
    setSyncing(true)
    setError(null)
    setLiveResult(null)
    try {
      const strikes = liveStrikes.split(',').map((value) => Number(value.trim())).filter((value) => Number.isFinite(value))
      const result = await api.liveSync({
        symbol: liveSymbol,
        date_start: liveStart || undefined,
        date_end: liveEnd || undefined,
        expiry: liveExpiry || undefined,
        strikes: strikes.length ? strikes : undefined,
      })
      setLiveResult(result)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSyncing(false)
    }
  }

  async function handleXSentiment() {
    if (!sentimentSymbol) return
    setSentimentLoading(true)
    setSentimentError(null)
    setSentimentResult(null)
    try {
      const result = await api.xSentiment({
        symbol: sentimentSymbol,
        max_results: sentimentMax,
      })
      setSentimentResult(result)
    } catch (e) {
      setSentimentError(e instanceof Error ? e.message : String(e))
    } finally {
      setSentimentLoading(false)
    }
  }

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h2 className="font-display font-bold text-2xl mb-1" style={{ color: 'var(--color-ink)' }}>Data Manager</h2>
        <p className="text-[13px]" style={{ color: 'var(--color-ink-muted)' }}>
          Import NSE equity and options-chain CSVs, review quality reports, and inspect coverage.
          Imports are idempotent — re-importing an identical file is a no-op.
        </p>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <Card><StatBlock label="Equity rows" value={stats?.equity_rows ?? '—'} /></Card>
        <Card><StatBlock label="Options rows" value={stats?.options_rows ?? '—'} /></Card>
        <Card><StatBlock label="Stocks" value={stats?.stocks ?? '—'} /></Card>
        <Card><StatBlock label="Imports" value={stats?.imports ?? '—'} /></Card>
      </div>

      <Card className="border-l-4" style={{ borderLeftColor: 'var(--color-profit)' }}>
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <CardTitle>Live market sync</CardTitle>
            <CardSubtitle>Pull historical Zerodha candles into the same dataset used by the backtester.</CardSubtitle>
          </div>
          <ProvenanceTag kind="live" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="md:col-span-2">
            <label className="text-[11px] uppercase tracking-wider mb-1 block" style={{ color: 'var(--color-ink-faint)' }}>Symbol</label>
            <input value={liveSymbol} onChange={(e) => setLiveSymbol(e.target.value.toUpperCase())} placeholder="RELIANCE"
              className="w-full rounded-lg border px-3 py-2 text-[13px] font-mono outline-none"
              style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }} />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-wider mb-1 block" style={{ color: 'var(--color-ink-faint)' }}>From</label>
            <input type="date" value={liveStart} onChange={(e) => setLiveStart(e.target.value)}
              className="w-full rounded-lg border px-3 py-2 text-[13px] font-mono outline-none"
              style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }} />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-wider mb-1 block" style={{ color: 'var(--color-ink-faint)' }}>To</label>
            <input type="date" value={liveEnd} onChange={(e) => setLiveEnd(e.target.value)}
              className="w-full rounded-lg border px-3 py-2 text-[13px] font-mono outline-none"
              style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }} />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-wider mb-1 block" style={{ color: 'var(--color-ink-faint)' }}>Expiry</label>
            <input type="date" value={liveExpiry} onChange={(e) => setLiveExpiry(e.target.value)}
              className="w-full rounded-lg border px-3 py-2 text-[13px] font-mono outline-none"
              style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }} />
          </div>
          <div className="md:col-span-2">
            <label className="text-[11px] uppercase tracking-wider mb-1 block" style={{ color: 'var(--color-ink-faint)' }}>Strikes</label>
            <input value={liveStrikes} onChange={(e) => setLiveStrikes(e.target.value)} placeholder="1400, 1450, 1500"
              className="w-full rounded-lg border px-3 py-2 text-[13px] font-mono outline-none"
              style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }} />
          </div>
          <div className="flex items-end">
            <Button onClick={handleLiveSync} disabled={!liveSymbol || syncing} className="w-full">
              {syncing ? <Spinner size={14} /> : <span className="text-base leading-none">↻</span>}
              {syncing ? 'Syncing…' : 'Sync from Zerodha'}
            </Button>
          </div>
        </div>
        {liveResult && (
          <div className="mt-4 grid grid-cols-3 gap-3 rounded-lg p-3 font-mono text-[12px]" style={{ background: 'var(--color-profit-bg)', color: 'var(--color-profit)' }}>
            <span>{liveResult.equity_rows} equity candles</span>
            <span>{liveResult.option_rows} option candles</span>
            <span className="text-right">synced {new Date(liveResult.synced_at).toLocaleString()}</span>
          </div>
        )}
      </Card>

      <Card>
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <CardTitle>X market sentiment</CardTitle>
            <CardSubtitle>Use the public X API to pull a quick sentiment pulse for a symbol and compare it with your trade setup.</CardSubtitle>
          </div>
          <ProvenanceTag kind="live" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-[1.4fr_0.7fr_auto] gap-3">
          <div>
            <label className="text-[11px] uppercase tracking-wider mb-1 block" style={{ color: 'var(--color-ink-faint)' }}>Symbol</label>
            <input value={sentimentSymbol} onChange={(e) => setSentimentSymbol(e.target.value.toUpperCase())} placeholder="RELIANCE"
              className="w-full rounded-lg border px-3 py-2 text-[13px] font-mono outline-none"
              style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }} />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-wider mb-1 block" style={{ color: 'var(--color-ink-faint)' }}>Posts</label>
            <input type="number" min={1} max={100} value={sentimentMax} onChange={(e) => setSentimentMax(Number(e.target.value) || 1)}
              className="w-full rounded-lg border px-3 py-2 text-[13px] font-mono outline-none"
              style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }} />
          </div>
          <div className="flex items-end">
            <Button onClick={handleXSentiment} disabled={!sentimentSymbol || sentimentLoading} className="w-full md:w-auto">
              {sentimentLoading ? <Spinner size={14} /> : <span className="text-base leading-none">◌</span>}
              {sentimentLoading ? 'Fetching…' : 'Fetch sentiment'}
            </Button>
          </div>
        </div>

        {sentimentError && (
          <div className="mt-3 rounded-lg border px-3 py-2 text-[12px] font-mono" style={{ color: 'var(--color-warn)', background: 'var(--color-warn-bg)', borderColor: 'color-mix(in srgb, var(--color-warn) 35%, transparent)' }}>
            {sentimentError}
          </div>
        )}

        {sentimentResult && (
          <div className="mt-4 rounded-lg border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}>
            <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
              <div className="font-mono text-[13px]" style={{ color: 'var(--color-ink)' }}>{sentimentResult.symbol}</div>
              <span className="font-mono text-[12px]" style={{ color: 'var(--color-ink-faint)' }}>{sentimentResult.posts_found} posts</span>
            </div>
            <div className="grid grid-cols-3 gap-3 text-[12px] font-mono" style={{ color: 'var(--color-ink-muted)' }}>
              <div>
                <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--color-ink-faint)' }}>Score</div>
                <div>{sentimentResult.sentiment_score}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--color-ink-faint)' }}>Normalized</div>
                <div>{sentimentResult.normalized_sentiment}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--color-ink-faint)' }}>Positive / negative</div>
                <div>{sentimentResult.positive_mentions} / {sentimentResult.negative_mentions}</div>
              </div>
            </div>
            <div className="mt-3 space-y-1.5">
              {sentimentResult.posts.slice(0, 3).map((post) => (
                <div key={post.id ?? post.text} className="rounded-md border px-2.5 py-2 text-[12px]" style={{ borderColor: 'var(--color-border)' }}>
                  <div className="font-mono" style={{ color: 'var(--color-ink-faint)' }}>{post.created_at ?? 'recent'}</div>
                  <div style={{ color: 'var(--color-ink)' }}>{post.text}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      <Card>
        <CardTitle>Import dataset</CardTitle>
        <CardSubtitle>
          Path relative to the raw data directory. A directory imports every CSV inside it.
          Files should be named <span className="font-mono">&lt;SYMBOL&gt;_equity.csv</span> or <span className="font-mono">&lt;SYMBOL&gt;_options.csv</span>.
        </CardSubtitle>
        <div className="flex gap-3">
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            className="flex-1 rounded-lg border px-3.5 py-2 text-[13.5px] font-mono outline-none"
            style={{ borderColor: 'var(--color-border-strong)', background: 'var(--color-paper)', color: 'var(--color-ink)' }}
            placeholder="demo"
          />
          <Button onClick={handleImport} disabled={importing}>
            {importing ? <Spinner size={14} /> : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3v12m0 0 4-4m-4 4-4-4M4 19h16" /></svg>
            )}
            Import
          </Button>
        </div>
        {error && <div className="mt-3 text-[13px]" style={{ color: 'var(--color-loss)' }}>{error}</div>}

        {lastReports && (
          <div className="mt-4 space-y-2">
            {lastReports.map((r, i) => (
              <div key={i} className="rounded-lg border p-3 text-[13px]" style={{ borderColor: 'var(--color-border)' }}>
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono font-medium" style={{ color: 'var(--color-ink)' }}>{r.file_path.split('/').pop()}</span>
                  <ProvenanceTag kind={r.skipped_duplicate_file ? 'blocked' : 'demo'} />
                </div>
                <div className="font-mono text-[12px]" style={{ color: 'var(--color-ink-muted)' }}>
                  {r.skipped_duplicate_file
                    ? 'Already imported (identical SHA-256) — no-op'
                    : `read ${r.rows_read} · accepted ${r.rows_accepted} · rejected ${r.rows_rejected} · range [${r.date_start ?? '—'} .. ${r.date_end ?? '—'}]`}
                </div>
                {r.errors.length > 0 && (
                  <div className="mt-1 text-[12px]" style={{ color: 'var(--color-loss)' }}>
                    {r.errors.slice(0, 3).join(' · ')}{r.errors.length > 3 ? ` (+${r.errors.length - 3} more)` : ''}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <div className="flex items-center justify-between mb-1">
          <CardTitle>Imported files</CardTitle>
        </div>
        <CardSubtitle>Select a row to view its full data-quality report.</CardSubtitle>

        {imports.length === 0 ? (
          <EmptyState
            icon={<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5" /></svg>}
            title="No files imported yet"
            description="Import a dataset above to get started."
          />
        ) : (
          <div className="overflow-x-auto thin-scroll -mx-1">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left" style={{ color: 'var(--color-ink-faint)' }}>
                  {['File', 'Symbol', 'Kind', 'Rows', 'Range', 'Imported'].map((h) => (
                    <th key={h} className="font-medium px-3 py-2 text-[11px] uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {imports.map((imp) => (
                  <tr
                    key={imp.import_id}
                    onClick={() => setSelected(imp)}
                    className="cursor-pointer border-t"
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    <td className="px-3 py-2.5 font-mono" style={{ color: 'var(--color-ink)' }}>{imp.file_path.split('/').pop()}</td>
                    <td className="px-3 py-2.5 font-mono" style={{ color: 'var(--color-ink-muted)' }}>{imp.symbol}</td>
                    <td className="px-3 py-2.5" style={{ color: 'var(--color-ink-muted)' }}>{imp.kind}</td>
                    <td className="px-3 py-2.5 font-mono" style={{ color: 'var(--color-ink-muted)' }}>{imp.rows_accepted}/{imp.rows_read}</td>
                    <td className="px-3 py-2.5 font-mono text-[12px]" style={{ color: 'var(--color-ink-muted)' }}>{imp.date_start} → {imp.date_end}</td>
                    <td className="px-3 py-2.5 font-mono text-[12px]" style={{ color: 'var(--color-ink-faint)' }}>{new Date(imp.imported_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {selected && (
        <Card>
          <div className="flex items-center justify-between mb-3">
            <CardTitle>Quality report — {selected.file_path.split('/').pop()}</CardTitle>
            <button onClick={() => setSelected(null)} className="text-[12px]" style={{ color: 'var(--color-ink-muted)' }}>close</button>
          </div>
          <div className="grid grid-cols-4 gap-4 font-mono text-[13px]">
            <div><div style={{ color: 'var(--color-ink-faint)' }} className="text-[11px] uppercase mb-1">Rows read</div>{selected.rows_read}</div>
            <div><div style={{ color: 'var(--color-ink-faint)' }} className="text-[11px] uppercase mb-1">Accepted</div>{selected.rows_accepted}</div>
            <div><div style={{ color: 'var(--color-ink-faint)' }} className="text-[11px] uppercase mb-1">Rejected</div>{selected.rows_rejected}</div>
            <div><div style={{ color: 'var(--color-ink-faint)' }} className="text-[11px] uppercase mb-1">Duplicates</div>{selected.duplicates}</div>
            <div><div style={{ color: 'var(--color-ink-faint)' }} className="text-[11px] uppercase mb-1">Trading days</div>{selected.trading_day_count}</div>
            <div><div style={{ color: 'var(--color-ink-faint)' }} className="text-[11px] uppercase mb-1">Date start</div>{selected.date_start}</div>
            <div><div style={{ color: 'var(--color-ink-faint)' }} className="text-[11px] uppercase mb-1">Date end</div>{selected.date_end}</div>
            <div className="truncate"><div style={{ color: 'var(--color-ink-faint)' }} className="text-[11px] uppercase mb-1">SHA-256</div><span title={selected.file_hash}>{selected.file_hash.slice(0, 16)}…</span></div>
          </div>
        </Card>
      )}
    </div>
  )
}
