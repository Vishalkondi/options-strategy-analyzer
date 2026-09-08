import type { ReactNode } from 'react'

// Data Table component with sorting, filtering, and pagination
export function DataTable({
  columns,
  data,
  onRowClick,
  isLoading,
  emptyMessage = 'No data available',
}: {
  columns: { key: string; label: string; width?: string; render?: (value: any) => ReactNode }[]
  data: any[]
  onRowClick?: (row: any) => void
  isLoading?: boolean
  emptyMessage?: string
}) {
  if (isLoading) {
    return (
      <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--color-border)' }}>
        <table className="w-full text-[13px]">
          <thead style={{ background: 'var(--color-border)', borderBottom: '1px solid var(--color-border)' }}>
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className="px-4 py-3 text-left font-semibold"
                  style={{ color: 'var(--color-ink-muted)' }}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[1, 2, 3, 4, 5].map((i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--color-border)' }}>
                {columns.map((col) => (
                  <td key={`${i}-${col.key}`} className="px-4 py-3">
                    <div
                      className="h-4 rounded bg-gradient-to-r from-gray-200 to-gray-300 animate-pulse"
                      style={{ width: `${Math.random() * 40 + 40}%` }}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  if (data.length === 0) {
    return (
      <div
        className="rounded-lg border p-8 text-center"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        <div style={{ color: 'var(--color-ink-muted)' }}>{emptyMessage}</div>
      </div>
    )
  }

  return (
    <div
      className="rounded-lg border overflow-x-auto"
      style={{ borderColor: 'var(--color-border)' }}
    >
      <table className="w-full text-[13px]">
        <thead>
          <tr style={{ background: 'var(--color-border)', borderBottom: '1px solid var(--color-border)' }}>
            {columns.map((col) => (
              <th
                key={col.key}
                className="px-4 py-3 text-left font-semibold"
                style={{ color: 'var(--color-ink-muted)', width: col.width }}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, idx) => (
            <tr
              key={idx}
              onClick={() => onRowClick?.(row)}
              className={onRowClick ? 'cursor-pointer hover:opacity-75 transition-opacity' : ''}
              style={{
                borderBottom: '1px solid var(--color-border)',
                background: idx % 2 === 0 ? 'transparent' : 'var(--color-border)',
              }}
            >
              {columns.map((col) => (
                <td key={`${idx}-${col.key}`} className="px-4 py-3" style={{ color: 'var(--color-ink)' }}>
                  {col.render ? col.render(row[col.key]) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Pagination component
export function Pagination({
  currentPage,
  totalPages,
  onPageChange,
}: {
  currentPage: number
  totalPages: number
  onPageChange: (page: number) => void
}) {
  return (
    <div className="flex items-center justify-center gap-2 py-4">
      <button
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage === 1}
        className="px-3 py-2 rounded-lg border text-[13px] font-medium transition-all disabled:opacity-40"
        style={{
          borderColor: 'var(--color-border)',
          color: 'var(--color-ink-muted)',
          background: 'var(--color-surface)',
        }}
      >
        ← Previous
      </button>

      <div className="flex gap-1">
        {Array.from({ length: Math.min(5, totalPages) }).map((_, i) => {
          let page = i + 1
          if (totalPages > 5 && currentPage > 3) {
            page = currentPage - 2 + i
          }
          return (
            <button
              key={page}
              onClick={() => onPageChange(page)}
              className="w-8 h-8 rounded-lg border text-[13px] font-medium transition-all"
              style={{
                borderColor: currentPage === page ? 'var(--color-accent)' : 'var(--color-border)',
                background: currentPage === page ? 'var(--color-accent)' : 'transparent',
                color: currentPage === page ? 'var(--color-accent-ink)' : 'var(--color-ink-muted)',
              }}
            >
              {page}
            </button>
          )
        })}
      </div>

      <button
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage === totalPages}
        className="px-3 py-2 rounded-lg border text-[13px] font-medium transition-all disabled:opacity-40"
        style={{
          borderColor: 'var(--color-border)',
          color: 'var(--color-ink-muted)',
          background: 'var(--color-surface)',
        }}
      >
        Next →
      </button>
    </div>
  )
}

// Filter chip group
export function FilterChips({
  chips,
  selected,
  onSelect,
}: {
  chips: { id: string; label: string }[]
  selected: string[]
  onSelect: (id: string) => void
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {chips.map((chip) => {
        const isSelected = selected.includes(chip.id)
        return (
          <button
            key={chip.id}
            onClick={() => onSelect(chip.id)}
            className="px-3 py-1.5 rounded-full text-[12px] font-medium transition-all"
            style={{
              background: isSelected ? 'var(--color-accent)' : 'var(--color-border)',
              color: isSelected ? 'var(--color-accent-ink)' : 'var(--color-ink-muted)',
              border: `1px solid ${isSelected ? 'var(--color-accent)' : 'var(--color-border)'}`,
            }}
          >
            {chip.label}
          </button>
        )
      })}
    </div>
  )
}

// Expandable row
export function ExpandableRow({
  summary,
  details,
  isExpanded,
  onToggle,
}: {
  summary: ReactNode
  details: ReactNode
  isExpanded: boolean
  onToggle: () => void
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        className="cursor-pointer hover:opacity-75 transition-opacity"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        <td className="px-4 py-3" colSpan={10}>
          <div className="flex items-center gap-2">
            <span
              className="transform transition-transform"
              style={{
                transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
                color: 'var(--color-ink-muted)',
              }}
            >
              ▶
            </span>
            {summary}
          </div>
        </td>
      </tr>
      {isExpanded && (
        <tr style={{ background: 'var(--color-border)', borderBottom: '1px solid var(--color-border)' }}>
          <td colSpan={10} className="px-4 py-3">
            {details}
          </td>
        </tr>
      )}
    </>
  )
}
