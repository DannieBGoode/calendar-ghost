import * as React from "react"

import { cn } from "@/lib/utils"

const VIEWPORT_MARGIN = 16
/** The space between the control and the popover, as its class sets it under the control (0.375rem). */
const GAP = 6
/**
 * With less room than this on both sides of its control, it first scrolls the control up to just
 * under the top bar, which leaves it the most room the page can give under it.
 */
const COMFORTABLE = 240

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
 * The part of the window the page keeps clear, inside a margin: below the sticky top bar and above
 * a toast, which the page's scroll padding marks.
 */
function clearWindow(): { top: number; bottom: number } {
  const page = getComputedStyle(document.documentElement)
  return {
    top: (Number.parseFloat(page.scrollPaddingTop) || 0) + VIEWPORT_MARGIN,
    bottom: window.innerHeight - (Number.parseFloat(page.scrollPaddingBottom) || 0) - VIEWPORT_MARGIN,
  }
}

/** The room in that clear part of the window above and below the control's box. */
function roomAround(anchor: HTMLElement): { above: number; below: number } {
  const clear = clearWindow()
  const box = anchor.getBoundingClientRect()
  return { above: box.top - GAP - clear.top, below: clear.bottom - box.bottom - GAP }
}

/** Where the popover and anything inside it had scrolled to, so placing it again keeps that. */
function scrolledParts(element: HTMLElement): [HTMLElement, number][] {
  return [element, ...element.querySelectorAll<HTMLElement>("*")]
    .filter((part) => part.scrollTop > 0)
    .map((part) => [part, part.scrollTop])
}

/**
 * Puts the popover under its control, or above it when it does not fit there and there is more
 * room above, and caps its height at the room on that side.
 */
function fit(element: HTMLElement, anchor: HTMLElement, natural: number) {
  const room = roomAround(anchor)
  const above = natural > room.below && room.above > room.below
  const space = Math.max(Math.floor(above ? room.above : room.below), 0)
  element.dataset.side = above ? "top" : "bottom"
  element.style.top = above ? "auto" : ""
  element.style.bottom = above ? `calc(100% + ${GAP}px)` : ""
  element.style.maxHeight = ""
  delete element.dataset.capped
  if (natural > space) {
    // Capped: its content may keep a smallest size of its own, scrolling beyond that.
    element.style.maxHeight = `${space}px`
    element.dataset.capped = "true"
  }
}

/**
 * Places the popover on the side of its control with room for it, its height capped so it never
 * leaves the window and its content scrolls inside it. On `opening`, a control with little room
 * on both sides is first scrolled up to just under the top bar, as far as the page scrolls.
 */
function placeVertically(element: HTMLElement, anchor: HTMLElement, opening: boolean) {
  const scrolled = scrolledParts(element)
  element.style.maxHeight = ""
  delete element.dataset.capped
  const natural = element.getBoundingClientRect().height
  const room = roomAround(anchor)
  if (opening && Math.max(room.above, room.below) < Math.min(natural, COMFORTABLE)) {
    // Folded while the page scrolls, so the page scrolls only as far as its own end.
    element.style.maxHeight = "0px"
    anchor.scrollIntoView({ block: "start" })
  }
  const before = anchor.getBoundingClientRect().top
  fit(element, anchor, natural)
  // A shorter popover can shorten the page, and a page scrolled to its end then moves: fit again.
  if (anchor.getBoundingClientRect().top !== before) fit(element, anchor, natural)
  for (const [part, top] of scrolled) part.scrollTop = top
}

/** Slides the popover back inside the window wherever its control sits, so it is never cut off at a side. */
function placeHorizontally(element: HTMLElement) {
  element.style.translate = ""
  const box = element.getBoundingClientRect()
  if (box.width === 0) return
  const viewport = document.documentElement.clientWidth
  const left = Math.min(Math.max(box.left, VIEWPORT_MARGIN), viewport - VIEWPORT_MARGIN - box.width)
  const shift = Math.round(left - box.left)
  if (shift !== 0) element.style.translate = `${shift}px 0`
}

/**
 * Keeps an open popover inside the window as it opens, as its content changes, and as the page
 * scrolls or the window resizes; scrolling inside the popover leaves it where it is.
 */
function useKeptInWindow(layer: React.RefObject<HTMLDialogElement | null>, open: boolean) {
  React.useLayoutEffect(() => {
    const element = layer.current
    const anchor = element?.parentElement
    if (!open || !element || !anchor) return
    const place = (opening = false) => {
      placeVertically(element, anchor, opening)
      placeHorizontally(element)
    }
    place(true)
    let frame = 0
    const later = (event: Event) => {
      if (event.target instanceof Node && element.contains(event.target)) return
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => place())
    }
    const changed = new MutationObserver(() => place())
    changed.observe(element, { childList: true, subtree: true, characterData: true })
    window.addEventListener("resize", later)
    window.addEventListener("scroll", later, true)
    return () => {
      cancelAnimationFrame(frame)
      changed.disconnect()
      window.removeEventListener("resize", later)
      window.removeEventListener("scroll", later, true)
    }
  }, [layer, open])
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
  useKeptInWindow(layer, open)

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
