export interface QualityReport {
  file_path: string
  symbol: string
  kind: string
  rows_read: number
  rows_accepted: number
  rows_rejected: number
  duplicates: number
  glued_rows_fixed: number
  missing_values: number
  invalid_values: number
  date_start: string | null
  date_end: string | null
  trading_day_count: number
  warnings: string[]
  errors: string[]
  skipped_duplicate_file: boolean
  import_id: number | null
}

export interface ImportRecord {
  import_id: number
  file_path: string
  file_hash: string
  symbol: string
  kind: string
  rows_read: number
  rows_accepted: number
  rows_rejected: number
  duplicates: number
  date_start: string | null
  date_end: string | null
  trading_day_count: number
  warnings: string
  errors: string
  imported_at: string
}

export interface Stats {
  equity_rows: number
  options_rows: number
  stocks: number
  imports: number
}

export interface LiveSyncResult {
  symbol: string
  equity_rows: number
  option_rows: number
  synced_at: string
}

export interface XSentimentResult {
  symbol: string
  query: string
  posts_found: number
  positive_mentions: number
  negative_mentions: number
  sentiment_score: number
  normalized_sentiment: number
  source: string
  posts: Array<{
    id?: string
    created_at?: string
    text: string
    engagement: Record<string, number | string>
    language?: string
  }>
}

export interface DataCoverage {
  symbol: string
  equity_rows: number
  equity_start: string | null
  equity_end: string | null
  option_rows: number
  option_start: string | null
  option_end: string | null
}

export type MarketSource = 'kite' | 'replay' | 'simulated'

export interface LiveMarketSnapshot {
  type: 'market_snapshot'
  timestamp: string
  source: MarketSource
  source_detail: string | null
  symbols: Record<string, {
    symbol: string
    price: number
    previous_close: number
    change: number
    change_percent: number
    timestamp: string
    source: MarketSource
    open?: number
    high?: number
    low?: number
    volume?: number
  }>
}

export interface ReplayStatus {
  running: boolean
  run_id: string | null
  symbol: string | null
  strategy_file: string | null
  speed: number
  bars_total: number
  bars_sent: number
  signals_fired: number
  progress: number
  started_at: string | null
  last_error: string | null
}

export interface CaptureStatus {
  enabled: boolean
  capturing: boolean
  active_sessions: Array<{
    session_id: string; symbol: string; source: string; status: string
    started_at: string | null; ticks_stored: number; bars_stored: number
    first_tick: string | null; last_tick: string | null
  }>
  last_tick_at: string | null
  last_tick_symbol: string | null
  last_db_write_at: string | null
  totals: { ticks: number; symbols: number; latest_tick_ts: string | null; bars: number; latest_bar_ts: string | null }
  writers: Record<string, {
    running: boolean; pending: number; written: number
    dropped: number; failed: number; last_error: string | null
  }>
}

export interface CaptureCycle {
  cycle_id: string; cycle_number: number
  scheduled_at: string | null; started_at: string | null; finished_at: string | null
  duration_ms: number | null; status: 'SUCCESS' | 'PARTIAL' | 'FAILED' | 'RUNNING'
  trigger: string; attempts: number
  symbols_requested: number; symbols_captured: number
  ticks_inserted: number; bars_inserted: number; option_rows_inserted: number
  signals_inserted: number; pnl_snapshots_inserted: number
  total_records: number; market_open: boolean | null; error: string | null
}

export interface SchedulerStatus {
  running: boolean; enabled: boolean; interval_minutes: number
  next_run_at: string | null; market_open: boolean
  cycles_total: number; cycles_succeeded: number; cycles_failed: number
  records_captured_total: number
  last_cycle: (Partial<CaptureCycle> & { status: string; error: string | null }) | null
}

export interface LivePosition {
  paper_trade_id: string; symbol: string; strategy_id: string; side: string
  entry_ts: string | null; entry_price: number | null
  exit_ts: string | null; exit_price: number | null; exit_reason: string | null
  realized_pnl: number | null; status: string
  ltp: number | null; unrealized_pnl: number | null
}

export interface PnlSnapshot {
  realized_pnl: number; unrealized_pnl: number; total_pnl: number
  open_positions: number; closed_positions: number
  capital: number | null; return_pct: number | null
}

export interface SystemEvent {
  event_ts: string; category: string; severity: string; event: string; detail: string | null
}

