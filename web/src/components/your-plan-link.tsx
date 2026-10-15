import { useI18n } from "@/i18n/provider"
import { yourPlanPath } from "@/lib/navigation"

/**
 * "See your plan", beside a limit's reason. A full navigation, so Settings opens at Your plan
 * wherever the reason was shown.
 */
export function YourPlanLink() {
  const { t } = useI18n()
  return (
    <a className="text-link" href={yourPlanPath()}>
      {t("common.plan.seeYourPlan")}
    </a>
  )
}
