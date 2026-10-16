import { createContext, useContext, type ReactNode } from "react"

/** A result that belongs to the page rather than a row, with Undo when it can be reversed. */
export type Toast = {
  message: ReactNode
  action?: { label: string; onSelect: () => void } | undefined
}

export type Toasts = {
  /** Shows a result in place of the one shown, if any. It stays until closed or replaced. */
  show: (toast: Toast) => void
}

export const ToastContext = createContext<Toasts | null>(null)

/** Shows page-level results; needs a `ToastProvider` above it. */
export function useToast(): Toasts {
  const toasts = useContext(ToastContext)
  if (!toasts) throw new Error("useToast needs a ToastProvider")
  return toasts
}
