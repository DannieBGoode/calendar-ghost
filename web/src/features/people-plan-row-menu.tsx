import { Copy, Pencil, Star, Trash2, UserPlus } from "lucide-react"
import { useState } from "react"

import { OverflowMenu, type OverflowMenuItem } from "@/components/overflow-menu"
import { useI18n } from "@/i18n/provider"
import type { PlanSummary, PlansOverview } from "@/lib/api"
import { makeDefaultHint, removeRefusal } from "@/lib/plans-catalog"
import type { PlanWorkControls } from "@/lib/use-plan-work"
import { usePlanHolders } from "@/lib/use-plans"

/**
 * A Plan's More actions: Edit and Assign people, which open its panel at Limits and People; Make
 * default, which says whom it moves and who keeps the default they were given; Duplicate, which opens New plan with its limits; and, set
 * apart, Remove. Remove is disabled on the default and on a Plan people have, with why as its
 * description, naming the first three who have it once the menu opens and their names arrive.
 * Every item waits while a Plan command is on its way.
 */
export function PlanRowMenu({
  plan,
  overview,
  work,
  onMakeDefault,
}: {
  plan: PlanSummary
  overview: PlansOverview
  work: PlanWorkControls
  onMakeDefault: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  // Who has the Plan is read only once the menu opens, for Remove's description.
  const [opened, setOpened] = useState(false)
  const holders = usePlanHolders(plan.key, opened && plan.people > 0 && !plan.is_default)
  const refusal = removeRefusal(i18n, plan, holders.data)
  const busy = work.busy
  const items: OverflowMenuItem[] = [
    {
      id: "edit",
      label: t("people.plans.menu.edit"),
      icon: <Pencil aria-hidden="true" />,
      disabled: busy,
      onSelect: () => work.openPanel({ plan: plan.key, tab: "limits" }),
    },
    {
      id: "assign",
      label: t("people.plans.menu.assign"),
      icon: <UserPlus aria-hidden="true" />,
      disabled: busy,
      onSelect: () => work.openPanel({ plan: plan.key, tab: "people" }),
    },
    ...(plan.is_default
      ? []
      : [
          {
            id: "default",
            label: t("people.plans.menu.makeDefault"),
            description: makeDefaultHint(i18n, plan, overview),
            icon: <Star aria-hidden="true" />,
            disabled: busy,
            onSelect: onMakeDefault,
          },
        ]),
    {
      id: "duplicate",
      label: t("people.plans.menu.duplicate"),
      icon: <Copy aria-hidden="true" />,
      disabled: busy,
      onSelect: () => work.openPanel({ plan: null, tab: "limits" }, plan.key),
    },
    {
      id: "remove",
      label: t("people.plans.menu.remove"),
      ...(refusal === null ? {} : { description: refusal }),
      icon: <Trash2 aria-hidden="true" />,
      disabled: busy || refusal !== null,
      separated: true,
      onSelect: () => work.openRemoval(plan.key),
    },
  ]
  return (
    <OverflowMenu label={t("people.plans.menu.label", { name: plan.name })} items={items} onOpen={() => setOpened(true)} />
  )
}
