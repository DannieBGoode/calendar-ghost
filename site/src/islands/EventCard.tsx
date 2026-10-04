import type { CSSProperties } from "react"
import { fitsTwoLines, type Box } from "../demo/layout"

export type CardLook = "work" | "personal" | "family" | "busy"

export function EventCard({
  box,
  phoneBox,
  look,
  title,
  detail,
  className = "",
}: {
  box: Box
  /** Where the event sits on phones, when the week there has another height (see demos.css). */
  phoneBox?: Box
  look: CardLook
  title: string
  detail?: string
  className?: string
}) {
  const shortness = phoneBox
    ? [fitsTwoLines(box) ? "" : "is-short-wide", fitsTwoLines(phoneBox) ? "" : "is-short-phone", "has-phone"]
    : [fitsTwoLines(box) ? "" : "is-short"]
  const classes = ["cal-event", `is-${look}`, ...shortness, className]
  const place = phoneBox
    ? {
        "--top": `${box.topPx}px`,
        "--h": `${box.heightPx}px`,
        "--top-phone": `${phoneBox.topPx}px`,
        "--h-phone": `${phoneBox.heightPx}px`,
      }
    : { top: box.topPx, height: box.heightPx }
  return (
    <div
      className={classes.filter(Boolean).join(" ")}
      style={
        {
          left: `calc(${box.leftPct}% + 4px)`,
          width: `calc(${box.widthPct}% - 8px)`,
          ...place,
        } as CSSProperties
      }
    >
      <span>{title}</span>
      {detail ? <small>{detail}</small> : null}
    </div>
  )
}
