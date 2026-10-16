import { CheckCircle2, Undo2, X } from "lucide-react"
import { useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react"

import { cn } from "@/lib/utils"

import { Button } from "./button"
import { ToastContext, type Toast, type Toasts } from "./toast-context"

/** The toast on screen, and the control that had focus when it appeared, for focus to return to. */
type Shown = { id: number; toast: Toast; returnTo: HTMLElement | null }

/**
 * Shows page-level results, one at a time, at the bottom of the window: an icon, the result, Undo
 * when it can be reversed, and Close. Results reach screen readers through one polite live region,
 * always present so the first result is announced too; the buttons sit outside it, so they are not
 * read out with each result. A toast never takes focus and has no timeout: it stays until it is
 * closed or the next result replaces it. When it closes with focus inside it, by Undo, Close, or
 * Escape, focus returns to the control that had it when the result appeared.
 */
function ToastProvider({ closeLabel, children }: { closeLabel: string; children: ReactNode }) {
  const [shown, setShown] = useState<Shown | null>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const count = useRef(0)
  const toasts = useMemo<Toasts>(
    () => ({
      show: (toast) => {
        const active = document.activeElement
        // A result shown from a toast's own Undo keeps the control the first one would return to.
        const fromToast = Boolean(viewport.current?.contains(active))
        const control = active instanceof HTMLElement ? active : null
        count.current += 1
        const id = count.current
        setShown((previous) => ({ id, toast, returnTo: fromToast ? (previous?.returnTo ?? null) : control }))
      },
    }),
    [],
  )

  function finish(current: Shown, action?: () => void) {
    const focusInside = Boolean(viewport.current?.contains(document.activeElement))
    action?.()
    setShown((latest) => (latest?.id === current.id ? null : latest))
    if (focusInside && current.returnTo?.isConnected) current.returnTo.focus()
  }

  function closeOnEscape(event: KeyboardEvent, current: Shown) {
    if (event.key !== "Escape") return
    event.preventDefault()
    finish(current)
  }

  return (
    <ToastContext.Provider value={toasts}>
      {children}
      <div ref={viewport} className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex justify-end sm:inset-x-auto sm:right-6 sm:bottom-6">
        <div
          className={cn(
            shown
              ? "pointer-events-auto flex w-full max-w-[26rem] items-center gap-3 rounded-xl border border-border bg-background py-3 pr-3 pl-4 text-sm text-foreground shadow-(--menu-shadow)"
              : "sr-only",
          )}
        >
          {shown && <CheckCircle2 aria-hidden="true" className="size-4 shrink-0 text-success-foreground" />}
          <div role="status" aria-live="polite" aria-atomic className="min-w-0 flex-1">
            {shown && <p key={shown.id}>{shown.toast.message}</p>}
          </div>
          {shown?.toast.action && (
            <Button
              variant="outline"
              size="sm"
              className="shrink-0 pointer-coarse:h-11"
              onClick={() => finish(shown, shown.toast.action?.onSelect)}
              onKeyDown={(event) => closeOnEscape(event, shown)}
            >
              <Undo2 aria-hidden="true" />
              {shown.toast.action.label}
            </Button>
          )}
          {shown && (
            <Button
              variant="ghost"
              size="icon"
              className="size-8 shrink-0 pointer-coarse:size-11"
              aria-label={closeLabel}
              title={closeLabel}
              onClick={() => finish(shown)}
              onKeyDown={(event) => closeOnEscape(event, shown)}
            >
              <X aria-hidden="true" />
            </Button>
          )}
        </div>
      </div>
    </ToastContext.Provider>
  )
}

export { ToastProvider }
