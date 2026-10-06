import { useEffect, useRef, useState } from "react"
import type { Messages } from "../../i18n"
import { MotionToggle } from "../../islands/MotionToggle"

/**
 * Hero E's one control. The travelling segments are CSS (node-diagram.css) and start at the first
 * paint, so this island only governs them: the pause control (WCAG 2.2.2) sets `data-playing` on
 * the figure, and while the figure is off screen it carries `data-offscreen`, so the loop costs
 * nothing where nobody sees it. Both hold the CSS animations where they are.
 */
export function NodeDiagramControls({ m }: { m: Messages["motion"] }) {
  const ref = useRef<HTMLDivElement>(null)
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    ref.current?.closest(".nd")?.setAttribute("data-playing", String(!paused))
  }, [paused])

  useEffect(() => {
    const figure = ref.current?.closest(".nd")
    if (!figure || typeof IntersectionObserver === "undefined") return
    const observer = new IntersectionObserver(([entry]) => figure.toggleAttribute("data-offscreen", !entry?.isIntersecting))
    observer.observe(figure)
    return () => observer.disconnect()
  }, [])

  return (
    <div ref={ref} className="nd-controls">
      <MotionToggle compact paused={paused} onToggle={() => setPaused((was) => !was)} m={m} />
    </div>
  )
}
