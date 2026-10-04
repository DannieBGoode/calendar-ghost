import { fitsTwoLines, type Box } from "../demo/layout"

export type CardLook = "work" | "personal" | "family" | "busy"

export function EventCard({
  box,
  look,
  title,
  detail,
  className = "",
}: {
  box: Box
  look: CardLook
  title: string
  detail?: string
  className?: string
}) {
  const classes = ["cal-event", `is-${look}`, fitsTwoLines(box) ? "" : "is-short", className]
  return (
    <div
      className={classes.filter(Boolean).join(" ")}
      style={{
        left: `calc(${box.leftPct}% + 4px)`,
        width: `calc(${box.widthPct}% - 8px)`,
        top: box.topPx,
        height: box.heightPx,
      }}
    >
      <span>{title}</span>
      {detail ? <small>{detail}</small> : null}
    </div>
  )
}