export interface KiteDiagnostics {
  ready: boolean
  problems: string[]
  credentials: {
    kiteconnect_installed: boolean
    env_file: string
    env_file_exists: boolean
    api_key: 'missing' | 'placeholder' | 'configured'
    api_secret: 'missing' | 'placeholder' | 'configured'
    env_access_token: 'missing' | 'placeholder' | 'configured'
  }
  token: { has_valid_token: boolean; generated_at: string | null; expires_at: string | null; expired: boolean }
  ticker: { ticker_running: boolean; watched_instruments: number; last_tick_at: string | null; last_error: string | null }
  next_step: string
}

export interface ParamSpec {
  type: string
  default: number
  min?: number
  max?: number
  description?: string
}

export interface StrategySpec {
  file: string
  name: string
  version: number
  parameters: Record<string, ParamSpec>
}

export interface RunRecord {
  run_id: string
  strategy_id: string
  strategy_version: number
  resolved_params: string
  params_hash: string
  selected_stocks: string
  date_start: string | null
  date_end: string | null
  data_snapshot_id: string | null
  git_sha: string | null
  engine_version: string
  app_version: string
  status: 'success' | 'failed' | 'blocked'
  error_message: string | null
  duration_ms: number
  total_gross_pnl: number | null
  total_costs: number | null
  total_net_pnl: number | null
  num_trades: number | null
  win_rate: number | null
  created_at: string
}

export interface TradeLeg {
  leg_id: string
  trade_id: string
  action: 'buy' | 'sell'
  option_type: 'CE' | 'PE'
  strike: number
  expiry: string
  entry_price: number
  exit_price: number | null
}

export interface Trade {
  trade_id: string
  run_id: string
  symbol: string
  strategy_side: string
  entry_date: string
  exit_date: string | null
  lot_size: number
  lots: number
  gross_pnl: number
  costs: number
  net_pnl: number
  exit_reason: string
  legs: TradeLeg[]
}

export interface TradesResponse {
  total: number
  trades: Trade[]
}

export interface CompareRun extends RunRecord {
  pnl_by_stock: Record<string, number>
  cumulative_pnl: { date: string; cumulative_pnl: number }[]
  avg_holding_days: number | null
}

export interface KiteTokenStatus {
  has_valid_token: boolean
  ticker_running: boolean
}

export interface LiveWatch {
  instrument_token: number
  symbol: string
  strategy_id: string
  strategy_version: number
  open_trade_id: string | null
}

export interface LiveWatchResult {
  status: string
  symbol: string
  instrument_token: number
  strategy_id: string
  params: Record<string, number>
}

export interface PaperTrade {
  paper_trade_id: string
  watch_symbol: string
  strategy_id: string
  side: 'bull' | 'bear'
  entry_ts: string
  entry_price: number
  exit_ts: string | null
  exit_price: number | null
  exit_reason: string | null
  net_pnl: number | null
  status: 'OPEN' | 'CLOSED'
}

export interface LiveSocketEvent {
  type: 'market_tick' | 'signal'
  symbol: string
  price: number
  timestamp: string
  action?: 'ENTRY' | 'EXIT'
  strategy?: string
  trade_id?: string
  reason?: Record<string, unknown>
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number
  source?: string
  unique_key?: string
}

export interface LiveStatus {
  connected: boolean
  database: string
  websocket_clients: number
  last_received_timestamp: string | null
  last_symbol: string | null
  total_records: number
  csv_watcher: { running: boolean; directory: string; last_file: string | null; last_error: string | null; invalid_rows: number }
  kite: { authenticated: boolean; ticker_running: boolean }
  replay: ReplayStatus
}

