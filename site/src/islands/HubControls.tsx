import { useEffect, useRef, useState } from "react"
import type { Messages } from "../i18n"
import { useHydrated, useReducedMotion } from "./hooks"
import { MotionToggle } from "./MotionToggle"

export type View = "work" | "you"

/** The names of the diagram's own animations (its keyframes in Hero.astro, and hub.css), all
 * prefixed `hc-`. */
const LOOP = /^hc-/

/** Starts the diagram's loop over from the top of a cycle. Only the clock moves: whether it plays
 * stays with CSS (`data-playing`, `data-offscreen`). */
export function replayLoop(figure: Element): void {
  for (const animation of figure.getAnimations?.({ subtree: true }) ?? []) {
    if (LOOP.test((animation as CSSAnimation).animationName ?? "")) animation.currentTime = 0
  }
}

type Props = {
  m: {
    views: Record<View, string>
    viewLabel: string
    motion: Messages["motion"]
    replay: string
  }
}

/**
 * The home hero diagram's controls. Over the whole diagram, centred, the switch: what work sees
 * (Sam's Work calendar) or what Sam sees (Sam's Personal calendar), through `data-view` on the
 * figure. In the diagram's bottom-right corner, a small labelled pair: Pause/Play for its loop
 * (WCAG 2.2.2), through `data-playing`, and Replay, which starts the cycle over. The loop itself
 * is CSS (hub.css); while the figure is off screen it carries `data-offscreen` and holds. Before
 * hydration none of this shows (the figure's own label, "What work sees", stands in for the
 * switch); under reduced motion only the switch does, since nothing moves.
 */
export function HubControls({ m }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [view, setView] = useState<View>("work")
  const [paused, setPaused] = useState(false)
  const [offscreen, setOffscreen] = useState(false)
  const hydrated = useHydrated()
  const reducedMotion = useReducedMotion()
  const figure = () => ref.current?.closest(".hc") ?? null

  useEffect(() => {
    const root = figure()
    if (!root) return
    root.toggleAttribute("data-enhanced", true)
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
  }, [paused, offscreen])

  useEffect(() => {
    figure()?.setAttribute("data-view", view)
  }, [view])

  const replay = () => {
    const root = figure()
    if (!root) return
    replayLoop(root)
    setPaused(false)
  }
  return (
    <div ref={ref} className="hc-controls" hidden={!hydrated}>
      <div className="hc-views" role="group" aria-label={m.viewLabel}>
        {(["work", "you"] as const).map((option) => (
          <button key={option} type="button" className="hc-view" aria-pressed={view === option} onClick={() => setView(option)}>
            {m.views[option]}
          </button>
        ))}
      </div>
      <div className="hc-motion" hidden={reducedMotion}>
        <MotionToggle paused={paused} onToggle={() => setPaused((was) => !was)} m={m.motion} short />
        <button type="button" className="motion-toggle hc-replay" onClick={replay}>
          <svg className="hc-replay-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
          </svg>
          {m.replay}
        </button>
      </div>
    </div>
  )
}
