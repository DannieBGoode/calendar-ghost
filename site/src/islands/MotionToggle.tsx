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
  compact = false,
  short = false,
}: {
  paused: boolean
  onToggle: () => void
  m: Messages["motion"]
  /** A 44px icon button: its words are still its name, for assistive technology and as a tooltip. */
  compact?: boolean
  /** Short words on the button ("Pause", "Play"), as hero E4 shows them; its name stays the full
   * words, which contain the short ones. */
  short?: boolean
}) {
  const hydrated = useHydrated()
  const reducedMotion = useReducedMotion()
  const label = paused ? m.play : m.pause
  return (
    <button
      type="button"
      className={compact ? "motion-toggle is-compact" : "motion-toggle"}
      hidden={!hydrated || reducedMotion}
      onClick={onToggle}
      title={compact ? label : undefined}
      aria-label={short ? label : undefined}
    >
      <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        {paused ? <path d="M5 3.5v9l7.5-4.5Z" /> : <path d="M4.5 3.5h2.5v9H4.5ZM9 3.5h2.5v9H9Z" />}
      </svg>
      {compact ? <span className="sr-only">{label}</span> : short ? (paused ? m.playShort : m.pauseShort) : label}
    </button>
  )
}
