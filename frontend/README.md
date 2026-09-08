# Frontend — Options Strategy Analyzer

React 19 + TypeScript + Vite + Tailwind CSS v4 frontend for the Options Strategy Analyzer.

## Setup

```bash
npm install
npm run dev
```

Then open http://localhost:5173 (make sure backend is running on 127.0.0.1:8000)

## Commands

| Command | Purpose |
|---------|---------|
| `npm run dev` | Start dev server with HMR (hot reload) |
| `npm run build` | Production build to `dist/` |
| `npm run preview` | Preview production build locally |
| `npm run lint` | Run Oxlint code quality checks |

## Architecture

### Pages
Located in `src/pages/`:
- **OverviewPage** — Dashboard with key metrics
- **StrategyRunnerPage** — Run backtests with strategy + symbol pickers
- **CompareRunsPage** — Multi-run comparison with charts
- **TradeExplorerPage** — Global trade table with filters
- **DataManagerPage** — CSV import & quality reports
- **LiveMonitorPage** — Real-time market data (when Kite connected)
- **StrategyBuilderPage** — Future: Strategy design tool

### Components
Located in `src/components/`:
- **Layout** — Main app shell with sidebar nav + header
- **ConnectionBanner** — Backend connection status indicator
- **ui.tsx** — Reusable UI primitives (Card, Button, Pill, ProvenanceTag, etc.)

### Hooks
Located in `src/hooks/`:
- **useTheme** — Dark/light mode toggle with localStorage
- **useApiHealth** — Backend connectivity monitoring

### Lib
Located in `src/lib/`:
- **api.ts** — Fetch wrapper + shared request/response handling

## Design System

### Theme Variables
All colors, spacing, typography defined in `src/index.css` as CSS variables:
- Light mode (default)
- Dark mode (`.dark` class)

Always use `var(--color-*)` instead of hardcoded colors.

### Fonts
- **Display** — Space Grotesk (headings)
- **Body** — DM Sans (content)
- **Mono** — JetBrains Mono (numbers, tags)

### Styling
- **Tailwind CSS v4** for layout, spacing, responsive
- **CSS variables** for theming
- **Inline `style` props** for dynamic color theming

Example:
```tsx
<div style={{ color: 'var(--color-ink)' }} className="text-lg font-semibold">
  Heading
</div>
```

## Component Usage

### Import UI Components
```tsx
import { 
  Card, CardTitle, CardSubtitle,
  Button, Pill, ProvenanceTag,
  StatBlock, PnlValue,
  EmptyState, BlockedNotice,
  Spinner
} from '@/components/ui'
```

### Common Patterns

#### Data Card with Provenance
```tsx
<Card>
  <div className="flex items-center justify-between">
    <div>
      <CardTitle>Total Profit</CardTitle>
      <StatBlock label="P&L" value={<PnlValue value={1234.56} />} />
    </div>
    <ProvenanceTag kind="demo" />
  </div>
</Card>
```

#### Empty State
```tsx
{trades.length === 0 && (
  <EmptyState 
    title="No trades yet"
    description="Run a strategy to generate trades"
  />
)}
```

#### Button Group
```tsx
<div className="flex gap-2">
  <Button variant="primary">Run</Button>
  <Button variant="secondary">Cancel</Button>
  <Button variant="ghost">Learn more</Button>
</div>
```

## API Client

See `src/lib/api.ts` for all API call patterns.

### Example: Fetch Data
```tsx
import { useState, useEffect } from 'react'

export function MyComponent() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch('/api/trades')
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const json = await res.json()
        setData(json)
      } catch (err) {
        setError(err)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) return <Spinner />
  if (error) return <div>Error: {error.message}</div>
  return <div>{JSON.stringify(data)}</div>
}
```

## Connection Issues

If you see "Backend not running" banner:

1. Make sure backend is running: `python -m uvicorn server.main:app --reload`
2. Check it's on http://127.0.0.1:8000
3. Browser console may have more details

The frontend automatically checks backend health every 5 seconds and displays connection status.

## Development Checklist

- [ ] Both backend + frontend servers running
- [ ] No TypeScript errors (`npm run build` passes)
- [ ] No linting errors (`npm run lint` passes)
- [ ] ConnectionBanner shows "connected"
- [ ] Navigation works (click sidebar items)
- [ ] Dark mode toggle works
- [ ] Responsive on mobile (F12 → device toolbar)

## Performance Tips

- Pages are lazy-loaded (code splitting via Vite)
- Charts (Recharts) only render when visible
- Use React DevTools Profiler to find slow components
- Keep component state as local as possible

## Next Steps

See [../UI_IMPROVEMENTS.md](../UI_IMPROVEMENTS.md) for planned UI enhancements.



See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
