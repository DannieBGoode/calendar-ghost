import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * A native radio drawn as the palette's dot: a ring that fills with the lantern color when chosen.
 * It is a `peer`, so the label after it can draw the focus ring around the whole option. Radio
 * Cards and Limit Fields group these by one `name`, so the browser gives them the WAI-ARIA radio
 * group keyboard: Tab stops once, and the arrow keys move the choice.
 */
function Radio({ className, ...props }: Omit<React.ComponentProps<"input">, "type">) {
  return (
    <input
      type="radio"
      className={cn(
        "peer m-0 size-3.5 shrink-0 cursor-pointer appearance-none rounded-full border-[1.5px] border-input bg-background outline-hidden transition-[border-width,border-color] duration-200 checked:border-4 checked:border-primary disabled:cursor-not-allowed aria-disabled:cursor-not-allowed motion-reduce:transition-none forced-colors:checked:border-[Highlight]",
        className,
      )}
      {...props}
    />
  )
}

export { Radio }
