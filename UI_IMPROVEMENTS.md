# UI/UX Improvements & Design System

## Current Status
- ✅ Professional design system in place (spacing, colors, typography)
- ✅ Dark mode support
- ✅ Tailwind CSS v4 + custom theme variables
- ✅ Component library with primitives (Card, Button, StatBlock, etc.)
- ✅ Responsive layout (sidebar, header, main content)
- ✅ Provenance tags (data lineage indicators)
- ✅ Connection status banner (NEW)
- ✅ Empty states and blocked notices

## Implemented Enhancements (Session)
1. **Connection Status Banner** — Shows backend connectivity status
   - Auto-checks `/api/health` every 5 seconds
   - Displays latency in milliseconds
   - Shows clear error messages for disconnection

2. **Development Startup Script** — `start-dev.bat`
   - Automatically starts both backend and frontend
   - Sets up venv and installs dependencies
   - Opens in separate terminal windows
   - One-click development environment

## Next-Priority UI Improvements

### High Priority (Better UX)
- [ ] **Loading States & Skeletons**
  - Data loading skeletons for trade tables, charts
  - Spinner states for running backtests
  - Progress indicators for long operations

- [ ] **Real-time Data Visualization**
  - Live P&L charts with auto-refresh
  - Trade entry/exit markers on candlesticks
  - Greeks visualization (Delta, Gamma, Theta, Vega)

- [ ] **Enhanced Error Handling**
  - Toast notifications for API errors
  - Form validation with inline error messages
  - Graceful fallbacks when backend unavailable

- [ ] **Data Tables**
  - Sortable trade explorer columns
  - Filterable by outcome, entry reason, exit reason
  - Pagination or virtual scrolling for large datasets
  - Expandable row details (legs breakdown)

### Medium Priority (Polish)
- [ ] **Mobile Responsiveness**
  - Collapsible sidebar on mobile
  - Touch-friendly button sizes (48x48px minimum)
  - Responsive grid layouts

- [ ] **Accessibility**
  - ARIA labels on all interactive elements
  - Keyboard navigation (Tab, Enter, Escape)
  - High contrast mode support
  - Screen reader friendly

- [ ] **Performance Optimizations**
  - Code splitting by page
  - Lazy loading for charts/tables
  - Query deduplication with React Query or SWR

### Nice to Have (Polish)
- [ ] **Animations**
  - Smooth page transitions
  - Chart animation on data updates
  - Micro-interactions on hover/click

- [ ] **Charts & Analytics**
  - Cumulative P&L curves
  - Strategy comparison heatmaps
  - Greeks surfaces for options analysis

- [ ] **Keyboard Shortcuts**
  - Cmd/Ctrl+K to open search/command palette
  - S to jump to Strategy Runner
  - T to jump to Trade Explorer

---

## Design System Reference

### Color Palette
```javascript
// Light mode
--color-paper:           #F4F6F8    (Background)
--color-surface:         #FFFFFF    (Cards)
--color-border:          #DDE3E8    (Dividers)
--color-ink:             #111827    (Text)
--color-ink-muted:       #6B7280    (Secondary text)
--color-accent:          #D6A84F    (Gold/Primary actions)
--color-profit:          #16A34A    (Green/Gains)
--color-loss:            #DC2626    (Red/Losses)
--color-warn:            #D97706    (Amber/Warnings)

// Dark mode: same variables, different values
```

### Typography
- **Display** — Space Grotesk (headings, brand)
- **Body** — DM Sans (content, UI text)
- **Mono** — JetBrains Mono (data, numbers, tags)

### Spacing
- Based on 4px grid
- `px-3`, `py-2`, `gap-3`, etc. for consistent rhythm

### Shadows
- `shadow-card` — 0 8px 24px rgba(16, 42, 46, 0.06)
- Used for depth on hover/interaction

---

## Component API Quick Reference

### Import Pattern
```tsx
import { Card, CardTitle, Button, Pill, PnlValue, ProvenanceTag } from '@/components/ui'
```

### Common Components

#### Card
```tsx
<Card>
  <CardTitle>My Title</CardTitle>
  <CardSubtitle>Description</CardSubtitle>
  <ProvenanceTag kind="demo" />
  {/* content */}
</Card>
```

#### Button Variants
```tsx
<Button variant="primary">Primary</Button>
<Button variant="secondary">Secondary</Button>
<Button variant="ghost">Ghost</Button>
```

#### Data Display
```tsx
<StatBlock label="Profit/Loss" value={<PnlValue value={1234.56} />} />
<Pill tone="accent">LIVE</Pill>
<ProvenanceTag kind="live" />
```

#### Empty States
```tsx
<EmptyState 
  icon={<Icon />}
  title="No trades yet"
  description="Run a strategy to generate trades"
/>
```

---

## File Structure
```
frontend/
├── src/
│   ├── components/
│   │   ├── Layout.tsx              (Main app shell)
│   │   ├── ConnectionBanner.tsx    (Backend status) [NEW]
│   │   └── ui.tsx                  (Component library)
│   ├── hooks/
│   │   ├── useTheme.ts             (Dark mode)
│   │   └── useApiHealth.ts         (Backend health) [NEW]
│   ├── lib/
│   │   └── api.ts                  (API client)
│   ├── pages/
│   │   ├── OverviewPage.tsx
│   │   ├── StrategyRunnerPage.tsx
│   │   ├── TradeExplorerPage.tsx
│   │   └── ... (others)
│   ├── index.css                   (Theme variables + Tailwind)
│   ├── main.tsx                    (Entry point)
│   └── App.tsx                     (Router)
├── package.json
├── vite.config.ts                  (Build config)
└── README.md
```

---

## Running the Frontend

```bash
cd frontend

# Development
npm run dev          # http://localhost:5173

# Production build
npm build            # Outputs to dist/

# Preview build
npm run preview       # Test production build locally

# Linting
npm run lint         # Run oxlint
```

---

## Tips for Extending UI

### Adding a New Component
1. Create in `src/components/NewComponent.tsx`
2. Follow existing pattern (use `var(--color-*)`, Tailwind for layout)
3. Export from `ui.tsx` if it's generic
4. Import and use in pages

### Styling with Theme
- **Always** use CSS variables, not hardcoded colors
- Dark mode is auto-applied via `.dark` class on root
- Example: `style={{ color: 'var(--color-ink)' }}`

### Forms
- Use standard HTML `<input>`, `<select>`, `<textarea>`
- Add styling in `index.css` under `input, select` rule
- Validation errors in placeholder or separate error div

---

## Testing UI Locally

With both servers running:
1. http://localhost:5173 — Frontend dev server
2. http://127.0.0.1:8000 — Backend API

Check:
- ✅ ConnectionBanner shows "connected"
- ✅ Navigation works (click sidebar items)
- ✅ Dark mode toggle works (click moon icon)
- ✅ Responsive on mobile (open DevTools F12, toggle device toolbar)

