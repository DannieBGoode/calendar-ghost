import { ArrowRight, RefreshCw, TriangleAlert } from "lucide-react"
import { useRef, useState, type MouseEvent } from "react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { PlanChange } from "@/features/plan-change"
import type { ShowPeople } from "@/features/people-plans-status"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { PersonRow, PlanAssignments, PlanSummary, PlansOverview } from "@/lib/api"
import { appPathForPerson, isPlainLeftClick, type OpenPerson } from "@/lib/navigation"
import { personName } from "@/lib/people"
import { peoplePath } from "@/lib/people-query"
import { wouldBeOver } from "@/lib/plan-assignment"
import { overLimitText } from "@/lib/plans"
import { usePlanPeople, type PlanCommands } from "@/lib/use-plans"

/** What the list says of someone who has the Plan, and whether it takes the attention tone. */
function holderState(i18n: I18n, person: PersonRow, enabled: boolean): { text: string; attention: boolean } {
  if (person.role === "installation_administrator") return { text: i18n.t("people.plans.holders.neverLimited"), attention: false }
  const over = person.plan?.over ?? []
  if (over.length === 0) return { text: i18n.t("people.plans.holders.within"), attention: false }
  // While Plans are off nothing is enforced, so it is what they would be over.
  if (!enabled) return { text: wouldBeOver(i18n, over) ?? "", attention: false }
  return { text: i18n.format.list(over.map((limit) => overLimitText(i18n, limit))), attention: true }
}

type HoldersProps = {
  plan: PlanSummary
  overview: PlansOverview
  assign: PlanCommands["assign"]
  /** Someone's plan was changed from the list: what it did, and the words its result says. */
  onChanged: (answer: PlanAssignments, message: string) => void
  onOpenPerson: OpenPerson
  onShowPeople: ShowPeople
}

/**
 * Who has the Plan now, under Assign people in its panel: each person by email, a link to their
 * page, with what they have more of than it allows, or that they are within every limit, and
 * Change plan, which opens a chooser under them. "Show in Everyone" lists them all there. Once a
 * change is made, focus moves to the list's heading, as the person leaves it.
 */
export function PlanHolders({ plan, overview, assign, onChanged, onOpenPerson, onShowPeople }: HoldersProps) {
  const i18n = useI18n()
  const { t } = i18n
  const holders = usePlanPeople(plan.key)
  const [changing, setChanging] = useState<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const base = `plan-holders-${plan.key}`
  const people = holders.data?.users ?? []

  function showAll(event: MouseEvent<HTMLAnchorElement>) {
    if (!isPlainLeftClick(event)) return
    event.preventDefault()
    onShowPeople({ plan: plan.key })
  }

  return (
    <section id={base} className="plan-have" aria-labelledby={`${base}-title`}>
      <div className="plan-have-head">
        <h4 id={`${base}-title`} ref={heading} tabIndex={-1}>
          {t("people.plans.holders.title", { name: plan.name })}
        </h4>
        <a className="text-link plan-have-show" href={peoplePath({ plan: plan.key })} onClick={showAll}>
          {t("people.plans.holders.show")}
          <ArrowRight aria-hidden="true" />
        </a>
      </div>
      <HoldersState plan={plan} holders={holders} />
      {people.length > 0 && (
        <ul className="plan-have-list" aria-labelledby={`${base}-title`}>
          {people.map((person) => (
            <HolderRow
              key={person.id}
              person={person}
              plan={plan}
              overview={overview}
              assign={assign}
              changing={changing === person.id}
              onChange={(open) => setChanging(open ? person.id : null)}
              onChanged={(answer, message) => {
                setChanging(null)
                // Focus leaves the chooser first, so the toast's Close returns it to the list.
                heading.current?.focus()
                onChanged(answer, message)
              }}
              onOpenPerson={onOpenPerson}
            />
          ))}
        </ul>
      )}
      {(holders.data?.total ?? 0) > people.length && (
        <p className="field-hint">{t("people.plans.holders.more", { count: people.length })}</p>
      )}
    </section>
  )
}

/**
 * Who has the Plan, before the list: skeletons while they load, why they could not, with Try
 * again, or that nobody has it yet.
 */
function HoldersState({ plan, holders }: { plan: PlanSummary; holders: ReturnType<typeof usePlanPeople> }) {
  const { t } = useI18n()
  if (holders.isPending) {
    return (
      <div className="plan-assign-loading" role="status" aria-busy="true" aria-label={t("people.plans.holders.loading")}>
        <Skeleton className="h-11 w-full" />
      </div>
    )
  }
  if (!holders.data) {
    return (
      <div className="plan-assign-error" role="alert">
        <span>{t("people.plans.assign.loadError")}</span>
        <Button type="button" variant="outline" size="sm" onClick={() => void holders.refetch()}>
          <RefreshCw aria-hidden="true" />
          {t("people.plans.tryAgain")}
        </Button>
      </div>
    )
  }
  if (holders.data.users.length > 0) return null
  return <p className="plan-have-empty">{t("people.plans.holders.nobody", { name: plan.name })}</p>
}

/** One person who has the Plan: their email, what they are over, and Change plan with its chooser under them. */
function HolderRow({
  person,
  plan,
  overview,
  assign,
  changing,
  onChange,
  onChanged,
  onOpenPerson,
}: Omit<HoldersProps, "onShowPeople"> & {
  person: PersonRow
  changing: boolean
  onChange: (open: boolean) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const button = useRef<HTMLButtonElement>(null)
  const name = personName(i18n, person)
  const state = holderState(i18n, person, overview.enabled)
  const chooser = `plan-change-${person.id}`
  return (
    <li className="plan-holder">
      <div className="plan-holder-who">
        <a
          href={appPathForPerson(person.id)}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onOpenPerson(person.id)
          }}
        >
          {name}
        </a>
        <span className="plan-holder-state" data-tone={state.attention ? "attention" : undefined}>
          {state.attention && <TriangleAlert aria-hidden="true" />}
          {state.text}
        </span>
      </div>
      <Button
        ref={button}
        type="button"
        variant="outline"
        size="sm"
        aria-label={t("people.plans.holders.changeLabel", { person: name })}
        aria-expanded={changing}
        aria-controls={changing ? chooser : undefined}
        aria-disabled={assign.isPending || undefined}
        onClick={() => !assign.isPending && onChange(!changing)}
      >
        {t("people.plans.holders.change")}
      </Button>
      {changing && (
        <PlanChange
          person={person}
          from={plan.key}
          overview={overview}
          assign={assign}
          onChanged={onChanged}
          onCancel={() => {
            onChange(false)
            button.current?.focus()
          }}
        />
      )}
    </li>
  )
}
