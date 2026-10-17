import { TriangleAlert } from "lucide-react"
import { useEffect, useRef } from "react"

import { Switch } from "@/components/ui/switch"
import type { ChangeSetting } from "@/features/use-setting-change"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { rich } from "@/i18n/rich"
import type { PlansOverview } from "@/lib/api"
import { isPlainLeftClick } from "@/lib/navigation"
import { peoplePath, type PeopleFilter } from "@/lib/people-query"
import { compactStatusSentence, statusFacts, statusSentence, switchedBy, type PlansFact } from "@/lib/plans-catalog"
import type { PlanCommands } from "@/lib/use-plans"

/** Opens Everyone showing only the people a filter names, such as who is over a limit. */
export type ShowPeople = (filter: PeopleFilter) => void

/**
 * The Plans tab's status card, first: whether Plans are on, one sentence on what they do now or,
 * while off, would do, and the switch, which applies at once and keeps the default. While its change
 * is on its way, the switch keeps focus and shows the state asked for; a refusal shows under it and
 * takes focus. Then, once a Plan exists, the facts. While a Plan's panel is open beside it, the
 * card is `compact`: its title, a shorter sentence, and the switch.
 */
export function PlansStatus({
  overview,
  commands,
  compact,
  onChange,
  onShowPeople,
}: {
  overview: PlansOverview
  commands: PlanCommands
  compact: boolean
  onChange: ChangeSetting
  onShowPeople: ShowPeople
}) {
  const i18n = useI18n()
  const { t } = i18n
  const sentence = compact ? compactStatusSentence(i18n, overview) : statusSentence(i18n, overview)
  return (
    <section
      id="plans-status"
      className="page-card plans-status"
      aria-labelledby="plans-status-title"
      data-state={overview.enabled ? "on" : "off"}
      data-compact={compact || undefined}
    >
      <div className="plans-status-main">
        <div className="plans-status-text">
          <h3 id="plans-status-title">{t(overview.enabled ? "people.plans.status.titleOn" : "people.plans.status.titleOff")}</h3>
          <p id="plans-status-sentence">{rich(sentence, { strong: (text) => <strong>{text}</strong> })}</p>
        </div>
        <PlansSwitch overview={overview} commands={commands} onChange={onChange} />
      </div>
      {!compact && <PlansFacts facts={statusFacts(i18n, overview)} onShowPeople={onShowPeople} />}
    </section>
  )
}

/**
 * The one switch, described by the card's sentence. While its change is on its way it keeps focus
 * and shows the state asked for; a refusal shows under it and takes focus.
 */
function PlansSwitch({ overview, commands, onChange }: { overview: PlansOverview; commands: PlanCommands; onChange: ChangeSetting }) {
  const i18n = useI18n()
  const { t } = i18n
  const { setting } = commands
  const toggle = useRef<HTMLButtonElement>(null)
  const pending = setting.isPending
  const checked = pending ? setting.variables.enabled : overview.enabled
  const refused = setting.error && switchedBy(setting.variables, overview) ? setting.error : null
  useEffect(() => {
    if (refused) toggle.current?.focus()
  }, [refused])
  return (
    <div className="plans-status-control">
      <Switch
        ref={toggle}
        id="plans-switch"
        aria-label={t("people.plans.status.switch")}
        aria-describedby={refused ? "plans-status-sentence plans-switch-error" : "plans-status-sentence"}
        checked={checked}
        pending={pending}
        stateLabels={{ on: t("people.plans.status.stateOn"), off: t("people.plans.status.stateOff") }}
        onCheckedChange={(enabled) => onChange({ enabled, defaultPlan: overview.default_plan }, overview)}
      />
      {refused && (
        <p id="plans-switch-error" className="field-error" role="alert">
          {apiErrorMessage(i18n, refused)}
        </p>
      )}
    </div>
  )
}

/**
 * Whom Plans limit, who is over a limit, the Default Plan, and who is never limited, as nouns and
 * numbers. Who is over takes Attention Ochre and its icon while Plans are on, and Show, which opens
 * Everyone narrowed to them.
 */
function PlansFacts({ facts, onShowPeople }: { facts: PlansFact[]; onShowPeople: ShowPeople }) {
  if (facts.length === 0) return null
  return (
    <dl className="plans-facts">
      {facts.map((fact) => (
        <div key={fact.id} className="plans-fact" data-fact={fact.id}>
          <dt>{fact.label}</dt>
          <dd data-tone={fact.attention ? "attention" : undefined}>
            {fact.attention && <TriangleAlert aria-hidden="true" />}
            <span>{fact.value}</span>
            {fact.id === "over" && fact.over > 0 && <ShowOver onShowPeople={onShowPeople} />}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function ShowOver({ onShowPeople }: { onShowPeople: ShowPeople }) {
  const { t } = useI18n()
  return (
    <a
      className="plans-fact-link"
      href={peoplePath({ over: true })}
      aria-label={t("people.plans.status.showLabel")}
      onClick={(event) => {
        if (!isPlainLeftClick(event)) return
        event.preventDefault()
        onShowPeople({ over: true })
      }}
    >
      {t("people.plans.status.show")}
    </a>
  )
}
