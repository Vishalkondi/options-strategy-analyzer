import { useState } from 'react'
import type { Page } from './components/Layout'
import { Layout } from './components/Layout'
import { OverviewPage } from './pages/OverviewPage'
import { StrategyRunnerPage } from './pages/StrategyRunnerPage'
import { LiveMonitorPage } from './pages/LiveMonitorPage'
import { CompareRunsPage } from './pages/CompareRunsPage'
import { TradeExplorerPage } from './pages/TradeExplorerPage'
import { StrategyBuilderPage } from './pages/StrategyBuilderPage'
import { DataManagerPage } from './pages/DataManagerPage'

export default function App() {
  const [page, setPage] = useState<Page>('overview')

  return (
    <Layout page={page} onNavigate={setPage}>
      {page === 'overview' && <OverviewPage />}
      {page === 'runner' && <StrategyRunnerPage />}
      {page === 'live' && <LiveMonitorPage />}
      {page === 'compare' && <CompareRunsPage />}
      {page === 'explorer' && <TradeExplorerPage />}
      {page === 'builder' && <StrategyBuilderPage />}
      {page === 'data' && <DataManagerPage />}
    </Layout>
  )
}
