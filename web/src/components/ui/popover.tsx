import * as React from "react"

import { cn } from "@/lib/utils"

import { useKeptInWindow } from "./keep-in-window"

/** The space between the control and the popover, as its class sets it under the control (0.375rem). */
const GAP = 6
const PLACEMENT = { gap: GAP, sideways: true }

type PopoverProps = {
  id: string
  open: boolean
  /** Escape, or a press outside it and its control, asks to close it. */
  onClose: () => void
  /** The control that opened it, which gets focus back as it closes with focus inside. */
  returnFocus: () => HTMLElement | null
  "aria-labelledby": string
  /** It lines up with its control's end edge rather than its start; it then slides back inside the window. */
  alignEnd?: boolean | undefined
  className?: string
  children: React.ReactNode
}

/**
 * One short choice beside the control that opened it, such as Change plan: a native dialog, shown
 * open rather than modal, that lifts above the page as a menu does but never blocks it. Its parent
 * is its control's positioned wrapper. It opens under the control, or above it when there is more
 * room there, and never past the window's edges, the sticky top bar, or a toast: its height is
 * capped at the room it has, and its content scrolls inside it. As it opens, focus stays where its
 * content put it, such as its chosen option, or moves to the popover itself. Escape, unless a
 * control inside handled it first, and a press outside it ask `onClose` to close it; as it closes
 * with focus inside, or with focus lost because its content went, focus returns to its control.
 */
function Popover({ id, open, onClose, returnFocus, alignEnd = false, className, children, ...name }: PopoverProps) {
  const layer = React.useRef<HTMLDialogElement>(null)
  const close = React.useEffectEvent(() => onClose())
  const control = React.useEffectEvent(() => returnFocus())
  useKeptInWindow(layer, open, PLACEMENT)

  React.useEffect(() => {
    if (!open) return
    const element = layer.current
    if (element && !element.contains(document.activeElement)) element.focus()
    const outside = (event: PointerEvent) => {
      const target = event.target as Node
      if (element?.contains(target) || control()?.contains(target)) return
      close()
    }
    document.addEventListener("pointerdown", outside)
    return () => {
      document.removeEventListener("pointerdown", outside)
      const active = document.activeElement
      if (active === null || active === document.body || element?.contains(active)) control()?.focus({ preventScroll: true })
    }
  }, [open])

  if (!open) return null
  return (
    <dialog
      ref={layer}
      id={id}
      open
      tabIndex={-1}
      className={cn(
        "absolute top-[calc(100%+0.375rem)] z-30 m-0 flex h-auto w-[min(26rem,calc(100vw-2rem))] max-w-none flex-col overflow-y-auto overscroll-contain rounded-xl border border-border bg-background p-4 text-left text-foreground shadow-(--menu-shadow) outline-none",
        alignEnd ? "right-0 left-auto" : "right-auto left-0",
        className,
      )}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || event.defaultPrevented) return
        event.preventDefault()
        onClose()
      }}
      {...name}
    >
      {children}
    </dialog>
  )
}

export { Popover }
