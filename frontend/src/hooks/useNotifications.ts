import { useState, useCallback } from 'react'

export interface ToastMessage {
  id: string
  type: 'success' | 'error' | 'warning' | 'info'
  title: string
  description?: string
}

export function useToast() {
  const [toasts, setToasts] = useState<ToastMessage[]>([])

  const add = useCallback(
    (type: ToastMessage['type'], title: string, description?: string, duration = 4000) => {
      const id = Date.now().toString()
      const toast: ToastMessage = { id, type, title, description }
      setToasts((prev) => [...prev, toast])

      if (duration > 0) {
        setTimeout(() => {
          setToasts((prev) => prev.filter((t) => t.id !== id))
        }, duration)
      }

      return id
    },
    [],
  )

  const remove = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const success = useCallback((title: string, description?: string) => add('success', title, description), [add])
  const error = useCallback((title: string, description?: string) => add('error', title, description), [add])
  const warning = useCallback((title: string, description?: string) => add('warning', title, description), [add])
  const info = useCallback((title: string, description?: string) => add('info', title, description), [add])

  return { toasts, add, remove, success, error, warning, info }
}

export function useModal(initialOpen = false) {
  const [isOpen, setIsOpen] = useState(initialOpen)

  const open = useCallback(() => setIsOpen(true), [])
  const close = useCallback(() => setIsOpen(false), [])
  const toggle = useCallback(() => setIsOpen((prev) => !prev), [])

  return { isOpen, open, close, toggle }
}
