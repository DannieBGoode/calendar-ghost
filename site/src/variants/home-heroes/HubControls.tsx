import { useEffect, useRef, useState } from "react"
import type { Messages } from "../../i18n"
import { useHydrated, useReducedMotion } from "../../islands/hooks"

/** The names of hero E3's own animations (hub.css and its face keyframes), all prefixed `hb-`. */
const RUN = /^hb-/

/** Hero E3's own animations in `figure`. */
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

export type View = "work" | "you"

type Props = {
  m: { views: Record<View, string>; viewLabel: string; replay: string; motion: Messages["motion"] }
}

/**
 * Hero E3's controls, in one row over Work's day. The switch shows Work's day as work sees it
 * (Busy) or as Sam does (the real titles), through `data-view` on the figure. Beside it, Pause and
 * Play (WCAG 2.2.2) and Replay. The run itself is CSS (hub.css): it plays once from the first
 * paint and rests with everything landed, so it needs no JavaScript to start or to rest. While the
 * figure is off screen it carries `data-offscreen` and the run holds. Before hydration none of
 * this shows (the drawing's own label, "What work sees", stands in); under reduced motion only the
 * switch does, since nothing moves.
 */
export function HubControls({ m }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [view, setView] = useState<View>("work")
  const [paused, setPaused] = useState(false)
  const [offscreen, setOffscreen] = useState(false)
  const [ended, setEnded] = useState(false)
  const runs = useRef(0)
  const hydrated = useHydrated()
  const reducedMotion = useReducedMotion()
  const figure = () => ref.current?.closest(".hb") ?? null

  /** Marks the run as ended once every one of its animations has finished. */
  const watch = (root: Element) => {
    const run = (runs.current += 1)
    const animations = runOf(root)
    if (animations.length === 0) return
    Promise.all(animations.map((animation) => animation.finished))
      .then(() => {
        if (run === runs.current) setEnded(true)
      })
      .catch(() => {})
  }

  useEffect(() => {
    const root = figure()
    if (!root) return
    root.toggleAttribute("data-enhanced", true)
    watch(root)
    if (typeof IntersectionObserver === "undefined") return
    const observer = new IntersectionObserver(([entry]) => setOffscreen(!entry?.isIntersecting))
    observer.observe(root)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const root = figure()
    if (!root) return
    root.setAttribute("data-playing", String(!paused))
    root.toggleAttribute("data-offscreen", offscreen)
    holdRun(root, paused || offscreen)
  }, [paused, offscreen])

  useEffect(() => {
    figure()?.setAttribute("data-view", view)
  }, [view])

  const replay = () => {
    const root = figure()
    if (!root) return
    setEnded(false)
    setPaused(false)
    root.setAttribute("data-playing", "true")
    replayRun(root)
    watch(root)
  }

  const pauseLabel = paused ? m.motion.play : m.motion.pause
  return (
    <div ref={ref} className="hb-controls" hidden={!hydrated}>
      <div className="hb-views" role="group" aria-label={m.viewLabel}>
        {(["work", "you"] as const).map((option) => (
          <button key={option} type="button" className="hb-view" aria-pressed={view === option} onClick={() => setView(option)}>
            {m.views[option]}
          </button>
        ))}
      </div>
      <div className="hb-motion" hidden={reducedMotion}>
        <button type="button" className="motion-toggle is-compact" onClick={() => setPaused((was) => !was)} disabled={ended} title={pauseLabel}>
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            {paused ? <path d="M5 3.5v9l7.5-4.5Z" /> : <path d="M4.5 3.5h2.5v9H4.5ZM9 3.5h2.5v9H9Z" />}
          </svg>
          <span className="sr-only">{pauseLabel}</span>
        </button>
        <button type="button" className="motion-toggle is-compact" onClick={replay} title={m.replay}>
          <svg className="hb-replay-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
          </svg>
          <span className="sr-only">{m.replay}</span>
        </button>
      </div>
    </div>
  )
}
