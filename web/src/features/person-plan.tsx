import { RefreshCw } from "lucide-react"
import { useRef } from "react"

import { PlanChips } from "@/components/plan-chips"
import { PlanUsage } from "@/components/plan-usage"
import { Button } from "@/components/ui/button"
import { Popover } from "@/components/ui/popover"
import { Skeleton } from "@/components/ui/skeleton"
import { PlanChooser, type ConfirmChange, type PlanChooserProps } from "@/features/plan-change"
import { useI18n } from "@/i18n/provider"
import type { PersonPlanOverview, UserOverview } from "@/lib/api"
import { isAdministrator, personName } from "@/lib/people"
import type { PlanPerson } from "@/lib/plan-assignment"
import { planCardSummary, planUsageRows } from "@/lib/plan-usage"
import { heldPlanChips } from "@/lib/plans"
import type { PeopleCommands } from "@/lib/use-people"
import { usePlanList } from "@/lib/use-plans"

type ChangePopoverProps = Omit<PlanChooserProps, "overview" | "level" | "onCancel"> & {
  open: boolean
  /** It lines up with its control's end edge, as for a control at the end of a row or card. */
  alignEnd?: boolean
  /** The control that opened it, which gets focus back as it closes. */
  returnFocus: () => HTMLElement | null
  /** Escape, Cancel, or a press outside asks to close it. */
  onClose: () => void
}

/**
 * Change plan in a popover beside the control that opened it, for the people selected in
 * Everyone, one person's row, or their page: the Plans are read as it opens, with Try again when
 * they cannot be, then the chooser.
 */
export function ChangePlanPopover({ open, alignEnd, returnFocus, onClose, ...chooser }: ChangePopoverProps) {
  return (
    <Popover
      id={`${chooser.id}-popover`}
      open={open}
      alignEnd={alignEnd}
      aria-labelledby={`${chooser.id}-title`}
      returnFocus={returnFocus}
      onClose={onClose}
      className="plan-change-popover"
    >
      <ChooserWithPlans {...chooser} onCancel={onClose} />
    </Popover>
  )
}

function ChooserWithPlans(props: Omit<PlanChooserProps, "overview" | "level">) {
  const { t } = useI18n()
  const plans = usePlanList()
  if (plans.data) return <PlanChooser {...props} overview={plans.data} level={3} />
  if (plans.isPending) {
    return (
      <div role="status" aria-busy="true" aria-label={t("people.plans.change.loading")}>
        <h3 id={`${props.id}-title`} className="sr-only">
          {t("people.plans.change.loading")}
        </h3>
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  return (
    <div className="plan-assign-error" role="alert">
      <h3 id={`${props.id}-title`}>{t("people.plans.change.loadError")}</h3>
      <Button type="button" variant="outline" size="sm" onClick={() => void plans.refetch()}>
        <RefreshCw aria-hidden="true" />
        {t("people.plans.tryAgain")}
      </Button>
    </div>
  )
}

/**
 * Change plan for one person, as a command on them like their others: open while their Plan is
 * being chosen, waiting while any person command runs, with the refusal of the last change. The
 * change gives the Plan chosen by its key, or the default with none, named as its result says it.
 */
export function PersonPlanPopover({
  person,
  commands,
  returnFocus,
}: {
  person: PlanPerson
  commands: PeopleCommands
  returnFocus: () => HTMLElement | null
}) {
  const refused = commands.errorFor(person)
  const confirm: ConfirmChange = (key, chosen) => {
    const name = chosen?.name ?? null
    commands.send({ person, action: "plan", plan: key === null ? { key, name } : { key, name: name ?? key } })
  }
  return (
    <ChangePlanPopover
      id={`plan-change-${person.id}`}
      open={commands.choosingPlan === person.id}
      alignEnd
      people={[person]}
      pending={commands.busy}
      refusal={refused}
      returnFocus={returnFocus}
      onChoose={() => refused && commands.command.reset()}
      onConfirm={confirm}
      onClose={commands.closePlanChoice}
    />
  )
}

/**
 * A person's Plan card, after Synchronization once any Plan exists: who gave the Plan and when and
 * whether it limits them now, Change plan for anyone but the reader, the Plan's name with its chips,
 * then one meter per limit. What a change did shows here, as their page's status announces it.
 */
export function PersonPlanCard({
  overview,
  plan,
  commands,
  own,
  now,
}: {
  overview: UserOverview
  plan: PersonPlanOverview
  commands: PeopleCommands
  /** The reader's own page, where no Change plan is offered. */
  own: boolean
  now: number
}) {
  const i18n = useI18n()
  const { t } = i18n
  const person = { ...overview.user, plan }
  const name = personName(i18n, person)
  const administrator = isAdministrator(person)
  const change = useRef<HTMLButtonElement>(null)
  const result = commands.planResultFor(person)
  const choosing = commands.choosingPlan === person.id
  return (
    <section className="page-card workflow user-overview-block person-plan-card" aria-labelledby="person-plan-title">
      <div className="person-plan-head">
        <div>
          <h2 id="person-plan-title">{t("people.person.plan.title")}</h2>
          <p className="person-plan-summary">{planCardSummary(i18n, plan, { name, administrator, now })}</p>
        </div>
        {!own && (
          <div className="person-plan-change">
            <Button
              ref={change}
              type="button"
              variant="outline"
              aria-haspopup="dialog"
              aria-expanded={choosing}
              aria-controls={choosing ? `plan-change-${person.id}-popover` : undefined}
              aria-disabled={commands.busy || undefined}
              onClick={() => (choosing ? commands.closePlanChoice() : commands.start({ person, action: "plan" }))}
            >
              {t("people.person.plan.change")}
            </Button>
            <PersonPlanPopover person={person} commands={commands} returnFocus={() => change.current} />
          </div>
        )}
      </div>
      {plan.has && (
        <p className="person-plan-held">
          <span className="person-plan-name">{plan.has.name}</span>
          <PlanChips chips={heldPlanChips(i18n, plan, administrator)} />
        </p>
      )}
      {result !== null && <p className="command-result person-plan-result">{result}</p>}
      {!administrator && plan.basis !== "administrator" && <PlanUsage rows={planUsageRows(i18n, plan, name)} />}
    </section>
  )
}
