import type { Messages } from "../i18n"
import { useHydrated, useReducedMotion } from "./hooks"

/**
 * The pause and play control every self-running demo loop carries (WCAG 2.2.2). It exists only
 * where it can do something: not before hydration (without JavaScript nothing loops), and not
 * under reduced motion (nothing moves by itself then).
 */
export function MotionToggle({
  paused,
  onToggle,
  m,
}: {
  paused: boolean
  onToggle: () => void
  m: Messages["motion"]
}) {
  const hydrated = useHydrated()
  const reducedMotion = useReducedMotion()
  return (
    <button type="button" className="motion-toggle" hidden={!hydrated || reducedMotion} onClick={onToggle}>
      <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        {paused ? <path d="M5 3.5v9l7.5-4.5Z" /> : <path d="M4.5 3.5h2.5v9H4.5ZM9 3.5h2.5v9H9Z" />}
      </svg>
      {paused ? m.play : m.pause}
    </button>
  )
}
