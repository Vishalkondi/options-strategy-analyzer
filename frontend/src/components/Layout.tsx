import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { useTheme } from '../hooks/useTheme'
import { ConnectionBanner } from './ConnectionBanner'

export type Page = 'overview' | 'runner' | 'live' | 'compare' | 'explorer' | 'builder' | 'data'

const NAV: { id: Page; label: string; icon: ReactNode }[] = [
  {
    id: 'overview', label: 'Overview', icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 18V6m0 12h16M7 15l3-3 2 2 5-6" /></svg>
    )
  },
  {
    id: 'runner', label: 'Strategy Runner', icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="9" /><path d="M10 9l5 3-5 3V9Z" fill="currentColor" stroke="none" /></svg>
    )
  },
  {
    id: 'live', label: 'Live Monitor', icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3" /><path d="M12 2v4M12 18v4M2 12h4M18 12h4" /></svg>
    )
  },
  {
    id: 'compare', label: 'Compare Runs', icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M8 3v18M16 3v18M4 8l4-4 4 4M20 16l-4 4-4-4" /></svg>
    )
  },
  {
    id: 'explorer', label: 'Trade Explorer', icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18M9 10v10" /></svg>
    )
  },
  {
    id: 'builder', label: 'Strategy Builder', icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></svg>
    )
  },
  {
    id: 'data', label: 'Data Manager', icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5" /><path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3" /></svg>
    )
  },
]

export function Layout({ page, onNavigate, children }: { page: Page; onNavigate: (p: Page) => void; children: ReactNode }) {
  const { dark, toggle } = useTheme()
  const mainRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0, behavior: 'auto' })
  }, [page])

  return (
    <div className="flex h-screen" style={{ background: 'var(--color-paper)' }}>
      <aside className="app-sidebar w-60 shrink-0 flex flex-col py-6 transition-[width]" style={{ background: 'var(--color-sidebar)' }}>
        <div className="app-brand px-6 mb-8 flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: 'var(--color-accent)', color: 'var(--color-accent-ink)' }}>
            <span className="font-display font-bold text-sm">O</span>
          </div>
          <div className="app-brand-copy">
            <div className="font-display font-bold text-[13px] tracking-[0.16em]" style={{ color: 'var(--color-sidebar-ink)' }}>OSA</div>
            <div className="font-mono text-[9px] tracking-widest" style={{ color: 'var(--color-sidebar-ink-muted)' }}>MARKET LAB</div>
          </div>
        </div>
        <nav className="app-nav flex-1 px-3 space-y-1">
          {NAV.map((item) => {
            const active = item.id === page
            return (
              <button
                key={item.id}
                onClick={() => onNavigate(item.id)}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13.5px] font-medium transition-all text-left hover:translate-x-0.5"
                style={{
                  background: active ? 'var(--color-sidebar-active)' : 'transparent',
                  color: active ? '#FFFFFF' : 'var(--color-sidebar-ink-muted)',
                  borderLeft: active ? '2px solid var(--color-accent)' : '2px solid transparent',
                }}
              >
                {item.icon}
                <span className="app-nav-label">{item.label}</span>
              </button>
            )
          })}
        </nav>
        <div className="app-version px-6 pt-4 text-[11px] font-mono" style={{ color: 'var(--color-sidebar-ink-muted)' }}>
          engine v0.1.0-demo
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header
          className="app-header h-16 shrink-0 flex items-center justify-between px-8 border-b backdrop-blur-sm"
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-paper)' }}
        >
          <div className="flex items-center gap-3">
            <h1 className="app-title font-display font-bold text-[16px]" style={{ color: 'var(--color-ink)' }}>
              Options Strategy Analyzer
            </h1>
            <span
              className="font-mono px-2.5 py-1 rounded-full text-[10px] font-medium uppercase tracking-wider"
              style={{ background: 'var(--color-warn-bg)', color: 'var(--color-warn)' }}
            >
              Phase 1 · Historical backtesting
            </span>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden sm:flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider" style={{ color: 'var(--color-profit)' }}>
              <span className="h-1.5 w-1.5 rounded-full animate-pulse" style={{ background: 'var(--color-profit)' }} />
              Workspace ready
            </div>
            <button
              onClick={toggle}
              aria-label="Toggle dark mode"
              className="w-9 h-9 flex items-center justify-center rounded-lg border transition-all hover:-translate-y-px"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-ink-muted)', background: 'var(--color-surface)' }}
            >
              {dark ? (
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="5" /><path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" /></svg>
              ) : (
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" /></svg>
              )}
            </button>
          </div>
        </header>

        <ConnectionBanner />

        <main ref={mainRef} className="app-main flex-1 overflow-auto px-8 py-6">
          {children}
        </main>
      </div>
    </div>
  )
}
