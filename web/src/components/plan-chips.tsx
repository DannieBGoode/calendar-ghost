import { TriangleAlert } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { PlanChip } from "@/lib/plans"

/**
 * The chips beside a person's Plan: "Default", "Over a limit" in Attention Ochre with its icon
 * ("Would be over", neutral, while Plans are off), and "Not limited" for an administrator. What
 * they are over follows its chip in words for a screen reader, as their page shows it to the eye.
 */
export function PlanChips({ chips }: { chips: readonly PlanChip[] }) {
  return (
    <>
      {chips.map((chip) => (
        <span key={chip.id} className="person-plan-chip-wrap">
          <Badge variant={chip.tone === "attention" ? "attention" : "neutral"} className="person-plan-chip" data-tone={chip.tone === "attention" ? "attention" : undefined}>
            {chip.tone === "attention" && <TriangleAlert aria-hidden="true" />}
            {chip.text}
          </Badge>
          {chip.detail && <span className="sr-only">{chip.detail}</span>}
        </span>
      ))}
    </>
  )
}
