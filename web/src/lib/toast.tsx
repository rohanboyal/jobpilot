import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { CheckCircle2, AlertTriangle, Info, X, XCircle } from 'lucide-react'
import { clsx } from 'clsx'

export type ToastKind = 'success' | 'error' | 'info' | 'warning'
export interface Toast { id: number; kind: ToastKind; title: string; detail?: string }

interface Ctx {
  push: (t: Omit<Toast, 'id'>) => void
  success: (title: string, detail?: string) => void
  error: (title: string, detail?: string) => void
  info: (title: string, detail?: string) => void
}

const ToastCtx = createContext<Ctx | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const seq = useRef(1)

  const dismiss = useCallback((id: number) => setToasts((ts) => ts.filter((t) => t.id !== id)), [])
  const push = useCallback((t: Omit<Toast, 'id'>) => {
    const id = seq.current++
    setToasts((ts) => [...ts.slice(-4), { ...t, id }])
    window.setTimeout(() => dismiss(id), t.kind === 'error' ? 7000 : 4000)
  }, [dismiss])

  const value = useMemo<Ctx>(() => ({
    push,
    success: (title, detail) => push({ kind: 'success', title, detail }),
    error: (title, detail) => push({ kind: 'error', title, detail }),
    info: (title, detail) => push({ kind: 'info', title, detail }),
  }), [push])

  const icons = { success: CheckCircle2, error: XCircle, info: Info, warning: AlertTriangle }
  const colors = { success: 'text-good-ink', error: 'text-bad-ink', info: 'text-accent-ink', warning: 'text-warn-ink' }

  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-[100] flex w-[360px] max-w-[calc(100vw-32px)] flex-col gap-2">
        {toasts.map((t) => {
          const Icon = icons[t.kind]
          return (
            <div key={t.id} className="toast-in card flex items-start gap-3 p-3 shadow-[var(--shadow)]">
              <Icon size={18} className={clsx('mt-0.5 shrink-0', colors[t.kind])} />
              <div className="min-w-0 flex-1">
                <div className="font-medium">{t.title}</div>
                {t.detail && <div className="mt-0.5 break-words text-xs text-ink-2">{t.detail}</div>}
              </div>
              <button onClick={() => dismiss(t.id)} className="rounded p-1 text-muted hover:bg-surface-2" aria-label="Dismiss">
                <X size={14} />
              </button>
            </div>
          )
        })}
      </div>
    </ToastCtx.Provider>
  )
}

export function useToast(): Ctx {
  const ctx = useContext(ToastCtx)
  if (!ctx) throw new Error('useToast outside ToastProvider')
  return ctx
}
