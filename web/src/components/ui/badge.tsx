import { cva, type VariantProps } from "class-variance-authority"
import * as React from "react"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
  {
    variants: {
      variant: {
        healthy: "bg-success-soft text-success-foreground",
        attention: "bg-warning-soft text-warning-foreground",
        stopped: "bg-destructive-soft text-destructive-soft-foreground",
        neutral: "bg-muted text-muted-foreground",
        outline: "border border-border bg-background text-foreground",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
)

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge }
