# Options Strategy Analyzer

> A full-stack options strategy backtesting and analysis platform built with
> FastAPI, React 19, TypeScript, Tailwind CSS, DuckDB, and configurable
> strategy definitions.

![Options Strategy Analyzer](docs/images/dashboard%20(1).png)

> ⚠️ **Development / Demo Status**
>
> This project is currently a working development build using synthetic demo
> market data. The strategy logic, indicators, lot sizes, transaction costs,
> and golden backtest results are not yet fully validated against the
> production/validated implementation.
>
> **Do not treat the displayed P&L as real or validated trading performance.**

---

## Overview

Options Strategy Analyzer is a full-stack application designed to import
market data, configure options strategies, run historical backtests, persist
trades, compare backtest runs, and explore individual trades and option legs.

The current implementation provides a real end-to-end workflow using
synthetic demo data.

The backend actually:

- Imports CSV market data
- Validates OHLC data
- Performs SHA-256 based idempotency checks
- Stores market data in DuckDB
- Calculates indicators
- Generates strategy entry signals
- Prices option spread legs
- Executes exits based on target, stop, or expiry
- Persists trades and trade legs
- Calculates run-level P&L and win rate
- Stores reproducibility metadata
- Exposes the functionality through a FastAPI REST API

The frontend is a real React application connected to the backend API.

---

# Features

- 📊 Market data ingestion and validation
- 🔐 SHA-256 based import idempotency
- 📈 SMA and Wilder's ADX indicators
- 🧮 Options strategy backtesting
- 💾 DuckDB persistence
- 📋 Trade and trade-leg persistence
- 📊 Multi-run comparison
- 📉 Cumulative P&L visualization
- 🔎 Global trade explorer
- ⚙️ YAML-driven strategy parameters
- 🧪 Automated unit and mechanics tests
- 🔄 Backtest reproducibility metadata
- 🟢 Optional Zerodha/Kite historical data synchronization
- 🌗 Light/dark theme support
- 🚦 DEMO DATA / BLOCKED provenance indicators
- 🖥️ Windows one-click development startup

---

# Technology Stack

| Layer | Technology |
|---|---|
| Frontend | React 19 |
| Language | TypeScript |
| Build Tool | Vite |
| Styling | Tailwind CSS v4 |
| Charts | Recharts |
| Backend | Python |
| API | FastAPI |
| Database | DuckDB |
| Configuration | YAML |
| Testing | pytest |
| Market Data | Synthetic demo data |
| Optional Live Data | Zerodha Kite Connect |

---

# Architecture

```text
┌──────────────────────────────────────────────┐
│                  React UI                    │
│                                              │
│ React 19 + TypeScript + Vite                 │
│ Tailwind CSS + Recharts                      │
│                                              │
│ Data Manager                                 │
│ Strategy Runner                              │
│ Compare Runs                                 │
│ Trade Explorer                               │
└──────────────────────┬───────────────────────┘
                       │
                       │ REST API
                       ▼
┌──────────────────────────────────────────────┐
│                  FastAPI                     │
│              server/main.py                  │
│                                              │
│ /api/import                                  │
│ /api/data-coverage                           │
│ /api/strategies                              │
│ /api/runs                                    │
│ /api/runs/{id}/trades                        │
│ /api/live/sync                               │
└───────────────┬──────────────┬───────────────┘
                │              │
                ▼              ▼
       ┌────────────────┐  ┌────────────────┐
       │ Data Ingestion │  │ Backtest       │
       │ & Validation   │  │ Engine         │
       │                │  │                │
       │ SHA-256        │  │ Entry Signals  │
       │ OHLC Checks    │  │ Option Pricing │
       │ Quality Report │  │ Exit Rules     │
       └───────┬────────┘  └───────┬────────┘
               │                   │
               └─────────┬─────────┘
                         ▼
                 ┌───────────────┐
                 │    DuckDB     │
                 │               │
                 │ imports       │
                 │ equity_bars   │
                 │ option_bars   │
                 │ strategies    │
                 │ runs          │
                 │ trades        │
                 │ trade_legs    │
                 └───────────────┘
