import { useCallback, useRef } from "react"

import { PlanChips } from "@/components/plan-chips"
import { PlanUsage } from "@/components/plan-usage"
import { Button } from "@/components/ui/button"
import { ChooserWithPlans, type SaveChange } from "@/features/plan-change"
import { usePlanChanges, type PlanChanges } from "@/features/use-plan-changes"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PersonPlanOverview, UserOverview } from "@/lib/api"
import { isAdministrator, personName } from "@/lib/people"
import type { PlanPerson } from "@/lib/plan-change"
import { planCardSummary, planUsageRows } from "@/lib/plan-usage"
import { heldPlanChips } from "@/lib/plans"
import type { PeopleCommands } from "@/lib/use-people"
import { usePlanList } from "@/lib/use-plans"

/**
 * Change plan inside a person's Plan card, open while their command is Change plan. Its title is
 * "Change plan", since the page names them. Once the change is made, or it closes, focus returns
 * to Change plan, then the page's toast says what the change did, with Undo.
 */
function PersonPlanChange({
  person,
  commands,
  changes,
  onClosed,
}: {
  person: PlanPerson
  commands: PeopleCommands
  changes: PlanChanges
  /** It closed: what follows once focus is back on Change plan, such as the change's toast. */
  onClosed: (then?: () => void) => void
}) {
  const { t } = useI18n()
  const source = person.id
  const refusal = changes.refusalFor(source)
  const save: SaveChange = (plan, chosen) =>
    changes.change({
      source,
      people: [person],
      plan,
      chosen,
      done: (show) => {
        commands.closePlanChoice()
        onClosed(show)
      },
    })
  return (
    <ChooserWithPlans
      id={`plan-change-${person.id}`}
      title={t("people.plans.change.heading")}
      people={[person]}
      pending={changes.pending}
      refusal={refusal}
      onChoose={() => refusal && changes.forget()}
      onSave={save}
      onCancel={() => {
        changes.forget()
        commands.closePlanChoice()
        onClosed()
      }}
    />
  )
}

/**
 * Once Change plan closes from inside, focus returns to the button that opened it as the button
 * shows again, and then what follows runs, such as the toast, which returns focus there as it
 * closes. Closing it by another command, such as Delete, leaves focus where that command put it.
 */
function useReturnToChange() {
  const returning = useRef<{ then: (() => void) | undefined } | null>(null)
  const button = useCallback((node: HTMLButtonElement | null) => {
    const closed = returning.current
    if (!node || closed === null) return
    returning.current = null
    node.focus()
    closed.then?.()
  }, [])
  const closed = useCallback((then?: () => void) => {
    returning.current = { then }
  }, [])
  return [button, closed] as const
}

/**
 * A person's Plan card, after Synchronization once any Plan exists: who gave the Plan and when and
 * whether it limits them now, Change plan for anyone but the reader, the Plan's name with its chips,
 * then one meter per limit. Change plan opens in the card, in place of the Plan's name, so what
 * they use stays in view beside the choice; what a change did is a toast with Undo.
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
  const changes = usePlanChanges()
  // Read as the card shows, so Change plan opens at once, with focus on the Plan they have.
  usePlanList(!own)
  const choosing = commands.choosingPlan === person.id
  const [changeButton, closed] = useReturnToChange()
  return (
    <section className="page-card workflow user-overview-block person-plan-card" aria-labelledby="person-plan-title">
      <div className="person-plan-head">
        <div>
          <h2 id="person-plan-title">{t("people.person.plan.title")}</h2>
          <p className="person-plan-summary">{planCardSummary(i18n, plan, { name, administrator, now })}</p>
        </div>
        {!own && !choosing && (
          <div className="person-plan-change">
            <Button
              ref={changeButton}
              type="button"
              variant="outline"
              aria-disabled={commands.busy || undefined}
              onClick={() => commands.start({ person, action: "plan" })}
            >
              {t("people.person.plan.change")}
            </Button>
          </div>
        )}
      </div>
      {choosing ? (
        <PersonPlanChange person={person} commands={commands} changes={changes} onClosed={closed} />
      ) : (
        plan.has && (
          <p className="person-plan-held">
            <span className="person-plan-name">{plan.has.name}</span>
            <PlanChips chips={heldPlanChips(i18n, plan, administrator)} />
          </p>
        )
      )}
      {changes.undoRefusal && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, changes.undoRefusal)}
        </p>
      )}
      {!administrator && plan.basis !== "administrator" && <PlanUsage rows={planUsageRows(i18n, plan, name)} />}
    </section>
  )
}
