# Frontend UI Best Practices & Component Library

## Complete Component Reference

### Basic Components (`ui.tsx`)

#### Card
Wrapper for grouped content with consistent styling.
```tsx
import { Card, CardTitle, CardSubtitle } from '@/components/ui'

<Card>
  <CardTitle>Title</CardTitle>
  <CardSubtitle>Description</CardSubtitle>
  {content}
</Card>
```

#### Button (3 Variants)
```tsx
<Button variant="primary">Primary Action</Button>
<Button variant="secondary">Secondary</Button>
<Button variant="ghost">Link-style</Button>
```

#### Data Display
```tsx
<StatBlock label="Total P&L" value={<PnlValue value={1234.56} />} />
<Pill tone="accent">LIVE</Pill>
<ProvenanceTag kind="demo" />
```

#### Empty State
```tsx
<EmptyState 
  title="No data"
  description="Try importing data first"
/>
```

---

### Advanced Components (`advanced.tsx`)

#### Skeleton Loading
For placeholder content while data loads:
```tsx
import { Skeleton, SkeletonCard, SkeletonTable } from '@/components/advanced'

// Minimal skeleton
<Skeleton width="200px" height="20px" />

// Skeleton card (default 3 lines)
<SkeletonCard lines={5} />

// Skeleton table (5 rows, 4 columns)
<SkeletonTable rows={5} cols={4} />
```

#### Input Field
With validation:
```tsx
import { Input } from '@/components/advanced'

<Input
  label="Amount"
  placeholder="1000"
  type="number"
  value={amount}
  onChange={setAmount}
  error={amount < 100 ? "Must be >= 100" : undefined}
/>
```

#### Select Dropdown
```tsx
import { Select } from '@/components/advanced'

<Select
  label="Strategy"
  options={[
    { value: 'spread', label: 'Debit Spread' },
    { value: 'strangle', label: 'Strangle' },
  ]}
  value={strategy}
  onChange={setStrategy}
  error={!strategy ? "Required" : undefined}
/>
```

#### Toast Notifications
Non-intrusive feedback messages. See hooks section for usage.

#### Modal Dialog
```tsx
import { Modal } from '@/components/advanced'
import { useModal } from '@/hooks/useNotifications'

const { isOpen, open, close } = useModal()

<Modal
  isOpen={isOpen}
  onClose={close}
  title="Confirm Action"
  actions={
    <>
      <Button variant="secondary" onClick={close}>Cancel</Button>
      <Button onClick={() => { /* action */ close() }}>Confirm</Button>
    </>
  }
>
  <p>Are you sure?</p>
</Modal>

<Button onClick={open}>Open Modal</Button>
```

#### Progress Bar
```tsx
import { Progress } from '@/components/advanced'

<Progress value={45} max={100} label="Backtest Progress" />
```

#### Badge
```tsx
import { Badge } from '@/components/advanced'

<Badge>default</Badge>
<Badge variant="success">Success</Badge>
<Badge variant="error">Error</Badge>
<Badge variant="warning">Warning</Badge>
```

#### Tabs
```tsx
import { Tabs } from '@/components/advanced'
import { useState } from 'react'

const [active, setActive] = useState('tab1')

<Tabs
  tabs={[
    { id: 'tab1', label: 'Overview' },
    { id: 'tab2', label: 'Details' },
  ]}
  active={active}
  onChange={setActive}
/>
```

---

### Data Table Components (`DataTable.tsx`)

#### DataTable
Fully featured table with sorting-ready structure:
```tsx
import { DataTable } from '@/components/DataTable'

<DataTable
  columns={[
    { key: 'symbol', label: 'Symbol', width: '100px' },
    { 
      key: 'pl', 
      label: 'P&L',
      render: (value) => (
        <span style={{ color: value > 0 ? 'green' : 'red' }}>
          {value.toFixed(2)}
        </span>
      )
    },
  ]}
  data={trades}
  isLoading={loading}
  emptyMessage="No trades"
  onRowClick={(row) => console.log(row)}
/>
```

#### Pagination
```tsx
import { Pagination } from '@/components/DataTable'

<Pagination 
  currentPage={page}
  totalPages={10}
  onPageChange={setPage}
/>
```

#### Filter Chips
```tsx
import { FilterChips } from '@/components/DataTable'

<FilterChips
  chips={[
    { id: 'win', label: 'Wins' },
    { id: 'loss', label: 'Losses' },
  ]}
  selected={selected}
  onSelect={(id) => {
    setSelected(prev => 
      prev.includes(id) 
        ? prev.filter(x => x !== id)
        : [...prev, id]
    )
  }}
/>
```

#### Expandable Row
For collapsible row details:
```tsx
import { ExpandableRow } from '@/components/DataTable'
import { useState } from 'react'

const [expanded, setExpanded] = useState(null)

{trades.map(trade => (
  <ExpandableRow
    key={trade.id}
    summary={<span>{trade.symbol} - {trade.pl}</span>}
    details={<TradeLegsTable legs={trade.legs} />}
    isExpanded={expanded === trade.id}
    onToggle={() => setExpanded(expanded === trade.id ? null : trade.id)}
  />
))}
```

---

### Notification Hooks (`hooks/useNotifications.ts`)

#### useToast
```tsx
import { useToast } from '@/hooks/useNotifications'

const toast = useToast()

// Methods
toast.success('Title', 'Optional description')
toast.error('Error title')
toast.warning('Warning')
toast.info('Info message')

// Show toast without auto-dismiss
toast.add('info', 'Title', 'Description', 0)

// Remove specific toast
toast.remove(toastId)
```

