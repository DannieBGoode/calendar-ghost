import * as React from "react"

const VIEWPORT_MARGIN = 16
/**
 * With less room than this on both sides of its control, a layer first scrolls the control up to
 * just under the top bar, which leaves it the most room the page can give under it.
 */
const COMFORTABLE = 240

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

/** The room in that clear part of the window above and below the control's box, `gap` away from it. */
function roomAround(anchor: HTMLElement, gap: number): { above: number; below: number } {
  const clear = clearWindow()
  const box = anchor.getBoundingClientRect()
  return { above: box.top - gap - clear.top, below: clear.bottom - box.bottom - gap }
}

/** Where the layer and anything inside it had scrolled to, so placing it again keeps that. */
function scrolledParts(element: HTMLElement): [HTMLElement, number][] {
  return [element, ...element.querySelectorAll<HTMLElement>("*")]
    .filter((part) => part.scrollTop > 0)
    .map((part) => [part, part.scrollTop])
}

/**
 * Puts the layer under its control, or above it when it does not fit there and there is more room
 * above, and caps its height at the room on that side.
 */
function fit(element: HTMLElement, anchor: HTMLElement, natural: number, gap: number) {
  const room = roomAround(anchor, gap)
  const above = natural > room.below && room.above > room.below
  const space = Math.max(Math.floor(above ? room.above : room.below), 0)
  element.dataset.side = above ? "top" : "bottom"
  element.style.top = above ? "auto" : ""
  element.style.bottom = above ? `calc(100% + ${gap}px)` : ""
  element.style.maxHeight = ""
  delete element.dataset.capped
  if (natural > space) {
    // Capped: its content may keep a smallest size of its own, scrolling beyond that.
    element.style.maxHeight = `${space}px`
    element.dataset.capped = "true"
  }
}

/**
 * Places the layer on the side of its control with room for it, its height capped so it never
 * leaves the window and its content scrolls inside it. On `opening`, a control with little room on
 * both sides is first scrolled up to just under the top bar, as far as the page scrolls.
 */
function placeVertically(element: HTMLElement, anchor: HTMLElement, gap: number, opening: boolean) {
  const scrolled = scrolledParts(element)
  element.style.maxHeight = ""
  delete element.dataset.capped
  const natural = element.getBoundingClientRect().height
  const room = roomAround(anchor, gap)
  if (opening && Math.max(room.above, room.below) < Math.min(natural, COMFORTABLE)) {
    // Folded while the page scrolls, so the page scrolls only as far as its own end.
    element.style.maxHeight = "0px"
    anchor.scrollIntoView({ block: "start" })
  }
  const before = anchor.getBoundingClientRect().top
  fit(element, anchor, natural, gap)
  // A shorter layer can shorten the page, and a page scrolled to its end then moves: fit again.
  if (anchor.getBoundingClientRect().top !== before) fit(element, anchor, natural, gap)
  for (const [part, top] of scrolled) part.scrollTop = top
}

/** Slides the layer back inside the window wherever its control sits, so it is never cut off at a side. */
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
 * Keeps an open layer that floats beside its control, such as a popover or a menu, inside the
 * window: as it opens, as its content changes, and as the page scrolls or the window resizes. Its
 * parent is its control's positioned wrapper, and its class places it `gap` pixels under it; it
 * moves above when there is more room there, below the top bar and above a toast, with its height
 * capped at the room it has. Scrolling inside the layer leaves it where it is. With `sideways`, it
 * also slides back inside the window's sides.
 */
export function useKeptInWindow(
  layer: React.RefObject<HTMLElement | null>,
  open: boolean,
  { gap, sideways }: { gap: number; sideways: boolean },
) {
  React.useLayoutEffect(() => {
    const element = layer.current
    const anchor = element?.parentElement
    if (!open || !element || !anchor) return
    const place = (opening = false) => {
      placeVertically(element, anchor, gap, opening)
      if (sideways) placeHorizontally(element)
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
  }, [layer, open, gap, sideways])
}
