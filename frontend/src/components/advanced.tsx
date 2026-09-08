import type { ReactNode } from 'react'

export function Skeleton({ width = 'full', height = '20px', className = '' }: { width?: string; height?: string; className?: string }) {
  return (
    <div
      className={`rounded bg-gradient-to-r from-transparent via-gray-300 to-transparent animate-pulse ${className}`}
      style={{ width, height, background: 'var(--color-border)' }}
    />
  )
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div
      className="rounded-xl border p-5 space-y-3"
      style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
    >
      <Skeleton width="40%" height="24px" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? '60%' : '100%'} height="16px" />
      ))}
    </div>
  )
}

export function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, row) => (
        <div key={row} className="flex gap-2">
          {Array.from({ length: cols }).map((_, col) => (
            <Skeleton
              key={`${row}-${col}`}
              width={col === 0 ? '30%' : '100%'}
              height="32px"
            />
          ))}
        </div>
      ))}
    </div>
  )
}

type ToastType = 'success' | 'error' | 'warning' | 'info'

export function Toast({
  type = 'info',
  title,
  description,
  onClose,
}: {
  type?: ToastType
  title: string
  description?: string
  onClose?: () => void
}) {
  const config = {
    success: {
      bg: 'var(--color-profit-bg)',
      text: 'var(--color-profit)',
      icon: '✓',
    },
    error: {
      bg: 'var(--color-loss-bg)',
      text: 'var(--color-loss)',
      icon: '✕',
    },
    warning: {
      bg: 'var(--color-warn-bg)',
      text: 'var(--color-warn)',
      icon: '⚠',
    },
    info: {
      bg: 'var(--color-border)',
      text: 'var(--color-ink-muted)',
      icon: 'ℹ',
    },
  }

  const c = config[type]

  return (
    <div
      className="rounded-lg border p-4 flex items-start gap-3 animate-in fade-in slide-in-from-top-2 duration-300"
      style={{ background: c.bg, borderColor: c.text }}
    >
      <div
        className="flex-shrink-0 w-5 h-5 flex items-center justify-center rounded-full text-[12px] font-bold"
        style={{ background: c.text, color: '#FFF' }}
      >
        {c.icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-[14px]" style={{ color: c.text }}>
          {title}
        </div>
        {description && (
          <div className="text-[13px] mt-0.5" style={{ color: c.text, opacity: 0.85 }}>
            {description}
          </div>
        )}
      </div>
      {onClose && (
        <button
          onClick={onClose}
          className="flex-shrink-0 opacity-60 hover:opacity-100 transition-opacity"
          style={{ color: c.text }}
        >
          ✕
        </button>
      )}
    </div>
  )
}

export function Input({
  label,
  placeholder,
  type = 'text',
  value,
  onChange,
  error,
  disabled,
}: {
  label?: string
  placeholder?: string
  type?: string
  value?: string
  onChange?: (value: string) => void
  error?: string
  disabled?: boolean
}) {
  return (
    <div className="space-y-1.5">
      {label && (
        <label className="block text-[13px] font-medium" style={{ color: 'var(--color-ink)' }}>
          {label}
        </label>
      )}
      <input
        type={type}
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="w-full px-3 py-2 rounded-lg border text-[14px] transition-colors"
        style={{
          background: 'var(--color-surface)',
          borderColor: error ? 'var(--color-loss)' : 'var(--color-border)',
          color: 'var(--color-ink)',
        }}
      />
      {error && (
        <p className="text-[12px]" style={{ color: 'var(--color-loss)' }}>
          {error}
        </p>
      )}
    </div>
  )
}

export function Select({
  label,
  options,
  value,
  onChange,
  error,
  disabled,
}: {
  label?: string
  options: { value: string; label: string }[]
  value?: string
  onChange?: (value: string) => void
  error?: string
  disabled?: boolean
}) {
  return (
    <div className="space-y-1.5">
      {label && (
        <label className="block text-[13px] font-medium" style={{ color: 'var(--color-ink)' }}>
          {label}
        </label>
      )}
      <select
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        disabled={disabled}
        className="w-full px-3 py-2 rounded-lg border text-[14px] transition-colors"
        style={{
          background: 'var(--color-surface)',
          borderColor: error ? 'var(--color-loss)' : 'var(--color-border)',
          color: 'var(--color-ink)',
        }}
      >
        <option value="">Select an option</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {error && (
        <p className="text-[12px]" style={{ color: 'var(--color-loss)' }}>
          {error}
        </p>
      )}
    </div>
  )
}

export function Modal({
  isOpen,
  onClose,
  title,
  children,
  actions,
}: {
  isOpen: boolean
  onClose: () => void
  title: string
  children: ReactNode
  actions?: ReactNode
}) {
  if (!isOpen) return null

  return (
    <>
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40"
        onClick={onClose}
        style={{ animation: 'fadeIn 0.2s ease-out' }}
      />
      <div
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md rounded-xl border"
        style={{
          background: 'var(--color-surface)',
          borderColor: 'var(--color-border)',
          boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
          animation: 'slideUp 0.3s ease-out',
        }}
      >
        <div className="border-b p-4" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-center justify-between">
            <h2 className="font-display font-semibold text-[16px]" style={{ color: 'var(--color-ink)' }}>
              {title}
            </h2>
            <button
              onClick={onClose}
              className="w-8 h-8 flex items-center justify-center rounded hover:opacity-60 transition-opacity"
              style={{ color: 'var(--color-ink-muted)' }}
            >
              ✕
            </button>
          </div>
        </div>
        <div className="p-4 max-h-[60vh] overflow-auto">
          {children}
        </div>
        {actions && (
          <div className="border-t p-4 flex justify-end gap-2" style={{ borderColor: 'var(--color-border)' }}>
            {actions}
          </div>
        )}
      </div>
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes slideUp {
          from { opacity: 0; transform: translate(-50%, calc(-50% + 10px)); }
          to { opacity: 1; transform: translate(-50%, -50%); }
        }
      `}</style>
    </>
  )
}

export function Progress({ value, max = 100, label }: { value: number; max?: number; label?: string }) {
  const percentage = (value / max) * 100

  return (
    <div className="space-y-1">
      {label && (
        <div className="flex items-center justify-between text-[12px]">
          <span style={{ color: 'var(--color-ink)' }}>{label}</span>
          <span style={{ color: 'var(--color-ink-muted)' }}>{Math.round(percentage)}%</span>
        </div>
      )}
      <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-border)' }}>
        <div
          className="h-full transition-all duration-300"
          style={{
            width: `${percentage}%`,
            background: percentage > 80 ? 'var(--color-profit)' : percentage > 50 ? 'var(--color-accent)' : 'var(--color-loss)',
          }}
        />
      </div>
    </div>
  )
}

export function Badge({ children, variant = 'default' }: { children: ReactNode; variant?: 'default' | 'success' | 'error' | 'warning' }) {
  const variants = {
    default: { bg: 'var(--color-border)', text: 'var(--color-ink-muted)' },
    success: { bg: 'var(--color-profit-bg)', text: 'var(--color-profit)' },
    error: { bg: 'var(--color-loss-bg)', text: 'var(--color-loss)' },
    warning: { bg: 'var(--color-warn-bg)', text: 'var(--color-warn)' },
  }
  const v = variants[variant]
  return (
    <span
      className="inline-block px-2.5 py-1 rounded-full text-[11px] font-semibold"
      style={{ background: v.bg, color: v.text }}
    >
      {children}
    </span>
  )
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string }[]
  active: string
  onChange: (id: string) => void
}) {
  return (
    <div
      className="flex gap-1 border-b overflow-x-auto"
      style={{ borderColor: 'var(--color-border)' }}
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className="px-4 py-2.5 text-[13px] font-medium border-b-2 transition-colors whitespace-nowrap"
          style={{
            borderColor: active === tab.id ? 'var(--color-accent)' : 'transparent',
            color: active === tab.id ? 'var(--color-ink)' : 'var(--color-ink-muted)',
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
