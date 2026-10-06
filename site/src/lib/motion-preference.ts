// The site-wide "Pause animations" control (components/MotionPreference.astro). Decorative loops
// that run longer than five seconds need a way to stop them (WCAG 2.2.2): one press stops every
// loop on the page, the demos included, and the choice is saved like the theme, under the site's
// own key. The device's reduced-motion setting stops the same loops by itself, and then the
// control shows as on.
//
// A stop is applied as `data-motion="paused"` on `<html>`: the stylesheets hold every CSS loop
// under it, and the islands treat it as reduced motion (islands/hooks.ts). Layout.astro's inline
// head script applies a saved choice before first paint, with the same key and value.
export const MOTION_STORAGE_KEY = "calendar-ghost-site-motion"
export const MOTION_PAUSED = "paused"
export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)"
/** What the islands watch: the attribute this module sets on `<html>`. */
export const MOTION_ATTRIBUTE = "data-motion"

type MotionStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">

function browserStorage(): MotionStorage | null {
  if (typeof window === "undefined") return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

/** Whether the visitor saved a stop; anything but the one value means no. */
export function readMotionPaused(storage: MotionStorage | null = browserStorage()): boolean {
  if (!storage) return false
  try {
    return storage.getItem(MOTION_STORAGE_KEY) === MOTION_PAUSED
  } catch {
    return false
  }
}

export function writeMotionPaused(paused: boolean, storage: MotionStorage | null = browserStorage()): boolean {
  if (!storage) return false
  try {
    if (paused) storage.setItem(MOTION_STORAGE_KEY, MOTION_PAUSED)
    else storage.removeItem(MOTION_STORAGE_KEY)
    return true
  } catch {
    return false
  }
}

export function deviceReducesMotion(): boolean {
  return typeof matchMedia === "function" && matchMedia(REDUCED_MOTION_QUERY).matches
}

/** Whether loops are stopped: by the visitor's choice, or by the device. */
export function motionStopped(paused: boolean, reducedMotion: boolean): boolean {
  return paused || reducedMotion
}

/** Sets or clears the page's stop. */
export function applyMotionPaused(
  paused: boolean,
  targetDocument: Document | undefined = typeof document === "undefined" ? undefined : document,
): void {
  if (!targetDocument) return
  if (paused) targetDocument.documentElement.setAttribute(MOTION_ATTRIBUTE, MOTION_PAUSED)
  else targetDocument.documentElement.removeAttribute(MOTION_ATTRIBUTE)
}

/** Whether the page is stopped right now (the attribute, whoever set it). */
export function pagePaused(targetDocument: Document | undefined = typeof document === "undefined" ? undefined : document): boolean {
  return targetDocument?.documentElement.getAttribute(MOTION_ATTRIBUTE) === MOTION_PAUSED
}
