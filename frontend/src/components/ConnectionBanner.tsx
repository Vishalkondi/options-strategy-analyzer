import type { ConnectionStatus } from '../hooks/useApiHealth'
import { useApiHealth } from '../hooks/useApiHealth'

export function ConnectionBanner() {
  const health = useApiHealth()

  if (health.status === 'connected') {
    return null
  }

  const config = {
    connecting: {
      bg: 'var(--color-warn-bg)',
      text: 'var(--color-warn)',
      icon: '⏳',
      title: 'Connecting to backend...',
      description: 'This may take a moment on first load.',
    },
    disconnected: {
      bg: 'var(--color-loss-bg)',
      text: 'var(--color-loss)',
      icon: '⚠️',
      title: 'Backend not running',
      description:
        'Start the backend with: python -m uvicorn server.main:app --reload',
    },
    error: {
      bg: 'var(--color-loss-bg)',
      text: 'var(--color-loss)',
      icon: '❌',
      title: 'Backend error',
      description: health.error || 'Unable to reach backend API',
    },
  } as const

  const current = config[health.status as Exclude<ConnectionStatus, 'connected'>]

  return (
    <div
      className="px-4 py-3 border-b flex items-center gap-3 text-[13px]"
      style={{
        background: current.bg,
        borderColor: current.text,
      }}
    >
      <span className="text-lg">{current.icon}</span>
      <div className="flex-1">
        <div
          className="font-semibold mb-0.5"
          style={{ color: current.text }}
        >
          {current.title}
        </div>
        <div
          className="font-mono text-[12px]"
          style={{ color: current.text, opacity: 0.8 }}
        >
          {current.description}
        </div>
      </div>
      {health.latency && (
        <div
          className="font-mono text-[11px] px-2 py-1 rounded"
          style={{
            background: 'rgba(0,0,0,0.1)',
            color: current.text,
          }}
        >
          {health.latency}ms
        </div>
      )}
    </div>
  )
}
