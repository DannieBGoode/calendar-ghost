import { CirclePause } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { YourPlanLink } from "@/components/your-plan-link"
import { useI18n } from "@/i18n/provider"
import { yourPlanPath } from "@/lib/navigation"
import { usePlanHoldStep } from "@/lib/use-own-plan"

/** A hold releases on its own; confirmed exemptions wait only for settlement. */
export function PlanHoldNote() {
  const { t } = useI18n()
  const step = usePlanHoldStep()
  return <p className="rule-note">{t(step === null ? "ruleDetails.hold.pendingRelease" : "ruleDetails.hold.resumes")}</p>
}

/** The same Your plan destination as capacity refusals, retaining native modified-click navigation. */
export function PlanHoldAction() {
  const { t } = useI18n()
  const step = usePlanHoldStep()
  if (step === null) return null
  if (step === "retry") return <YourPlanLink />
  return (
    <Button variant="outline" asChild>
      <a href={yourPlanPath()}>{t("settings.ownPlan.keep.open")}</a>
    </Button>
  )
}

/** Neutral in both the signed-in User's rules and the private Operator Overview. */
export function PlanHoldBadge({ thirdPerson }: { thirdPerson?: boolean | undefined }) {
  const { t } = useI18n()
  return (
    <Badge variant="neutral">
      <CirclePause aria-hidden="true" /> {t(thirdPerson ? "ruleDetails.state.heldTheirPlan" : "ruleDetails.state.heldYourPlan")}
    </Badge>
  )
}
