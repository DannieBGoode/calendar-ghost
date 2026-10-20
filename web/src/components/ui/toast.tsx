import { AlertCircle, CheckCircle2, Undo2, X } from "lucide-react"
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react"
import { createPortal } from "react-dom"

import { cn } from "@/lib/utils"

import { Button } from "./button"
import { ToastContext, ToastLayerContext, type Toast, type Toasts } from "./toast-context"

/** The toast on screen, and the control that had focus when it appeared, for focus to return to. */
type Shown = { id: number; toast: Toast; returnTo: HTMLElement | null }

/** How long a result with no Undo stays once nothing holds it. */
const PLAIN_RESULT_MS = 6_000

/** Whether a toast stays until it is closed: one with an action, or a refusal. */
const lasts = (toast: Toast) => toast.action !== undefined || toast.refused === true

/** The space kept between the toast and what the page shows above it, in pixels. */
const CLEARANCE = 8

/**
 * Keeps `--toast-space` on the page while a toast shows: from the foot of the window to the
 * toast's top, plus a little clearance. The page reserves it at its end and in its scroll padding,
 * so the page can scroll clear of the toast and keyboard focus stops above it. An open drawer
 * hosts the toast inside its modal focus scope, above its action footer.
 */
function useReservedSpace(card: RefObject<HTMLElement | null>, showing: boolean, layer: HTMLElement | null) {
  useLayoutEffect(() => {
    const element = card.current
    if (!showing || !element) return
    const root = document.documentElement
    const reserve = () => {
      const space = Math.ceil(window.innerHeight - element.getBoundingClientRect().top) + CLEARANCE
      root.style.setProperty("--toast-space", `${Math.max(space, 0)}px`)
    }
    reserve()
    const observer = new ResizeObserver(reserve)
    observer.observe(element)
    window.addEventListener("resize", reserve)
    return () => {
      observer.disconnect()
      window.removeEventListener("resize", reserve)
      root.style.removeProperty("--toast-space")
    }
  }, [card, showing, layer])
}

/**
 * Whether the pointer is on the toast or focus is in it, either of which holds a result with no
 * Undo on screen. Each resets as the toast closes.
 */
function useHold() {
  const [pointer, setPointer] = useState(false)
  const [focus, setFocus] = useState(false)
  return {
    held: pointer || focus,
    release: () => {
      setPointer(false)
      setFocus(false)
    },
    handlers: {
      onPointerEnter: () => setPointer(true),
      onPointerLeave: () => setPointer(false),
      onFocus: () => setFocus(true),
      onBlur: (event: FocusEvent<HTMLElement>) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocus(false)
      },
    },
  }
}

/**
 * Shows page-level results, one at a time, at the bottom of the window: an icon, the result, Undo
 * when it can be reversed or the one next step it leads to, and Close. Results reach screen
 * readers through one polite live region, always present so the first result is announced too;
 * the buttons sit outside it, so they are not read out with each result. A toast never takes
 * focus. One with Undo, or a next step, stays until it is closed or the next result replaces it,
 * so its action is still there when a keyboard reaches it; one without leaves after six seconds,
 * counted again each time the pointer leaves it or focus leaves it. While one shows, the page
 * reserves its space. When it closes with focus inside it, by its action, Close, or Escape, focus
 * returns to the control that had it when the result appeared. A refusal has an icon of its own,
 * and stays until it is closed, so it is not missed.
 */
function ToastProvider({ closeLabel, children }: { closeLabel: string; children: ReactNode }) {
  const [layer, setLayer] = useState<HTMLElement | null>(null)
  const [shown, setShown] = useState<Shown | null>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const card = useRef<HTMLDivElement>(null)
  const count = useRef(0)
  const hold = useHold()
  useReservedSpace(card, shown !== null, layer)
  const shownId = shown?.id
  const lasting = shown === null || lasts(shown.toast) || hold.held
  useEffect(() => {
    if (lasting) return
    const timer = window.setTimeout(() => setShown(null), PLAIN_RESULT_MS)
    return () => window.clearTimeout(timer)
  }, [lasting, shownId])
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
    hold.release()
    if (focusInside && current.returnTo?.isConnected) current.returnTo.focus()
  }

  function closeOnEscape(event: KeyboardEvent, current: Shown) {
    if (event.key !== "Escape") return
    event.preventDefault()
    finish(current)
  }

  const toastViewport = (
    <div
      ref={viewport}
      className="toast-viewport pointer-events-none fixed inset-x-4 bottom-4 z-50 flex justify-end sm:inset-x-auto sm:right-6 sm:bottom-6"
    >
      <div
        ref={card}
        className={cn(
          shown
            ? "pointer-events-auto flex w-full max-w-[26rem] items-center gap-3 rounded-xl border border-border bg-background py-3 pr-3 pl-4 text-sm text-foreground shadow-(--menu-shadow)"
            : "sr-only",
        )}
        {...hold.handlers}
      >
        {shown && <ToastIcon refused={shown.toast.refused} />}
        <div role="status" aria-live="polite" aria-atomic className="min-w-0 flex-1">
          {shown && <p key={shown.id}>{shown.toast.message}</p>}
        </div>
        {shown?.toast.action && (
          <ToastAction
            action={shown.toast.action}
            onClick={() => finish(shown, shown.toast.action?.onSelect)}
            onKeyDown={(event) => closeOnEscape(event, shown)}
          />
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
  )
  return (
    <ToastContext.Provider value={toasts}>
      <ToastLayerContext.Provider value={setLayer}>{children}</ToastLayerContext.Provider>
      <ToastPlacement layer={layer}>{toastViewport}</ToastPlacement>
    </ToastContext.Provider>
  )
}

/** The toast's icon: a check for a result, or an alert for a refusal. */
function ToastIcon({ refused }: { refused: boolean | undefined }) {
  return refused ? (
    <AlertCircle aria-hidden="true" className="size-4 shrink-0 text-destructive" />
  ) : (
    <CheckCircle2 aria-hidden="true" className="size-4 shrink-0 text-success-foreground" />
  )
}

/** The toast's one action: Undo, with its icon, or the next step it leads to, with its own. */
function ToastAction({
  action,
  onClick,
  onKeyDown,
}: {
  action: NonNullable<Toast["action"]>
  onClick: () => void
  onKeyDown: (event: KeyboardEvent) => void
}) {
  return (
    <Button variant="outline" size="sm" className="shrink-0" onClick={onClick} onKeyDown={onKeyDown}>
      {action.icon ?? <Undo2 aria-hidden="true" />}
      {action.label}
    </Button>
  )
}

export { ToastProvider }

/** Results must share a modal's focus scope while it is open. */
function ToastPlacement({ layer, children }: { layer: HTMLElement | null; children: ReactNode }) {
  return layer ? createPortal(children, layer) : children
}
