import type { ReactNode } from "react"

/** A Monday-to-Friday frame: day names on top and a dashed line between days. */
export function WeekGrid({
  days,
  children,
  className = "",
}: {
  days: readonly string[]
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`week ${className}`.trim()}>
      <div className="week-days" aria-hidden="true">
        {days.map((day) => (
          <span key={day}>{day}</span>
        ))}
      </div>
      <div className="week-columns" aria-hidden="true">
        {days.map((day) => (
          <span key={day} />
        ))}
      </div>
      {children}
    </div>
  )
}