**In JSX:**
```tsx
import { useToastContext } from '@/components/ToastContainer'

function MyComponent() {
  const toast = useToastContext()
  
  const handleClick = () => {
    toast.success('Saved!', 'Your changes are saved')
  }
}
```

#### useModal
```tsx
import { useModal } from '@/hooks/useNotifications'

const { isOpen, open, close, toggle } = useModal(false)

<Button onClick={open}>Open</Button>
<Modal isOpen={isOpen} onClose={close} title="My Modal">
  Content here
</Modal>
```

---

### API Health Hook (`hooks/useApiHealth.ts`)

Monitor backend connection status:
```tsx
import { useApiHealth } from '@/hooks/useApiHealth'

const health = useApiHealth()
// { status: 'connected' | 'connecting' | 'disconnected' | 'error', latency?: number, error?: string }

if (health.status === 'connected') {
  return <div>✓ Connected ({health.latency}ms)</div>
}
```

---

## Usage Patterns

### Loading Pattern
```tsx
const [data, setData] = useState(null)
const [loading, setLoading] = useState(true)
const [error, setError] = useState(null)

useEffect(() => {
  const load = async () => {
    try {
      const res = await fetch('/api/trades')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }
  load()
}, [])

return (
  <>
    {loading && <SkeletonTable />}
    {error && <Toast type="error" title="Failed to load data" />}
    {data && <DataTable columns={...} data={data} />}
  </>
)
```

### Form Pattern
```tsx
import { useToastContext } from '@/components/ToastContainer'
import { Input, Select } from '@/components/advanced'
import { Button } from '@/components/ui'

function StrategyForm() {
  const [name, setName] = useState('')
  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(false)
  const toast = useToastContext()

  const validate = () => {
    const newErrors = {}
    if (!name) newErrors.name = 'Required'
    if (name.length < 3) newErrors.name = 'At least 3 characters'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!validate()) return

    setLoading(true)
    try {
      const res = await fetch('/api/strategies', {
        method: 'POST',
        body: JSON.stringify({ name }),
      })
      if (!res.ok) throw new Error('Failed')
      toast.success('Strategy created!')
      setName('')
    } catch (err) {
      toast.error('Failed to create', err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Input
        label="Strategy Name"
        value={name}
        onChange={setName}
        error={errors.name}
        disabled={loading}
      />
      <Button type="submit" disabled={loading}>
        {loading ? 'Creating...' : 'Create Strategy'}
      </Button>
    </form>
  )
}
```

### Data Table with Filtering Pattern
```tsx
const [page, setPage] = useState(1)
const [filters, setFilters] = useState([])

const filteredData = data.filter(row =>
  filters.length === 0 || filters.includes(row.outcome)
)

return (
  <>
    <FilterChips
      chips={[
        { id: 'win', label: 'Wins' },
        { id: 'loss', label: 'Losses' },
      ]}
      selected={filters}
      onSelect={(id) => setFilters(prev =>
        prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
      )}
    />
    <DataTable columns={...} data={filteredData} />
    <Pagination
      currentPage={page}
      totalPages={Math.ceil(filteredData.length / 20)}
      onPageChange={setPage}
    />
  </>
)
```

---

## Style Patterns

### Color Usage
Always use CSS variables for theme support:
```tsx
// ✓ Good
<div style={{ color: 'var(--color-ink)' }}>Text</div>

// ✗ Bad
<div style={{ color: '#111827' }}>Text</div>
```

### Responsive Classes
Use Tailwind breakpoints:
```tsx
<div className="px-4 sm:px-6 lg:px-8">
  Responsive padding
</div>
```

### Spacing
Use Tailwind's spacing scale (4px base):
```tsx
<div className="space-y-4">  {/* gap-y: 1rem */}
  <div>Item 1</div>
  <div>Item 2</div>
</div>

<div className="flex gap-3">  {/* gap: 0.75rem */}
  <span>Icon</span>
  <span>Text</span>
</div>
```

---

## Accessibility Checklist

- [ ] All interactive elements are keyboard accessible
- [ ] Form inputs have associated labels
- [ ] Color isn't the only way to convey information
- [ ] Icons have aria-labels when standalone
- [ ] Tables have proper thead/tbody structure
- [ ] Modals trap focus (manage with onKeyDown)
- [ ] Error messages are associated with inputs
- [ ] Sufficient color contrast (WCAG AA minimum)

---

## Performance Tips

1. **Lazy load pages** — Already set up via Vite code splitting
2. **Virtualize long lists** — Use pagination or window library
3. **Debounce input handlers** — For search/filter
4. **Memoize callbacks** — useCallback for event handlers
5. **Split state** — Keep local state close to where it's used

---

## Common Issues

| Problem | Solution |
|---------|----------|
| Toast doesn't show | Wrap app with `<ToastProvider>` first |
| Modal scrolls body | Modal has `max-h-[60vh] overflow-auto` |
| Table overflow on mobile | Wrap with `overflow-x-auto` |
| Form validation lost | Store errors in separate state |
| Loading state stuck | Always clean up in useEffect |

---

## Testing Components

See `src/components/ComponentShowcase.tsx` for interactive examples of all components.

To add showcase route to your app:
```tsx
import { ComponentShowcase } from '@/components/ComponentShowcase'

// In your router:
if (page === 'showcase') return <ComponentShowcase />
```

