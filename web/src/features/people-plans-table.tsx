import { Clock, Info, TriangleAlert, Zap } from "lucide-react"
import { useRef, type MouseEvent, type ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { PlanDetails } from "@/features/people-plan-details"
import { PlanRowMenu } from "@/features/people-plan-row-menu"
import type { ShowPeople } from "@/features/people-plans-status"
import type { ChangeSetting } from "@/features/use-setting-change"
import { useI18n } from "@/i18n/provider"
import type { PlanSummary, PlansOverview, SyncInterval } from "@/lib/api"
import { appPathForPlanPanel, isPlainLeftClick } from "@/lib/navigation"
import { peoplePath, type PeopleFilter } from "@/lib/people-query"
import { catalogOrder, countCell, removable, speedLabel } from "@/lib/plans-catalog"
import type { PlanWorkControls } from "@/lib/use-plan-work"
import type { PlanCommands } from "@/lib/use-plans"

/** Fixed widths, so columns stay put whatever the Plans say. */
const COLUMN_CLASSES = ["col-plan", "col-count", "col-count", "col-count", "col-speed", "col-people", "col-actions"]
/** Beside an open panel, only what picks a Plan. */
const COMPACT_COLUMN_CLASSES = ["col-plan", "col-speed", "col-people"]
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
}

/**
 * The catalog of Plans: how many there are, with `action`, New plan, beside them, then a table
 * with a column for each limit, the default first, so Plans compare by column. Each Plan's name
 * heads its row and opens its panel, as a press anywhere else on the row does; People opens
 * Everyone filtered by it, and More actions holds the rest. While a panel is open beside it, the
 * catalog keeps only the Plan, its sync speed, and who has it, and marks the open Plan. When the
 * catalog itself is narrow, each row becomes a card that labels its values.
 */
export function PlansCatalog({ action, ...context }: RowContext & { action: ReactNode }) {
  const { t } = useI18n()
  const plans = catalogOrder(context.overview.plans)
  const { panel } = context.work
  const compact = panel !== null
  const columns = compact ? COMPACT_COLUMN_CLASSES : COLUMN_CLASSES
  return (
    <section
      id="plans-catalog"
      className="page-card plans-catalog"
      aria-labelledby="plans-catalog-title"
      data-plans={context.overview.enabled ? "on" : "off"}
    >
      <div className="plans-catalog-head">
        <h3 id="plans-catalog-title">{t("people.plans.catalog.title", { count: plans.length })}</h3>
        {action}
      </div>
      <div className="plans-table-wrap">
        <table className="plans-table" role="table" aria-labelledby="plans-catalog-title" data-compact={compact || undefined}>
          <colgroup>
            {columns.map((name, index) => (
              <col key={index} className={name} />
            ))}
          </colgroup>
          <CatalogHead compact={compact} />
          <tbody role="rowgroup">
            {plans.map((plan) => (
              <PlanRows key={plan.key} plan={plan} compact={compact} columns={columns.length} {...context} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="plans-catalog-note">
        <Info aria-hidden="true" />
        {t(compact ? "people.plans.catalog.noteOpen" : "people.plans.catalog.note")}
      </p>
    </section>
  )
}

/** The column headings; beside an open panel, only Plan, Sync speed, and People. */
function CatalogHead({ compact }: { compact: boolean }) {
  const { t } = useI18n()
  return (
    <thead role="rowgroup">
      <tr role="row">
        <th scope="col" role="columnheader">
          {t("people.plans.catalog.plan")}
        </th>
        {!compact &&
          COUNTS.map(({ column, label }) => (
            <th key={column} scope="col" role="columnheader" className="plans-count">
              {t(label)}
            </th>
          ))}
        <th scope="col" role="columnheader" className="plans-speed">
          {t("people.plans.catalog.speed")}
        </th>
        <th scope="col" role="columnheader">
          {t("people.plans.catalog.people")}
        </th>
        {!compact && (
          <th scope="col" role="columnheader">
            <span className="sr-only">{t("people.plans.catalog.actions")}</span>
          </th>
        )}
      </tr>
    </thead>
  )
}

/** A press on a Plan's row that its links, buttons, and menu do not answer themselves. */
function pressesRow(event: MouseEvent<HTMLTableRowElement>): boolean {
  return !(event.target as HTMLElement).closest("a, button, .plan-col-actions")
}

/**
 * One Plan's row, and under it, while open, its removal's confirmation, or why a command from its
 * menu was refused. The name is the row's keyboard target; the rest of the row is a larger
 * pointer target that opens the same panel, as Activity's rows do.
 */
function PlanRows({ plan, compact, columns, ...context }: RowContext & { plan: PlanSummary; compact: boolean; columns: number }) {
  const { work } = context
  const row = useRef<HTMLTableRowElement>(null)
  const removing = work.removing === plan.key
  const confirming = removing && removable(plan)
  const selected = work.panel?.plan === plan.key
  return (
    <>
      <tr
        ref={row}
        role="row"
        className="plan-row"
        data-plan={plan.key}
        data-open={confirming || undefined}
        data-selected={selected || undefined}
        onClick={(event) => {
          if (pressesRow(event)) work.openPanel({ plan: plan.key, tab: "limits" })
        }}
      >
        <NameCell plan={plan} selected={selected} work={work} />
        {!compact && <CountCells plan={plan} />}
        <SpeedCell interval={plan.limits.sync_interval} />
        <PeopleCell plan={plan} enabled={context.overview.enabled} onShowPeople={context.onShowPeople} />
        {!compact && (
          <td role="cell" className="plan-col-actions">
            <PlanRowMenu
              plan={plan}
              overview={context.overview}
              work={work}
              onMakeDefault={() => context.onChange({ enabled: context.overview.enabled, defaultPlan: plan.key }, context.overview)}
            />
          </td>
        )}
      </tr>
      <PlanDetails
        plan={plan}
        removing={removing}
        columns={columns}
        row={row}
        overview={context.overview}
        commands={context.commands}
        work={work}
      />
    </>
  )
}

/**
 * The Plan's name, which heads its row: a link that opens its panel, marked as the page while it
 * is open, with Default beside it.
 */
function NameCell({ plan, selected, work }: { plan: PlanSummary; selected: boolean; work: PlanWorkControls }) {
  const { t } = useI18n()
  const { openPanel } = work
  const panel = { plan: plan.key, tab: "limits" } as const
  return (
    <th scope="row" role="rowheader" className="plan-col-plan">
      <div className="plan-name-row">
        <a
          id={`plan-name-${plan.key}`}
          href={appPathForPlanPanel(panel)}
          className="plan-name"
          aria-current={selected ? "page" : undefined}
          aria-disabled={work.busy || undefined}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            openPanel(panel)
          }}
        >
          {plan.name}
        </a>
        {plan.is_default && <Badge variant="outline">{t("people.plans.isDefault")}</Badge>}
      </div>
    </th>
  )
}

/** A Plan's counts in tabular numerals, with "Unlimited" muted. */
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

/** How soon the Plan's rules sync, with a lightning bolt for Instant and a clock otherwise, on the row's line of text. */
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
