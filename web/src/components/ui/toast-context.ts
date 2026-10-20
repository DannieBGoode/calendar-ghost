import { createContext, useContext, type ReactNode } from "react"

/**
 * A result that belongs to the page rather than a row, with Undo when it can be reversed, or the
 * one next step it leads to, such as Assign people for a Plan just added, with an icon of its own
 * in place of Undo's; or why a command, such as Undo, was `refused`.
 */
export type Toast = {
  message: ReactNode
  action?: { label: string; onSelect: () => void; icon?: ReactNode } | undefined
  refused?: boolean
}

export type Toasts = {
  /**
   * Shows a result in place of the one shown, if any. One with an action, such as Undo, or a
   * refusal stays until closed or replaced; any other leaves after a few seconds.
   */
  show: (toast: Toast) => void
}

/** Keeps results and Undo reachable inside an open modal drawer. */
export const ToastLayerContext = createContext<((layer: HTMLElement | null) => void) | null>(null)

export const ToastContext = createContext<Toasts | null>(null)

/** Shows page-level results; needs a `ToastProvider` above it. */
export function useToast(): Toasts {
  const toasts = useContext(ToastContext)
  if (!toasts) throw new Error("useToast needs a ToastProvider")
  return toasts
}
