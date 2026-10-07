import { useEffect, useRef, useState } from "react"
import type { Messages } from "../i18n"
import { usePageVisible } from "./hooks"
import { MotionToggle } from "./MotionToggle"

/** Controls the decorative provider cluster through the same attributes as the other demos. */
export function CalendarMotion({ m }: { m: Messages["motion"] }) {
  const ref = useRef<HTMLDivElement>(null)
  const [paused, setPaused] = useState(false)
  const [offscreen, setOffscreen] = useState(true)
  const visible = usePageVisible()

  useEffect(() => {
    const root = ref.current?.closest(".calendars")
    if (!root) return
    root.setAttribute("data-enhanced", "")
    const observer = new IntersectionObserver(([entry]) => setOffscreen(!entry?.isIntersecting))
    observer.observe(root)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const root = ref.current?.closest(".calendars")
    root?.setAttribute("data-playing", String(!paused && visible))
    root?.toggleAttribute("data-offscreen", offscreen)
  }, [paused, offscreen, visible])

  return (
    <div ref={ref} className="calendar-motion">
      <MotionToggle paused={paused} onToggle={() => setPaused((value) => !value)} m={m} short />
    </div>
  )
}
