import { Clock, Info, TriangleAlert, Zap } from "lucide-react"
import { useEffect, useRef, type ReactNode, type RefObject } from "react"

import { Badge } from "@/components/ui/badge"
import { PlanDetails } from "@/features/people-plan-details"
import { PlanRowMenu } from "@/features/people-plan-row-menu"
import type { ShowPeople } from "@/features/people-plans-status"
import type { ChangeSetting } from "@/features/use-setting-change"
import { useI18n } from "@/i18n/provider"
import type { PlanSummary, PlansOverview, SyncInterval } from "@/lib/api"
import { isPlainLeftClick } from "@/lib/navigation"
import { peoplePath, type PeopleFilter } from "@/lib/people-query"
import { catalogOrder, countCell, speedLabel } from "@/lib/plans-catalog"
import type { PlanWorkControls } from "@/lib/use-plan-work"
import type { PlanCommands } from "@/lib/use-plans"

/** Fixed widths, so columns stay put whatever the Plans say. */
const COLUMN_CLASSES = ["col-plan", "col-count", "col-count", "col-count", "col-speed", "col-people", "col-actions"]
/** The counts each Plan has a column for, by where its limits keep them. */
const COUNTS = [
  { column: "rules", label: "people.plans.catalog.rules", limit: "rules" },
  { column: "accounts", label: "people.plans.catalog.accounts", limit: "connected_accounts" },
  { column: "tokens", label: "people.plans.catalog.tokens", limit: "integration_tokens" },
] as const

/** What a Plan's row needs beside the Plan itself. */
type RowContext = {
  overview: PlansOverview
  commands: PlanCommands
  work: PlanWorkControls
  onChange: ChangeSetting
  onShowPeople: ShowPeople
  /** The reader, whom Assign people marks "You". */
  currentUserId: string
}

/**
 * The catalog of Plans: a table with a column for each limit, the default first, so Plans compare
 * by column. Each Plan's name opens its form, People opens Everyone filtered by it, and More
 * actions holds the rest. When the catalog itself is narrow, each row becomes a card that labels
 * its values.
 */
