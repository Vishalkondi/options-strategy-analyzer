import type { CSSProperties, ReactNode } from 'react'

export function Card({ children, className = '', style }: { children: ReactNode; className?: string; style?: CSSProperties }) {
  return (
    <div
      className={`rounded-xl border p-5 transition-shadow hover:shadow-[0_12px_30px_rgba(16,42,46,0.09)] ${className}`}
      style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', boxShadow: 'var(--shadow-card)', ...style }}
    >
      {children}
    </div>
  )
}

export function CardTitle({ children }: { children: ReactNode }) {
  return <h3 className="font-display font-semibold text-[15px] mb-1" style={{ color: 'var(--color-ink)' }}>{children}</h3>
}

export function CardSubtitle({ children }: { children: ReactNode }) {
  return <p className="text-[13px] mb-4" style={{ color: 'var(--color-ink-muted)' }}>{children}</p>
}

type ProvenanceKind = 'demo' | 'live' | 'blocked' | 'deferred'

const provenanceStyles: Record<ProvenanceKind, { color: string; bg: string; label: string }> = {
  demo: { color: 'var(--color-warn)', bg: 'var(--color-warn-bg)', label: 'DEMO DATA' },
  live: { color: 'var(--color-profit)', bg: 'var(--color-profit-bg)', label: 'LIVE DATA' },
  replay: { color: 'var(--color-warn)', bg: 'var(--color-warn-bg)', label: 'REPLAY' },
  simulated: { color: 'var(--color-loss)', bg: 'var(--color-loss-bg)', label: 'NOT LIVE' },
  blocked: { color: 'var(--color-blocked)', bg: 'var(--color-blocked-bg)', label: 'BLOCKED' },
  deferred: { color: 'var(--color-ink-muted)', bg: 'var(--color-border)', label: 'DEFERRED' },
}

/** The project's signature element: every card touching numbers declares its data lineage. */
export function ProvenanceTag({ kind }: { kind: ProvenanceKind }) {
  const s = provenanceStyles[kind]
  return (
    <span
      className="font-mono inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium tracking-wider"
      style={{ color: s.color, background: s.bg }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.color }} />
      {s.label}
    </span>
  )
}

export function Pill({ children, tone = 'default' }: { children: ReactNode; tone?: 'default' | 'accent' }) {
  return (
    <span
      className="font-mono inline-block px-2.5 py-1 rounded-md text-[11px] font-medium tracking-wide"
      style={
        tone === 'accent'
          ? { color: 'var(--color-accent-ink)', background: 'var(--color-accent)' }
          : { color: 'var(--color-ink-muted)', background: 'var(--color-border)' }
      }
    >
      {children}
    </span>
  )
}

export function Button({
  children, onClick, variant = 'primary', disabled, type = 'button', className = '',
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'ghost'
  disabled?: boolean
  type?: 'button' | 'submit'
  className?: string
}) {
  const base = 'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-[13px] font-semibold transition-all hover:-translate-y-px active:translate-y-0 disabled:opacity-40 disabled:cursor-not-allowed'
  const styleByVariant: Record<string, React.CSSProperties> = {
    primary: { background: 'var(--color-accent)', color: 'var(--color-accent-ink)' },
    secondary: { background: 'var(--color-surface)', color: 'var(--color-ink)', border: '1px solid var(--color-border-strong)' },
    ghost: { background: 'transparent', color: 'var(--color-ink-muted)' },
  }
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`${base} ${className}`} style={styleByVariant[variant]}>
      {children}
    </button>
  )
}

export function StatBlock({ label, value, mono = true }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider mb-1" style={{ color: 'var(--color-ink-faint)' }}>{label}</div>
      <div className={`text-2xl font-semibold ${mono ? 'font-mono' : 'font-display'}`} style={{ color: 'var(--color-ink)' }}>{value}</div>
    </div>
  )
}

export function PnlValue({ value, size = 'md' }: { value: number | null | undefined; size?: 'sm' | 'md' | 'lg' }) {
  if (value === null || value === undefined) return <span style={{ color: 'var(--color-ink-faint)' }}>—</span>
  const positive = value > 0
  const zero = value === 0
  const color = zero ? 'var(--color-ink-muted)' : positive ? 'var(--color-profit)' : 'var(--color-loss)'
  const sizeCls = size === 'lg' ? 'text-2xl' : size === 'sm' ? 'text-[13px]' : 'text-base'
  const sign = positive ? '+' : ''
  return (
    <span className={`font-mono font-medium ${sizeCls}`} style={{ color }}>
      {sign}{value.toFixed(2)}
    </span>
  )
}

export function EmptyState({ icon, title, description }: { icon?: ReactNode; title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      {icon && <div className="mb-3" style={{ color: 'var(--color-ink-faint)' }}>{icon}</div>}
      <div className="font-display font-semibold text-[15px] mb-1" style={{ color: 'var(--color-ink)' }}>{title}</div>
      {description && <div className="text-[13px] max-w-sm" style={{ color: 'var(--color-ink-muted)' }}>{description}</div>}
    </div>
  )
}

export function BlockedNotice({ title, reasons }: { title: string; reasons: string[] }) {
  return (
    <div
      className="rounded-xl border p-5 flex gap-3"
      style={{ background: 'var(--color-blocked-bg)', borderColor: 'var(--color-blocked)' }}
    >
      <div className="mt-0.5" style={{ color: 'var(--color-blocked)' }}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 9v4m0 4h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
        </svg>
      </div>
      <div>
        <div className="font-display font-semibold text-[14px] mb-1" style={{ color: 'var(--color-ink)' }}>{title}</div>
        <ul className="text-[13px] space-y-0.5" style={{ color: 'var(--color-ink-muted)' }}>
          {reasons.map((r, i) => <li key={i}>• {r}</li>)}
        </ul>
      </div>
    </div>
  )
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className="animate-spin" style={{ color: 'var(--color-accent)' }}>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" fill="none" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
    </svg>
  )
}
