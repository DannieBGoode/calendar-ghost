import { useEffect, useRef, useState } from "react"
import type { Messages } from "../../i18n"
import { useHydrated, useReducedMotion } from "../../islands/hooks"

export type View = "work" | "you"

type Props = {
  m: { views: Record<View, string>; viewLabel: string; motion: Messages["motion"] }
}

/**
 * Hero E4's controls. Over the whole diagram, centred, the switch: what work sees (Sam's Work
 * calendar) or what Sam sees (Sam's Personal calendar), through `data-view` on the figure. In the
 * diagram's bottom-right corner, one quiet Pause/Play for its loop (WCAG 2.2.2), through
 * `data-playing`. The loop itself is CSS (hub-e4.css); while the figure is off screen it carries
 * `data-offscreen` and holds. Before hydration none of this shows (the figure's own label, "What
 * work sees", stands in for the switch); under reduced motion only the switch does, since nothing
 * moves.
 */
export function HubE4Controls({ m }: Props) {
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

  const pauseLabel = paused ? m.motion.play : m.motion.pause
  return (
    <div ref={ref} className="hc-controls" hidden={!hydrated}>
      <div className="hc-views" role="group" aria-label={m.viewLabel}>
        {(["work", "you"] as const).map((option) => (
          <button key={option} type="button" className="hc-view" aria-pressed={view === option} onClick={() => setView(option)}>
            {m.views[option]}
          </button>
        ))}
      </div>
      <button type="button" className="motion-toggle is-compact hc-pause" hidden={reducedMotion} onClick={() => setPaused((was) => !was)} title={pauseLabel}>
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          {paused ? <path d="M5 3.5v9l7.5-4.5Z" /> : <path d="M4.5 3.5h2.5v9H4.5ZM9 3.5h2.5v9H9Z" />}
        </svg>
        <span className="sr-only">{pauseLabel}</span>
      </button>
    </div>
  )
}
