import * as React from "react"

import { cn } from "@/lib/utils"

/** A switch is named by its own label or by the heading it switches, never by its state text. */
type SwitchName = { "aria-label": string } | { "aria-labelledby": string }

type SwitchProps = Omit<React.ComponentProps<"button">, "type" | "role" | "onClick" | "children" | "aria-checked"> &
  SwitchName & {
    checked: boolean
    onCheckedChange: (checked: boolean) => void
    /** The state as words beside the track ("On", "Off"), so it never relies on the thumb alone. */
    stateLabels: { on: string; off: string }
    /** The last change is on its way: the switch keeps focus but ignores presses. */
    pending?: boolean
  }

/**
 * Turns a mode on or off at once, following the WAI-ARIA switch pattern: a native button, so Tab
 * reaches it and Enter or Space presses it, with its state in `aria-checked`. Its state also shows
 * as text beside the track; both words keep their place, so pressing it never moves the track.
 */
function Switch({ checked, onCheckedChange, stateLabels, pending = false, className, ...props }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-disabled={pending || undefined}
      className={cn(
        "group inline-flex min-h-10 shrink-0 items-center gap-3 rounded-full border border-border bg-background py-1 pr-1 pl-3.5 text-sm font-semibold text-foreground outline-hidden transition-[background-color,box-shadow] duration-200 hover:bg-muted focus-visible:ring-[3px] focus-visible:ring-ring/90 focus-visible:ring-offset-2 focus-visible:ring-offset-background aria-disabled:cursor-not-allowed pointer-coarse:min-h-11",
        className,
      )}
      onClick={() => {
        if (!pending) onCheckedChange(!checked)
      }}
      {...props}
    >
      <span aria-hidden="true" className="grid">
        <span data-state-label="on" className={cn("[grid-area:1/1]", !checked && "invisible")}>
          {stateLabels.on}
        </span>
        <span data-state-label="off" className={cn("[grid-area:1/1]", checked && "invisible")}>
          {stateLabels.off}
        </span>
      </span>
      <span
        aria-hidden="true"
        className="inline-flex h-7 w-13 shrink-0 items-center rounded-full border border-input bg-muted p-[3px] transition-colors duration-200 group-aria-checked:border-primary group-aria-checked:bg-primary motion-reduce:transition-none"
      >
        <span className="size-[1.3125rem] rounded-full bg-muted-foreground transition-transform duration-200 ease-[var(--ease-out)] group-aria-checked:translate-x-6 group-aria-checked:bg-primary-foreground motion-reduce:transition-none forced-colors:bg-[ButtonText]" />
      </span>
    </button>
  )
}

export { Switch }
