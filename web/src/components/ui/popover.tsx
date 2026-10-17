import * as React from "react"

import { cn } from "@/lib/utils"

const VIEWPORT_MARGIN = 16

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
 * positions it, under its control. As it opens, focus stays where its content put it, such as its
 * title, or moves to the popover itself. Escape, unless a control inside handled it first, and a
 * press outside it ask `onClose` to close it; as it closes with focus inside, or with focus lost
 * because its content went, focus returns to its control.
 */
function Popover({ id, open, onClose, returnFocus, alignEnd = false, className, children, ...name }: PopoverProps) {
  const layer = React.useRef<HTMLDialogElement>(null)
  const close = React.useEffectEvent(() => onClose())
  const control = React.useEffectEvent(() => returnFocus())

  React.useLayoutEffect(() => {
    const element = layer.current
    if (!open || !element) return
    // Slide back inside the window wherever the control sits, so it is never cut off. Each opening
    // is a new element, so it starts where its parent put it.
    const box = element.getBoundingClientRect()
    const viewport = document.documentElement.clientWidth
    if (box.width === 0) return
    const left = Math.min(Math.max(box.left, VIEWPORT_MARGIN), viewport - VIEWPORT_MARGIN - box.width)
    const shift = Math.round(left - box.left)
    if (shift !== 0) element.style.translate = `${shift}px 0`
  }, [open])

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
        "absolute top-[calc(100%+0.375rem)] z-30 m-0 h-auto w-[min(26rem,calc(100vw-2rem))] max-w-none rounded-xl border border-border bg-background p-4 text-left text-foreground shadow-(--menu-shadow) outline-none",
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
