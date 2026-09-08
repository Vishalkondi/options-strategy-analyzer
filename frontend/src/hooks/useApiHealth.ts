import { useEffect, useState } from 'react'

export type ConnectionStatus = 'connected' | 'connecting' | 'disconnected' | 'error'

interface ConnectionHealth {
  status: ConnectionStatus
  latency?: number
  error?: string
  lastChecked?: Date
}

export function useApiHealth() {
  const [health, setHealth] = useState<ConnectionHealth>({
    status: 'connecting',
  })

  useEffect(() => {
    let isMounted = true
    let interval: number

    const checkHealth = async () => {
      const startTime = performance.now()
      try {
        const response = await fetch('/api/health', {
          signal: AbortSignal.timeout(3000),
        })
        const latency = Math.round(performance.now() - startTime)

        if (isMounted) {
          if (response.ok) {
            setHealth({
              status: 'connected',
              latency,
              lastChecked: new Date(),
            })
          } else {
            setHealth({
              status: 'error',
              error: `HTTP ${response.status}`,
              lastChecked: new Date(),
            })
          }
        }
      } catch (err) {
        if (isMounted) {
          const message = err instanceof Error ? err.message : 'Unknown error'
          setHealth({
            status: 'disconnected',
            error: message,
            lastChecked: new Date(),
          })
        }
      }
    }

    checkHealth()
    interval = window.setInterval(checkHealth, 5000)

    return () => {
      isMounted = false
      clearInterval(interval)
    }
  }, [])

  return health
}
