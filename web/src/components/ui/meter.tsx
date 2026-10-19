import { cn } from "@/lib/utils"

type MeterName = { "aria-label": string } | { "aria-labelledby": string }

type MeterProps = MeterName & {
  value: number
  max: number
  /** The numbers in words, such as "2 of 1, over the limit"; the meter is never read as a bare number. */
  valueText: string
  /** "over" past an enforced limit: Attention Ochre with diagonal stripes. Neutral otherwise. */
  tone?: "neutral" | "over" | undefined
  className?: string | undefined
}

/** How full the bar is, as a CSS width: a share of the limit, never past it. */
function fillWidth(value: number, max: number): string {
  if (max <= 0) return value > 0 ? "100%" : "0%"
  const share = Math.min(Math.max(value / max, 0), 1)
  return `${Math.round(share * 10_000) / 100}%`
}

/**
 * How much of a limit is in use: a thin track with a neutral fill, which always sits beside its
 * numbers and a chip. Past an enforced limit the fill turns Attention Ochre with stripes, so color
 * is never the only sign. A native `meter`, invisible over the drawn bar, gives it the meter role;
 * it holds its value within the limit, as a meter must, and `valueText` says the real count.
 */
function Meter({ value, max, valueText, tone = "neutral", className, ...name }: MeterProps) {
  // A meter's maximum must exceed its minimum, so a limit of 0 reads as empty or full.
  const bound = max > 0 ? max : 1
  const held = max > 0 ? value : Math.sign(value)
  return (
    <div data-tone={tone} className={cn("relative h-2 w-full", className)}>
      <meter
        min={0}
        max={bound}
        value={Math.min(Math.max(held, 0), bound)}
        aria-valuetext={valueText}
        className="absolute inset-0 m-0 size-full appearance-none opacity-0"
        {...name}
      />
      <span
        aria-hidden="true"
        className="absolute inset-0 overflow-hidden rounded-full bg-muted forced-colors:border forced-colors:border-[CanvasText]"
      >
        <span
          data-meter-fill=""
          className={cn(
            "absolute inset-y-0 left-0 rounded-full bg-muted-foreground forced-colors:bg-[CanvasText]",
            tone === "over" && "bg-(image:--meter-over-fill)",
          )}
          style={{ width: fillWidth(value, max) }}
        />
      </span>
    </div>
  )
}

export { Meter }
