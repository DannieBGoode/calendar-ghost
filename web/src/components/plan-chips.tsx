import { TriangleAlert } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { PlanChip } from "@/lib/plans"

/**
 * The chips beside a person's Plan: "Default", "Over a limit" in Attention Ochre with its icon
 * ("Would be over", neutral, while Plans are off), and "Not limited" for an administrator. What
 * they are over follows its chip in words: for a screen reader where the page shows it to the eye
 * elsewhere, as a person's page does with its meters, or, `shown`, on a muted line under the chips,
 * as Everyone's Plan column does.
 */
export function PlanChips({ chips, shown = false }: { chips: readonly PlanChip[]; shown?: boolean }) {
  return (
    <>
      {chips.map((chip) => (
        <span key={chip.id} className="person-plan-chip-wrap">
          <Badge variant={chip.tone === "attention" ? "attention" : "neutral"} className="person-plan-chip" data-tone={chip.tone === "attention" ? "attention" : undefined}>
            {chip.tone === "attention" && <TriangleAlert aria-hidden="true" />}
            {chip.text}
          </Badge>
          {chip.detail && <span className={shown ? "person-plan-detail" : "sr-only"}>{chip.detail}</span>}
        </span>
      ))}
    </>
  )
}
