import { Check, Minus } from "lucide-react"
import * as React from "react"

import { cn } from "@/lib/utils"

type CheckboxProps = Omit<React.ComponentProps<"input">, "type" | "checked" | "defaultChecked" | "onChange" | "ref"> & {
  checked: boolean
  /** Mixed, as a header's box is when only some rows are selected; pressing it selects them all. */
  indeterminate?: boolean
  onCheckedChange: (checked: boolean) => void
  /** A command is on its way: the box keeps focus but ignores changes. */
  pending?: boolean
}

/**
 * A native checkbox, so Tab reaches it and Space toggles it, drawn with the palette's tokens. Its
 * mixed state is the native `indeterminate`, which browsers expose as `aria-checked="mixed"`. The
 * box is small, but the input over it reaches 32 pixels, and 44 on a coarse pointer.
 */
function Checkbox({ checked, indeterminate = false, onCheckedChange, pending = false, className, ...props }: CheckboxProps) {
  return (
    <span className={cn("relative inline-grid size-[1.125rem] shrink-0 place-items-center", className)}>
      <input
        type="checkbox"
        checked={checked}
        ref={(input) => {
          if (input) input.indeterminate = indeterminate
        }}
        aria-disabled={pending || undefined}
        className="peer absolute -inset-[0.4375rem] z-[1] m-0 cursor-pointer appearance-none opacity-0 aria-disabled:cursor-not-allowed pointer-coarse:-inset-[0.8125rem]"
        onChange={(event) => {
          if (!pending) onCheckedChange(event.target.checked)
        }}
        {...props}
      />
      <span
        aria-hidden="true"
        className="pointer-events-none grid size-full place-items-center rounded-[0.3125rem] border-[1.5px] border-input bg-background text-primary-foreground transition-[background-color,border-color,box-shadow] duration-200 peer-checked:border-primary peer-checked:bg-primary peer-indeterminate:border-primary peer-indeterminate:bg-primary peer-focus-visible:ring-[3px] peer-focus-visible:ring-ring/90 peer-focus-visible:ring-offset-1 peer-focus-visible:ring-offset-background peer-aria-disabled:opacity-60 forced-colors:text-[CanvasText] [&>svg]:size-3.5 [&>svg]:stroke-3"
      >
        {indeterminate ? <Minus /> : checked ? <Check /> : null}
      </span>
    </span>
  )
}

export { Checkbox }
