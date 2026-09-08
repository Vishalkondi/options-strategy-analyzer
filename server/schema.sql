-- Single DuckDB database. Idempotent: CREATE ... IF NOT EXISTS everywhere.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS imports (
    import_id           UBIGINT PRIMARY KEY,
    file_path            VARCHAR,
    file_hash             VARCHAR UNIQUE,          -- SHA-256 of file bytes; enforces idempotency
    symbol                VARCHAR,
    kind                  VARCHAR,                 -- 'equity' | 'options'
    rows_read             INTEGER,
    rows_accepted         INTEGER,
    rows_rejected         INTEGER,
    duplicates            INTEGER,
    glued_rows_fixed      INTEGER,
    missing_values        INTEGER,
    invalid_values        INTEGER,
    date_start            DATE,
    date_end              DATE,
    trading_day_count     INTEGER,
    warnings              VARCHAR,                 -- JSON-encoded list
    errors                VARCHAR,                 -- JSON-encoded list
    imported_at           TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS equity_bars (
    symbol          VARCHAR NOT NULL,
    trading_date    DATE NOT NULL,
    timestamp       TIMESTAMP NOT NULL,
    bar_interval    VARCHAR NOT NULL DEFAULT '1d',
    open            DOUBLE,
    high            DOUBLE,
    low             DOUBLE,
    close           DOUBLE,
    prev_close      DOUBLE,
    vwap            DOUBLE,
    volume          BIGINT,
    turnover        DOUBLE,
    total_trades    BIGINT,
    deliverable_qty BIGINT,
    deliverable_pct DOUBLE,
    import_id       UBIGINT,
    PRIMARY KEY (symbol, trading_date, bar_interval)
);

CREATE TABLE IF NOT EXISTS option_bars (
    underlying      VARCHAR NOT NULL,
    timestamp       TIMESTAMP NOT NULL,
    trading_date    DATE NOT NULL,
    expiry          DATE NOT NULL,
    strike          DOUBLE NOT NULL,
    option_type     VARCHAR NOT NULL,   -- 'CE' | 'PE'
    bar_interval    VARCHAR NOT NULL DEFAULT '1d',
    open            DOUBLE,
    high            DOUBLE,
    low             DOUBLE,
    close           DOUBLE,
    settle          DOUBLE,
    open_interest   BIGINT,
    chg_in_oi       BIGINT,
    contracts       BIGINT,
    lot_size        INTEGER,            -- nullable; unresolved per GAP_ANALYSIS B6
    import_id       UBIGINT,
    PRIMARY KEY (underlying, timestamp, expiry, strike, option_type, bar_interval)
);

CREATE TABLE IF NOT EXISTS strategies (
    strategy_id     VARCHAR NOT NULL,
    version         INTEGER NOT NULL,
    parent_version  INTEGER,
    name            VARCHAR,
    description     VARCHAR,
    config_yaml     VARCHAR NOT NULL,
    config_hash     VARCHAR NOT NULL,
    param_schema    VARCHAR NOT NULL,   -- JSON-encoded
    created_at      TIMESTAMP DEFAULT current_timestamp,
    is_used         BOOLEAN DEFAULT false,  -- becomes immutable once true
    PRIMARY KEY (strategy_id, version)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id              VARCHAR PRIMARY KEY,
    strategy_id         VARCHAR NOT NULL,
    strategy_version    INTEGER NOT NULL,
    resolved_params     VARCHAR NOT NULL,   -- JSON
    params_hash         VARCHAR NOT NULL,
    selected_stocks     VARCHAR NOT NULL,   -- JSON list
    date_start          DATE,
    date_end            DATE,
    data_snapshot_id    VARCHAR,
    git_sha             VARCHAR,
    engine_version      VARCHAR,
    app_version         VARCHAR,
    status              VARCHAR,            -- 'success' | 'failed' | 'blocked'
    error_message       VARCHAR,
    duration_ms         INTEGER,
    total_gross_pnl     DOUBLE,
    total_costs         DOUBLE,
    total_net_pnl       DOUBLE,
    num_trades          INTEGER,
    win_rate            DOUBLE,
    created_at          TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id        VARCHAR PRIMARY KEY,
    run_id          VARCHAR NOT NULL,
    symbol          VARCHAR NOT NULL,
    strategy_side   VARCHAR,            -- 'bull_call_debit_spread' | 'bear_put_debit_spread'
    entry_date      DATE,
    exit_date       DATE,
    lot_size        INTEGER,
    lots            INTEGER,
    gross_pnl       DOUBLE,
    costs           DOUBLE,
    net_pnl         DOUBLE,
    exit_reason     VARCHAR             -- 'target' | 'stop' | 'expiry'
);

CREATE TABLE IF NOT EXISTS trade_legs (
    leg_id          VARCHAR PRIMARY KEY,
    trade_id        VARCHAR NOT NULL,
    action          VARCHAR,            -- 'buy' | 'sell'
    option_type     VARCHAR,            -- 'CE' | 'PE'
    strike          DOUBLE,
    expiry          DATE,
    entry_price     DOUBLE,
    exit_price      DOUBLE
);

CREATE TABLE IF NOT EXISTS paper_positions (
    position_id VARCHAR PRIMARY KEY, symbol VARCHAR NOT NULL, expiry DATE NOT NULL,
    strike DOUBLE NOT NULL, option_type VARCHAR NOT NULL, quantity INTEGER NOT NULL,
    entry_price DOUBLE NOT NULL, status VARCHAR NOT NULL, opened_at TIMESTAMP NOT NULL,
    exit_price DOUBLE, pnl DOUBLE, closed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_orders (
    order_id VARCHAR PRIMARY KEY, position_id VARCHAR NOT NULL, side VARCHAR NOT NULL,
    quantity INTEGER NOT NULL, price DOUBLE NOT NULL, status VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL
);

-- Phase 2: Live Data Tables

CREATE TABLE IF NOT EXISTS kite_sessions (
    id              INTEGER PRIMARY KEY,
    access_token    VARCHAR NOT NULL,
    generated_at    TIMESTAMP NOT NULL,
    expires_at      TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol              VARCHAR NOT NULL,
    strategy_id         VARCHAR NOT NULL,
    strategy_version    INTEGER NOT NULL,
    params_json         VARCHAR,
    instrument_token    INTEGER,
    added_at            TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, strategy_id, strategy_version)
);

CREATE TABLE IF NOT EXISTS live_ticks (
    symbol          VARCHAR NOT NULL,
    ts              TIMESTAMP NOT NULL,
    ltp             DOUBLE NOT NULL,
    volume          BIGINT,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS live_market_data (
    id              BIGINT PRIMARY KEY,
    timestamp       TIMESTAMP NOT NULL,
    symbol          VARCHAR NOT NULL,
    open            DOUBLE NOT NULL,
    high            DOUBLE NOT NULL,
    low             DOUBLE NOT NULL,
    close           DOUBLE NOT NULL,
    volume          BIGINT NOT NULL,
    received_at     TIMESTAMP DEFAULT current_timestamp,
    source          VARCHAR NOT NULL DEFAULT 'api',
    unique_key      VARCHAR NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS paper_trades (
    paper_trade_id  VARCHAR PRIMARY KEY,
    watch_symbol    VARCHAR NOT NULL,
    strategy_id     VARCHAR NOT NULL,
    side            VARCHAR,                       -- 'bull' | 'bear' (direction from strategy_debit_spread)
    entry_ts        TIMESTAMP,
    entry_price     DOUBLE,
    exit_ts         TIMESTAMP,
    exit_price      DOUBLE,
    exit_reason     VARCHAR,                       -- 'target' | 'stop' | 'expiry'
    net_pnl         DOUBLE,
    status          VARCHAR NOT NULL DEFAULT 'OPEN'  -- 'OPEN' | 'CLOSED'
);

-- One row per capture run, so you can tell a two-hour recording from a
-- restarted one and see which session produced which bars.
CREATE TABLE IF NOT EXISTS capture_sessions (
    session_id      VARCHAR PRIMARY KEY,
    symbol          VARCHAR NOT NULL,
    source          VARCHAR NOT NULL,
    bar_interval    VARCHAR NOT NULL DEFAULT '1m',
    started_at      TIMESTAMP NOT NULL,
    stopped_at      TIMESTAMP,
    bars_captured   INTEGER DEFAULT 0,
    status          VARCHAR NOT NULL DEFAULT 'RUNNING',  -- 'RUNNING' | 'STOPPED'
    last_error      VARCHAR
);

-- Signals have never been persisted: signals.py wrote paper_trades and
-- broadcast the ENTRY/EXIT event, which then vanished. This is the audit
-- trail of what the strategy decided and why, independent of whether a
-- trade resulted.
CREATE TABLE IF NOT EXISTS strategy_signals (
    signal_id       VARCHAR PRIMARY KEY,
    symbol          VARCHAR NOT NULL,
    strategy_id     VARCHAR NOT NULL,
    strategy_version INTEGER,
    run_id          VARCHAR,                        -- backtest run, NULL for live
    paper_trade_id  VARCHAR,                        -- resulting trade, if any
    action          VARCHAR NOT NULL,               -- 'ENTRY' | 'EXIT'
    side            VARCHAR,                        -- 'bull' | 'bear'
    price           DOUBLE,
    signal_ts       TIMESTAMP NOT NULL,             -- bar timestamp
    reason          VARCHAR,                        -- 'target' | 'stop' | 'crossover' ...
    metadata        VARCHAR,                        -- JSON: indicator values at signal time
    source          VARCHAR NOT NULL DEFAULT 'live',
    created_at      TIMESTAMP DEFAULT current_timestamp
);

-- Point-in-time P&L, so history can be reconstructed without recomputing
-- from trades and without depending on frontend state.
CREATE TABLE IF NOT EXISTS pnl_snapshots (
    snapshot_id     VARCHAR PRIMARY KEY,
    snapshot_ts     TIMESTAMP NOT NULL,
    scope           VARCHAR NOT NULL DEFAULT 'live',  -- 'live' | 'run'
    strategy_id     VARCHAR,
    run_id          VARCHAR,
    symbol          VARCHAR,
    realized_pnl    DOUBLE DEFAULT 0,
    unrealized_pnl  DOUBLE DEFAULT 0,
    total_pnl       DOUBLE DEFAULT 0,
    open_positions  INTEGER DEFAULT 0,
    closed_positions INTEGER DEFAULT 0,
    capital         DOUBLE,
    return_pct      DOUBLE,
    created_at      TIMESTAMP DEFAULT current_timestamp
);

-- Operational audit log: connection transitions, ingestion events, write
-- failures. Errors must be visible in the database, not only in stdout.
CREATE TABLE IF NOT EXISTS system_events (
    event_id        VARCHAR PRIMARY KEY,
    event_ts        TIMESTAMP NOT NULL,
    category        VARCHAR NOT NULL,   -- 'kite' | 'capture' | 'database' | 'strategy' | 'ingest'
    severity        VARCHAR NOT NULL,   -- 'INFO' | 'WARNING' | 'ERROR'
    event           VARCHAR NOT NULL,
    detail          VARCHAR,
    metadata        VARCHAR,            -- JSON
    created_at      TIMESTAMP DEFAULT current_timestamp
);

-- One row per scheduled capture cycle. This is the audit trail that answers
-- "did the 30-minute capture run, and what did it write?" -- including the
-- cycles that failed, which are the ones you actually need to see.
CREATE TABLE IF NOT EXISTS capture_cycles (
    cycle_id            VARCHAR PRIMARY KEY,
    cycle_number        BIGINT,
    scheduled_at        TIMESTAMP NOT NULL,   -- when the cycle was due
    started_at          TIMESTAMP NOT NULL,   -- when it actually began
    finished_at         TIMESTAMP,
    duration_ms         BIGINT,
    status              VARCHAR NOT NULL,     -- 'SUCCESS' | 'PARTIAL' | 'FAILED' | 'RUNNING'
    trigger             VARCHAR DEFAULT 'scheduler',  -- 'scheduler' | 'manual' | 'startup'
    attempts            INTEGER DEFAULT 1,
    symbols_requested   INTEGER DEFAULT 0,
    symbols_captured    INTEGER DEFAULT 0,
    ticks_inserted      INTEGER DEFAULT 0,
    bars_inserted       INTEGER DEFAULT 0,
    option_rows_inserted INTEGER DEFAULT 0,
    signals_inserted    INTEGER DEFAULT 0,
    pnl_snapshots_inserted INTEGER DEFAULT 0,
    total_records       INTEGER DEFAULT 0,
    market_open         BOOLEAN,
    error               VARCHAR,
    detail              VARCHAR               -- JSON: per-symbol breakdown
);