export function PlansCatalog(context: RowContext) {
  const { t } = useI18n()
  const plans = catalogOrder(context.overview.plans)
  return (
    <section
      id="plans-catalog"
      className="page-card plans-catalog"
      aria-labelledby="plans-catalog-title"
      data-plans={context.overview.enabled ? "on" : "off"}
    >
      <div className="plans-catalog-head">
        <h3 id="plans-catalog-title">{t("people.plans.catalog.title", { count: plans.length })}</h3>
        <p className="plans-catalog-intro">{t("people.plans.catalog.intro")}</p>
      </div>
      <div className="plans-table-wrap">
        <table className="plans-table" role="table" aria-labelledby="plans-catalog-title">
          <colgroup>
            {COLUMN_CLASSES.map((name, index) => (
              <col key={index} className={name} />
            ))}
          </colgroup>
          <thead role="rowgroup">
            <tr role="row">
              <th scope="col" role="columnheader">
                {t("people.plans.catalog.plan")}
              </th>
              {COUNTS.map(({ column, label }) => (
                <th key={column} scope="col" role="columnheader" className="plans-count">
                  {t(label)}
                </th>
              ))}
              <th scope="col" role="columnheader">
                {t("people.plans.catalog.speed")}
              </th>
              <th scope="col" role="columnheader">
                {t("people.plans.catalog.people")}
              </th>
              <th scope="col" role="columnheader">
                <span className="sr-only">{t("people.plans.catalog.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {plans.map((plan) => (
              <PlanRows key={plan.key} plan={plan} {...context} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="plans-catalog-note">
        <Info aria-hidden="true" />
        {t("people.plans.catalog.note")}
      </p>
    </section>
  )
}

/**
 * One Plan's row, and under it, while open, its form, Assign people, its removal's confirmation,
 * or why a command from its menu was refused. A Plan just added takes focus at its name as it shows.
 */
function PlanRows({ plan, ...context }: RowContext & { plan: PlanSummary }) {
  const { work } = context
  const row = useRef<HTMLTableRowElement>(null)
  const name = useRef<HTMLButtonElement>(null)
  const justAdded = work.added === plan.key
  useEffect(() => {
    if (justAdded) name.current?.focus()
  }, [justAdded])
  const open = work.work !== null && work.work.action !== "new" && work.work.key === plan.key ? work.work.action : null

  return (
    <>
      <tr ref={row} role="row" className="plan-row" data-plan={plan.key} data-open={open !== null || undefined}>
        <NameCell plan={plan} editing={open === "edit"} work={work} name={name} />
        <CountCells plan={plan} />
        <SpeedCell interval={plan.limits.sync_interval} />
        <PeopleCell plan={plan} enabled={context.overview.enabled} onShowPeople={context.onShowPeople} />
        <td role="cell" className="plan-col-actions">
          <PlanRowMenu
            plan={plan}
            overview={context.overview}
            work={work}
            onMakeDefault={() => context.onChange({ enabled: context.overview.enabled, defaultPlan: plan.key }, context.overview)}
          />
        </td>
      </tr>
      <PlanDetails
        plan={plan}
        open={open}
        columns={COLUMN_CLASSES.length}
        row={row}
        name={name}
        overview={context.overview}
        commands={context.commands}
        work={work}
        currentUserId={context.currentUserId}
      />
    </>
  )
}

/** The Plan's name, which opens its form, with Default beside it and, under it, whom the default is for. */
function NameCell({
  plan,
  editing,
  work,
  name,
}: {
  plan: PlanSummary
  editing: boolean
  work: PlanWorkControls
  name: RefObject<HTMLButtonElement | null>
}) {
  const { t } = useI18n()
  return (
    <td role="cell" className="plan-col-plan">
      <div className="plan-name-row">
        <button
          ref={name}
          id={`plan-name-${plan.key}`}
          type="button"
          className="plan-name"
          aria-label={t("people.plans.editLabel", { name: plan.name })}
          aria-expanded={editing}
          aria-controls={editing ? `plan-edit-${plan.key}` : undefined}
          aria-disabled={work.busy || undefined}
          onClick={() => (editing ? work.close() : work.open({ action: "edit", key: plan.key }))}
        >
          {plan.name}
        </button>
        {plan.is_default && <Badge variant="outline">{t("people.plans.isDefault")}</Badge>}
      </div>
      {plan.is_default && <p className="plan-sub">{t("people.plans.catalog.defaultFor")}</p>}
    </td>
  )
}

/** A Plan's counts in tabular numerals, with "Unlimited" and "None" muted. */
function CountCells({ plan }: { plan: PlanSummary }) {
  const i18n = useI18n()
  return COUNTS.map(({ column, label, limit }) => {
    const { text, muted } = countCell(i18n, plan.limits[limit])
    return (
      <td
        key={column}
        role="cell"
        className={`plan-col-${column} plans-count`}
        data-label={i18n.t(label)}
        data-muted={muted ? "true" : undefined}
      >
        {text}
      </td>
    )
  })
}

/** How soon the Plan's rules sync, with a lightning bolt for Instant and a clock otherwise. */
function SpeedCell({ interval }: { interval: SyncInterval }) {
  const i18n = useI18n()
  const Icon = interval === "instant" ? Zap : Clock
  return (
    <td role="cell" className="plan-col-speed" data-label={i18n.t("people.plans.catalog.speed")}>
      <span className="plan-speed">
        <Icon aria-hidden="true" />
        {speedLabel(i18n, interval)}
      </span>
    </td>
  )
}

/**
 * Who has the Plan, as a link to Everyone filtered by it, and how many of the people it limits are
 * over a limit, as a chip linking to them: Attention Ochre with its icon while Plans are on, and
 * neutral, "would be over", while they are off.
 */
function PeopleCell({ plan, enabled, onShowPeople }: { plan: PlanSummary; enabled: boolean; onShowPeople: ShowPeople }) {
  const { t } = useI18n()
  const { key, name, people, over_people: over } = plan
  return (
    <td role="cell" className="plan-col-people" data-label={t("people.plans.catalog.people")}>
      <div className="plan-people">
        {people === 0 ? (
          <span className="plan-nobody">{t("people.plans.catalog.nobody")}</span>
        ) : (
          <PeopleLink
            className="plan-holders"
            filter={{ plan: key }}
            label={t("people.plans.catalog.holdersLabel", { count: people, name })}
            onShowPeople={onShowPeople}
          >
            {t("people.plans.catalog.holders", { count: people })}
          </PeopleLink>
        )}
        {over > 0 && (
          <PeopleLink
            className="plan-over"
            attention={enabled}
            filter={{ plan: key, over: true }}
            label={t(enabled ? "people.plans.catalog.overLabel" : "people.plans.catalog.wouldBeOverLabel", {
              count: over,
              name,
            })}
            onShowPeople={onShowPeople}
          >
            <Badge variant={enabled ? "attention" : "neutral"}>
              {enabled && <TriangleAlert aria-hidden="true" />}
              {t(enabled ? "people.plans.catalog.over" : "people.plans.catalog.wouldBeOver", { count: over })}
            </Badge>
          </PeopleLink>
        )}
      </div>
    </td>
  )
}

/** A link to Everyone showing only the people `filter` names, opened in place. */
function PeopleLink({
  className,
  attention = false,
  filter,
  label,
  onShowPeople,
  children,
}: {
  className: string
  /** Takes the attention tone, as people over a limit Plans enforce now. */
  attention?: boolean
  filter: PeopleFilter
  label: string
  onShowPeople: ShowPeople
  children: ReactNode
}) {
  return (
    <a
      className={className}
      data-tone={attention ? "attention" : undefined}
      href={peoplePath(filter)}
      aria-label={label}
      onClick={(event) => {
        if (!isPlainLeftClick(event)) return
        event.preventDefault()
        onShowPeople(filter)
      }}
    >
      {children}
    </a>
  )
}
