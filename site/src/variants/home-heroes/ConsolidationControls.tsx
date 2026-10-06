import { useEffect, useRef, useState } from "react"
import type { Messages } from "../../i18n"
import { useHydrated, useReducedMotion } from "../../islands/hooks"

/** The names of hero E2's own animations (consolidation.css), all prefixed `cn-`. */
const RUN = /^cn-/

/** Hero E2's own animations in `figure`. */
export function runOf(figure: Element): Animation[] {
  return (figure.getAnimations?.({ subtree: true }) ?? []).filter((animation) => RUN.test((animation as CSSAnimation).animationName ?? ""))
}

/** Starts the run over from its first frame. */
export function replayRun(figure: Element): void {
  for (const animation of runOf(figure)) {
    animation.currentTime = 0
    animation.play()
  }
}

/**
 * Holds the run where it is, or lets it go on. `data-playing` alone is not enough: once an
 * animation has been started over from script, CSS's `animation-play-state` no longer governs it.
 * A finished animation is left alone, since playing it again would start it over.
 */
export function holdRun(figure: Element, held: boolean): void {
  for (const animation of runOf(figure)) {
    if (held && animation.playState === "running") animation.pause()
    else if (!held && animation.playState === "paused") animation.play()
  }
}

type Props = { m: { replay: string; motion: Messages["motion"] } }

/**
 * Hero E2's one control, small in the diagram's corner. The run itself is CSS
 * (consolidation.css): it plays once from the first paint and rests on the full Work column, so it
 * needs no JavaScript to start or to rest. While it runs, the control pauses and plays it
 * (WCAG 2.2.2); once it has rested, the same control replays it. While the figure is off screen it
 * carries `data-offscreen` and the run holds, so nobody misses it. The control exists only where
 * it can do something: after hydration, and not under reduced motion.
 */
export function ConsolidationControls({ m }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [paused, setPaused] = useState(false)
  const [offscreen, setOffscreen] = useState(false)
  const [ended, setEnded] = useState(false)
  const runs = useRef(0)
  const hydrated = useHydrated()
  const reducedMotion = useReducedMotion()

  /** Marks the run as ended once every one of its animations has finished. */
  const watch = (figure: Element) => {
    const run = (runs.current += 1)
    const animations = runOf(figure)
    if (animations.length === 0) return
    Promise.all(animations.map((animation) => animation.finished))
      .then(() => {
        if (run === runs.current) setEnded(true)
      })
      .catch(() => {})
  }

  useEffect(() => {
    const figure = ref.current?.closest(".cn")
    if (!figure) return
    watch(figure)
    if (typeof IntersectionObserver === "undefined") return
    const observer = new IntersectionObserver(([entry]) => setOffscreen(!entry?.isIntersecting))
    observer.observe(figure)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const figure = ref.current?.closest(".cn")
    if (!figure) return
    figure.setAttribute("data-playing", String(!paused))
    figure.toggleAttribute("data-offscreen", offscreen)
    holdRun(figure, paused || offscreen)
  }, [paused, offscreen])

  const onClick = () => {
    if (!ended) {
      setPaused((was) => !was)
      return
    }
    const figure = ref.current?.closest(".cn")
    if (!figure) return
    setEnded(false)
    setPaused(false)
    figure.setAttribute("data-playing", "true")
    replayRun(figure)
    watch(figure)
  }

  const label = ended ? m.replay : paused ? m.motion.play : m.motion.pause
  return (
    <div ref={ref} className="cn-controls">
      <button type="button" className="motion-toggle is-compact" hidden={!hydrated || reducedMotion} onClick={onClick} title={label}>
        {ended ? (
          <svg className="cn-replay-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
          </svg>
        ) : (
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            {paused ? <path d="M5 3.5v9l7.5-4.5Z" /> : <path d="M4.5 3.5h2.5v9H4.5ZM9 3.5h2.5v9H9Z" />}
          </svg>
        )}
        <span className="sr-only">{label}</span>
      </button>
    </div>
  )
}
