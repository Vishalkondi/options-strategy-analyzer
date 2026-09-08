import type { ReactNode } from 'react'
import { useToast } from '../hooks/useNotifications'
import { Toast } from './advanced'

export function ToastContainer() {
  const { toasts, remove } = useToast()

  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2 pointer-events-none max-w-sm">
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <Toast
            type={toast.type}
            title={toast.title}
            description={toast.description}
            onClose={() => remove(toast.id)}
          />
        </div>
      ))}
    </div>
  )
}

// Context provider for toast notifications
import { createContext, useContext } from 'react'

type ToastContextType = ReturnType<typeof useToast> | null

const ToastContext = createContext<ToastContextType>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const toast = useToast()
  return <ToastContext.Provider value={toast}>{children}</ToastContext.Provider>
}

export function useToastContext() {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToastContext must be used within ToastProvider')
  }
  return context
}
