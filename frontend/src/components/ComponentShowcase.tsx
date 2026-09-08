import { useState } from 'react'
import { Card, CardTitle, Button } from './ui'
import { Input, Select, SkeletonCard, Toast, Modal, Progress, Badge, Tabs } from './advanced'
import { DataTable, Pagination, FilterChips } from './DataTable'

export function ComponentShowcase() {
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [selectedTab, setSelectedTab] = useState('inputs')

  // Mock data
  const mockTrades = [
    { id: 1, symbol: 'NIFTY', entry: 18500, exit: 18600, pl: 1200.5, outcome: 'Win' },
    { id: 2, symbol: 'SENSEX', entry: 62000, exit: 61800, pl: -850.25, outcome: 'Loss' },
    { id: 3, symbol: 'BANKNIFTY', entry: 45000, exit: 45500, pl: 2500, outcome: 'Win' },
  ]

  return (
    <div className="space-y-8 pb-8">
      <div>
        <h1 className="text-2xl font-bold mb-2" style={{ color: 'var(--color-ink)' }}>
          UI Component Showcase
        </h1>
        <p style={{ color: 'var(--color-ink-muted)' }}>
          Reference guide for all available UI components
        </p>
      </div>

      {/* Tabs */}
      <Card>
        <Tabs
          tabs={[
            { id: 'inputs', label: 'Inputs & Forms' },
            { id: 'tables', label: 'Tables & Data' },
            { id: 'states', label: 'States & Loading' },
            { id: 'feedback', label: 'Feedback & Notifications' },
          ]}
          active={selectedTab}
          onChange={setSelectedTab}
        />
      </Card>

      {/* Inputs & Forms */}
      {selectedTab === 'inputs' && (
        <div className="space-y-6">
          <Card>
            <CardTitle>Text Input</CardTitle>
            <div className="mt-4">
              <Input
                label="Strategy Name"
                placeholder="Enter strategy name"
                type="text"
              />
            </div>
          </Card>

          <Card>
            <CardTitle>Input with Error</CardTitle>
            <div className="mt-4">
              <Input
                label="Amount"
                placeholder="1000"
                type="number"
                error="Must be greater than 100"
              />
            </div>
          </Card>

          <Card>
            <CardTitle>Select Dropdown</CardTitle>
            <div className="mt-4">
              <Select
                label="Strategy Type"
                options={[
                  { value: 'spread', label: 'Debit Spread' },
                  { value: 'straddle', label: 'Straddle' },
                  { value: 'strangle', label: 'Strangle' },
                ]}
              />
            </div>
          </Card>

          <Card>
            <CardTitle>Badges</CardTitle>
            <div className="flex gap-2 flex-wrap mt-4">
              <Badge>Default</Badge>
              <Badge variant="success">Success</Badge>
              <Badge variant="error">Error</Badge>
              <Badge variant="warning">Warning</Badge>
            </div>
          </Card>
        </div>
      )}

      {/* Tables & Data */}
      {selectedTab === 'tables' && (
        <div className="space-y-6">
          <Card>
            <CardTitle>Data Table</CardTitle>
            <div className="mt-4">
              <DataTable
                columns={[
                  { key: 'symbol', label: 'Symbol', width: '100px' },
                  { key: 'entry', label: 'Entry', render: (v) => v.toFixed(0) },
                  { key: 'exit', label: 'Exit', render: (v) => v.toFixed(0) },
                  {
                    key: 'pl',
                    label: 'P&L',
                    render: (v) => (
                      <span style={{ color: v > 0 ? 'var(--color-profit)' : 'var(--color-loss)' }}>
                        {v > 0 ? '+' : ''}{v.toFixed(2)}
                      </span>
                    ),
                  },
                ]}
                data={mockTrades}
                emptyMessage="No trades found"
              />
            </div>
          </Card>

          <Card>
            <CardTitle>Table with Loading</CardTitle>
            <div className="mt-4">
              <DataTable
                columns={[
                  { key: 'symbol', label: 'Symbol' },
                  { key: 'entry', label: 'Entry' },
                  { key: 'exit', label: 'Exit' },
                ]}
                data={[]}
                isLoading={true}
              />
            </div>
          </Card>

          <Card>
            <CardTitle>Pagination</CardTitle>
            <div className="mt-4">
              <Pagination currentPage={page} totalPages={10} onPageChange={setPage} />
              <p className="text-center text-sm mt-2" style={{ color: 'var(--color-ink-muted)' }}>
                Page {page} of 10
              </p>
            </div>
          </Card>

          <Card>
            <CardTitle>Filter Chips</CardTitle>
            <div className="mt-4">
              <FilterChips
                chips={[
                  { id: 'win', label: 'Wins' },
                  { id: 'loss', label: 'Losses' },
                  { id: 'breakeven', label: 'Break-even' },
                ]}
                selected={['win']}
                onSelect={(id) => console.log('Selected:', id)}
              />
            </div>
          </Card>
        </div>
      )}

      {/* States & Loading */}
      {selectedTab === 'states' && (
        <div className="space-y-6">
          <Card>
            <CardTitle>Skeleton Loading</CardTitle>
            <div className="mt-4 space-y-3">
              <SkeletonCard lines={3} />
            </div>
          </Card>

          <Card>
            <CardTitle>Progress Bar</CardTitle>
            <div className="mt-4 space-y-4">
              <Progress value={30} label="Backtest Progress" />
              <Progress value={75} label="Data Ingestion" />
              <Progress value={100} label="Complete" />
            </div>
          </Card>

          <Card>
            <CardTitle>Loading States</CardTitle>
            <div className="mt-4">
              <Button
                onClick={() => setLoading(!loading)}
                variant={loading ? 'secondary' : 'primary'}
              >
                {loading ? 'Loading...' : 'Start Process'}
              </Button>
              {loading && (
                <div className="mt-4 text-center">
                  <div
                    className="w-8 h-8 border-3 border-current border-t-transparent rounded-full animate-spin mx-auto"
                    style={{ color: 'var(--color-accent)' }}
                  />
                </div>
              )}
            </div>
          </Card>
        </div>
      )}

      {/* Feedback & Notifications */}
      {selectedTab === 'feedback' && (
        <div className="space-y-6">
          <Card>
            <CardTitle>Success Toast</CardTitle>
            <div className="mt-4">
              <Toast
                type="success"
                title="Strategy executed successfully"
                description="Backtest completed with 15 trades"
              />
            </div>
          </Card>

          <Card>
            <CardTitle>Error Toast</CardTitle>
            <div className="mt-4">
              <Toast
                type="error"
                title="Failed to load data"
                description="Please check your connection"
              />
            </div>
          </Card>

          <Card>
            <CardTitle>Warning Toast</CardTitle>
            <div className="mt-4">
              <Toast
                type="warning"
                title="Insufficient funds"
                description="You need at least $1000 to run this strategy"
              />
            </div>
          </Card>

          <Card>
            <CardTitle>Info Toast</CardTitle>
            <div className="mt-4">
              <Toast
                type="info"
                title="Demo data loaded"
                description="Using synthetic data for demonstration"
              />
            </div>
          </Card>

          <Card>
            <CardTitle>Modal Dialog</CardTitle>
            <div className="mt-4">
              <Button onClick={() => setModalOpen(true)}>Open Modal</Button>
              <Modal
                isOpen={modalOpen}
                onClose={() => setModalOpen(false)}
                title="Confirm Action"
                actions={
                  <>
                    <Button variant="secondary" onClick={() => setModalOpen(false)}>
                      Cancel
                    </Button>
                    <Button onClick={() => setModalOpen(false)}>Confirm</Button>
                  </>
                }
              >
                <p style={{ color: 'var(--color-ink)' }}>
                  Are you sure you want to run this backtest? This may take a few moments.
                </p>
              </Modal>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