export interface CreatedStrategy {
  file: string
  name: string
  version: number
  description: string
  parameters: Record<string, ParamSpec>
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  health: () => req<{ status: string }>('/health'),
  stats: () => req<Stats>('/stats'),
  symbols: () => req<string[]>('/symbols'),
  imports: () => req<ImportRecord[]>('/imports'),
  importPath: (path: string) => req<{ reports: QualityReport[] }>('/import', {
    method: 'POST',
    body: JSON.stringify({ path }),
  }),
  liveSync: (payload: { symbol: string; date_start?: string; date_end?: string; expiry?: string; strikes?: number[] }) =>
    req<LiveSyncResult>('/live/sync', { method: 'POST', body: JSON.stringify(payload) }),
  liveMarket: () => req<LiveMarketSnapshot>('/live/market'),
  liveStatus: () => req<LiveStatus>('/live/status'),
  liveRecords: (params?: { symbol?: string; limit?: number }) => {
    const search = new URLSearchParams()
    if (params?.symbol) search.set('symbol', params.symbol)
    if (params?.limit) search.set('limit', String(params.limit))
    return req<{ records: LiveSocketEvent[] }>(`/live/records?${search.toString()}`)
  },
  xSentiment: (payload: { symbol: string; max_results?: number }) =>
    req<XSentimentResult>('/live/x/sentiment', { method: 'POST', body: JSON.stringify(payload) }),
  dataCoverage: (symbol: string) => req<DataCoverage>(`/data-coverage?symbol=${encodeURIComponent(symbol)}`),
  strategies: () => req<StrategySpec[]>('/strategies'),
  createRun: (payload: { strategy_file: string; symbol: string; date_start?: string; date_end?: string; params?: Record<string, number> }) =>
    req<RunRecord>('/runs', { method: 'POST', body: JSON.stringify(payload) }),
  listRuns: () => req<RunRecord[]>('/runs'),
  runTrades: (runId: string) => req<Trade[]>(`/runs/${runId}/trades`),
  trades: (params: { run_id?: string; symbol?: string; exit_reason?: string; outcome?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '') qs.set(k, String(v)) })
    return req<TradesResponse>(`/trades?${qs.toString()}`)
  },
  compareRuns: (runIds: string[]) => req<CompareRun[]>(`/runs/compare?run_ids=${runIds.join(',')}`),
  createStrategy: (payload: { name: string; description?: string; parent_file?: string; parameters: Record<string, number> }) =>
    req<CreatedStrategy>('/strategies', { method: 'POST', body: JSON.stringify(payload) }),
  kiteLoginUrl: () => req<{ login_url: string }>('/kite/login-url'),
  kiteLoginCallback: (request_token: string) =>
    req<{ status: string }>('/kite/login-callback', { method: 'POST', body: JSON.stringify({ request_token }) }),
  kiteTokenStatus: () => req<KiteTokenStatus>('/kite/token-status'),
  kiteDiagnostics: () => req<KiteDiagnostics>('/kite/diagnostics'),
  replayStatus: () => req<ReplayStatus>('/live/replay/status'),
  captureStatus: () => req<CaptureStatus>('/live/capture-status'),
  schedulerStatus: () => req<SchedulerStatus>('/scheduler/status'),
  schedulerCycles: (limit = 20) => req<{ cycles: CaptureCycle[] }>(`/scheduler/cycles?limit=${limit}`),
  schedulerRunNow: () => req<CaptureCycle>('/scheduler/run-now', { method: 'POST' }),
  captureStart: (symbol: string, source = 'kite') =>
    req<unknown>('/live/capture/start', { method: 'POST', body: JSON.stringify({ symbol, source }) }),
  captureStop: (symbol: string) =>
    req<unknown>('/live/capture/stop', { method: 'POST', body: JSON.stringify({ symbol, source: 'kite' }) }),
  liveTicks: (symbol?: string, limit = 20) =>
    req<{ total: number; ticks: Array<Record<string, unknown>> }>(
      `/live/ticks?limit=${limit}${symbol ? `&symbol=${encodeURIComponent(symbol)}` : ''}`),
  livePositions: () => req<{ count: number; positions: LivePosition[] }>('/live/positions'),
  livePnl: () => req<{ current: PnlSnapshot; snapshots: PnlSnapshot[] }>('/live/pnl'),
  systemEvents: (limit = 20) => req<{ events: SystemEvent[] }>(`/live/events?limit=${limit}`),
  replayStart: (payload: { symbol: string; strategy_file?: string; speed?: number; bar_limit?: number }) =>
    req<ReplayStatus>('/live/replay/start', { method: 'POST', body: JSON.stringify(payload) }),
  replayStop: () => req<ReplayStatus>('/live/replay/stop', { method: 'POST' }),
  liveWatch: (payload: { symbol: string; strategy_file: string; params?: Record<string, number> }) =>
    req<LiveWatchResult>('/live/watch', { method: 'POST', body: JSON.stringify(payload) }),
  liveUnwatch: (instrument_token: number) =>
    req<{ status: string }>('/live/unwatch', { method: 'POST', body: JSON.stringify({ instrument_token }) }),
  liveWatchlist: () => req<LiveWatch[]>('/live/watchlist'),
  liveSignals: (symbol?: string) => req<PaperTrade[]>(`/live/signals${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''}`),
}
