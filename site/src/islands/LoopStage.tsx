import { useRef, useState, type ReactNode } from "react"
import type { Messages } from "../i18n"
import { useHydrated, useOnScreen, usePageVisible } from "./hooks"
import { MotionToggle } from "./MotionToggle"

/**
 * A stage for CSS-animated scenes that loop: it gives them one pause control (WCAG 2.2.2) and
 * tells the stylesheet when to play.
 *
 * - `data-hydrated="true"` once JavaScript runs. Scenes animate only then, so without JavaScript
 *   (where no pause control exists) they rest on their final frame.
 * - `data-playing="false"` while paused, off screen, or in a hidden tab; the stylesheet pauses
 *   every animation inside.
 *
 * Reduced motion is the stylesheet's job (no animation at all), and the control hides itself.
 */
export function LoopStage({
  motion,
  className,
  children,
}: {
  motion: Messages["motion"]
  className?: string
  children?: ReactNode
}) {
  const root = useRef<HTMLDivElement>(null)
  const [paused, setPaused] = useState(false)
  const hydrated = useHydrated()
  const onScreen = useOnScreen(root)
  const pageVisible = usePageVisible()
  const playing = hydrated && onScreen && pageVisible && !paused
  return (
    <div
      ref={root}
      className={className ? `loop-stage ${className}` : "loop-stage"}
      data-hydrated={hydrated ? "true" : "false"}
      data-playing={playing ? "true" : "false"}
    >
      {children}
      <div className="demo-foot">
        <MotionToggle paused={paused} onToggle={() => setPaused((value) => !value)} m={motion} />
      </div>
    </div>
  )
}
