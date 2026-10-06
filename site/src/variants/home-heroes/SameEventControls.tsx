import { useEffect, useRef, useState } from "react"
import type { Messages } from "../../i18n"
import { useHydrated, useReducedMotion } from "../../islands/hooks"
import { MotionToggle } from "../../islands/MotionToggle"

/** The names of hero D's own sequence animations (same-event.css), all prefixed `se-`. */
const SEQUENCE = /^se-/

/** Hero D's own sequence animations in `figure` (not the ghost's blinking). */
function sequence(figure: Element): Animation[] {
  return (figure.getAnimations?.({ subtree: true }) ?? []).filter((animation) =>
    SEQUENCE.test((animation as CSSAnimation).animationName ?? ""),
  )
}

/** Starts hero D's sequence over from its first frame. */
export function replaySequence(figure: Element): void {
  for (const animation of sequence(figure)) {
    animation.currentTime = 0
    animation.play()
  }
}

/**
 * Holds the sequence where it is, or lets it go on. `data-playing` alone is not enough: once an
 * animation has been started over from script, CSS's `animation-play-state` no longer governs it.
 * A finished animation is left alone, since playing it again would start it over.
 */
export function holdSequence(figure: Element, held: boolean): void {
  for (const animation of sequence(figure)) {
    if (held && animation.playState === "running") animation.pause()
    else if (!held && animation.playState === "paused") animation.play()
  }
}

/**
 * Hero D's two controls. The sequence itself is CSS (same-event.css): it plays once from the first
 * paint, so it needs no JavaScript to start and none to rest. These controls only exist where they
 * can do something (after hydration, and not under reduced motion): Replay runs it again, and the
 * pause control (WCAG 2.2.2) holds it and the ghost's blinking (`data-playing` on the figure, and
 * the sequence's animations themselves).
 */
export function SameEventControls({ m }: { m: { replay: string; motion: Messages["motion"] } }) {
  const ref = useRef<HTMLDivElement>(null)
  const [paused, setPaused] = useState(false)
  const hydrated = useHydrated()
  const reducedMotion = useReducedMotion()

  useEffect(() => {
    const figure = ref.current?.closest(".se")
    if (!figure) return
    figure.setAttribute("data-playing", String(!paused))
    holdSequence(figure, paused)
  }, [paused])

  const replay = () => {
    const figure = ref.current?.closest(".se")
    if (!figure) return
    setPaused(false)
    figure.setAttribute("data-playing", "true")
    replaySequence(figure)
  }

  return (
    <div ref={ref} className="se-controls">
      <button type="button" className="se-replay" hidden={!hydrated || reducedMotion} onClick={replay}>
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
          <path d="M3 3v5h5" />
        </svg>
        {m.replay}
      </button>
      <MotionToggle compact paused={paused} onToggle={() => setPaused((was) => !was)} m={m.motion} />
    </div>
  )
}
