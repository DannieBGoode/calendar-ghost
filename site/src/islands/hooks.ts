import { useEffect, useRef, useState, type RefObject } from "react"
import { MOTION_ATTRIBUTE, pagePaused, REDUCED_MOTION_QUERY } from "../lib/motion-preference"
import { eyeOffset } from "./motion"

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false)
  useEffect(() => {
    const list = window.matchMedia(query)
    const update = () => setMatches(list.matches)
    update()
    list.addEventListener("change", update)
    return () => list.removeEventListener("change", update)
  }, [query])
  return matches
}

/** False on the server and in the first client render, true once the island has hydrated. */
export function useHydrated(): boolean {
  const [hydrated, setHydrated] = useState(false)
  useEffect(() => setHydrated(true), [])
  return hydrated
}

/** Whether the visitor pressed the site-wide "Pause animations" (lib/motion-preference.ts). */
function usePagePaused(): boolean {
  const [paused, setPaused] = useState(false)
  useEffect(() => {
    const root = document.documentElement
    const update = () => setPaused(pagePaused())
    update()
    const observer = new MutationObserver(update)
    observer.observe(root, { attributes: true, attributeFilter: [MOTION_ATTRIBUTE] })
    return () => observer.disconnect()
  }, [])
  return paused
}

/**
 * Whether nothing should move by itself: the device asks for reduced motion, or the visitor
 * pressed the site-wide "Pause animations". Either way a demo rests on its still state and hides
 * its own pause control, since there is nothing left to pause. False on the server and in the
 * first client render.
 */
export function useReducedMotion(): boolean {
  const reduced = useMediaQuery(REDUCED_MOTION_QUERY)
  const paused = usePagePaused()
  return reduced || paused
}

export function useOnScreen(ref: RefObject<Element | null>): boolean {
  const [onScreen, setOnScreen] = useState(false)
  useEffect(() => {
    const element = ref.current
    if (!element) return
    const observer = new IntersectionObserver(([entry]) => setOnScreen(entry?.isIntersecting ?? false))
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref])
  return onScreen
}

export function usePageVisible(): boolean {
  const [visible, setVisible] = useState(true)
  useEffect(() => {
    const update = () => setVisible(document.visibilityState === "visible")
    update()
    document.addEventListener("visibilitychange", update)
    return () => document.removeEventListener("visibilitychange", update)
  }, [])
  return visible
}

/** Calls `onFrame` with the time since the loop started, on every frame while `active`. */
export function useAnimationFrame(onFrame: (elapsedMs: number) => void, active: boolean): void {
  const callback = useRef(onFrame)
  useEffect(() => {
    callback.current = onFrame
  })
  useEffect(() => {
    if (!active) return
    let frame = 0
    const start = performance.now()
    const tick = (now: number) => {
      callback.current(now - start)
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [active])
}

/** Eye offset toward the pointer for the ghost inside `ref`. Listens only while `active`, so an
 * island off screen does not track the pointer for nothing. */
export function usePointerEyes(ref: RefObject<Element | null>, active = true): { x: number; y: number } {
  const [eyes, setEyes] = useState({ x: 0, y: 0 })
  useEffect(() => {
    if (!active) return
    let frame = 0
    const onMove = (event: PointerEvent) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const box = ref.current?.getBoundingClientRect()
        if (!box) return
        setEyes(eyeOffset(event.clientX - (box.left + box.width / 2), event.clientY - (box.top + box.height / 2)))
      })
    }
    window.addEventListener("pointermove", onMove, { passive: true })
    return () => {
      window.removeEventListener("pointermove", onMove)
      cancelAnimationFrame(frame)
    }
  }, [ref, active])
  return eyes
}
