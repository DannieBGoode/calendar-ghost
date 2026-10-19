import { CheckCircle2, CircleAlert, CircleDot, CirclePause, LoaderCircle, ShieldAlert } from "lucide-react"

import { OverflowMenu, type OverflowMenuItem } from "@/components/overflow-menu"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { YourPlanLink } from "@/components/your-plan-link"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { PreviewSummary } from "@/lib/api"
import { accountSearch, appPathForRulePreview, connectionsPath, isPlainLeftClick, type ViewChange } from "@/lib/navigation"
import { ruleStateLabel } from "@/lib/rule-change"
import { previewReadyLabel } from "@/lib/rule-run"
import { workDescription, workLabel, workMeta, type RuleWork, type RuleWorkKind } from "@/lib/rule-work"
import { useNow } from "@/lib/use-now"
import { usePlanWarning } from "@/lib/use-own-plan"
import type { RuleCommand, RuleFeedback, RunnableCommand } from "@/lib/use-rule-commands"

const PREVIEWABLE_STATES = ["draft", "paused", "degraded"]

/**
 * `removing` is a display state for a running Rule Removal, not a stored one. `working` names
 * other work running now, which says more than the stored state while it lasts. A previewed rule
 * whose Start the User's Plan would refuse reads "Previewed", not "Ready to start".
 */
export function RuleStatusBadge({
  state,
  stopped,
  working,
  refused,
}: {
  state: string
  stopped: boolean
  working?: RuleWorkKind | undefined
  refused?: boolean
}) {
  const i18n = useI18n()
  if (state === "removing" || working) {
    return (
      <Badge variant="neutral">
        <LoaderCircle aria-hidden="true" className="work-spinner" />{" "}
        {working ? workLabel(i18n, working) : ruleStateLabel(i18n, state)}
      </Badge>
    )
  }
  if (stopped || state === "disabled") {
    return (
      <Badge variant="stopped">
        <ShieldAlert aria-hidden="true" /> {state === "disabled" ? ruleStateLabel(i18n, state) : i18n.t("ruleDetails.state.degraded")}
      </Badge>
    )
  }
  if (state === "enabled") {
    return (
      <Badge variant="healthy">
        <CheckCircle2 aria-hidden="true" /> {i18n.t("ruleDetails.state.enabled")}
      </Badge>
    )
  }
  return (
    <Badge variant="neutral">
      {state === "paused" ? <CirclePause aria-hidden="true" /> : <CircleDot aria-hidden="true" />}{" "}
      {restingLabel(i18n, state, refused === true)}
    </Badge>
  )
}

/** A rule's state while it neither runs nor stopped; "Previewed" when its Plan would refuse Start. */
function restingLabel(i18n: I18n, state: string, refused: boolean): string {
  return state === "dry_run_validated" && refused ? i18n.t("ruleDetails.state.previewed") : ruleStateLabel(i18n, state)
}

/** The one visible next step for a rule; routine commands live in the overflow menu. */
export function RuleNextAction({
  ruleId,
  state,
  reauthorize,
  describedBy,
  onPreview,
  onViewChange,
}: {
  ruleId: string
  state: string
  /** An account of the rule to reauthorize first; its Settings row is the next step. */
  reauthorize: { id: string } | undefined
  describedBy?: string | undefined
  /** Opens the rule's preview page, where it is previewed and started. */
  onPreview: () => void
  onViewChange: ViewChange
}) {
  const { t } = useI18n()
  if (state === "disabled" || state === "removing") return null
  if (reauthorize) {
    const search = accountSearch(reauthorize.id)
    return (
      <Button variant="outline" asChild>
        <a
          href={connectionsPath(search)}
          aria-describedby={describedBy}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onViewChange("settings", { search, settingsTab: "connections" })
          }}
        >
          {t("ruleDetails.commands.reauthorize")}
        </a>
      </Button>
    )
  }
  // A previewed rule starts only from its preview, where the events it will write are in view.
  if (state === "dry_run_validated") {
    return (
      <Button asChild>
        <a
          href={appPathForRulePreview(ruleId)}
          aria-describedby={describedBy}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onPreview()
          }}
        >
          {t("ruleDetails.commands.reviewAndStart")}
        </a>
      </Button>
    )
  }
  if (!PREVIEWABLE_STATES.includes(state)) return null
  return (
    <Button variant="outline" asChild>
      <a
        href={appPathForRulePreview(ruleId)}
        aria-describedby={describedBy}
        onClick={(event) => {
          if (!isPlainLeftClick(event)) return
          event.preventDefault()
          onPreview()
        }}
      >
        {state === "degraded" ? t("ruleDetails.commands.previewToRestart") : t("ruleDetails.commands.preview")}
      </a>
    </Button>
  )
}

export function RuleCommandMenu({
  state,
  unauthorized,
  pending,
  source,
  destination,
  reserveSpace = false,
  onRun,
}: {
  state: string
  /** Whether an account of the rule needs reauthorization, so running it now would fail. */
  unauthorized: boolean
  pending: RuleCommand | undefined
  source: string
  destination: string
  /** Keeps list rows aligned when a rule has no routine commands. */
  reserveSpace?: boolean
  onRun: (command: RunnableCommand) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  // Read before any return, as the rules of hooks require.
  const mayNotRestart = usePlanWarning() && countsTowardPlan(state, unauthorized)
  const busy = pending !== undefined
  const items: OverflowMenuItem[] = []
  if (state === "enabled" && !unauthorized) {
    items.push(
      {
        id: "sync",
        label: t("ruleDetails.commands.syncNow"),
        description: t("ruleDetails.commands.syncNowDescription", { source }),
        disabled: busy,
        onSelect: () => onRun("sync"),
      },
      {
        id: "reconcile",
        label: t("ruleDetails.commands.reconcileNow"),
        description: t("ruleDetails.commands.reconcileNowDescription", { destination }),
        disabled: busy,
        onSelect: () => onRun("reconcile"),
      },
    )
  }
  if (state === "enabled" || state === "degraded") {
    items.push({
      id: "pause",
      label: t("ruleDetails.commands.pause"),
      description: pauseDescription(i18n, destination, mayNotRestart),
      disabled: busy,
      onSelect: () => onRun("pause"),
    })
  }
  if (!items.length) return reserveSpace ? <span className="overflow-menu-spacer" aria-hidden="true" /> : null
  return <OverflowMenu label={t("ruleDetails.commands.moreActions", { source, destination })} items={items} />
}

/**
 * Whether the rule counts toward its User's plan, as the Web UI can tell: enabled, or stopped
 * only until an account of it is reauthorized.
 */
function countsTowardPlan(state: string, unauthorized: boolean): boolean {
  return state === "enabled" || (state === "degraded" && unauthorized)
}

/**
 * What Pause does; and, while more rules count than the plan allows, that the plan may not let
 * the rule start again, since a paused rule gives up its place (decision 4).
 */
function pauseDescription({ t }: I18n, destination: string, mayNotRestart: boolean): string {
  const description = t("ruleDetails.commands.pauseDescription", { destination })
  return mayNotRestart ? `${description} ${t("common.plan.mayNotRestart")}` : description
}

/**
 * What the latest preview found, which Review and start leads back to; or, when the User's Plan
 * would refuse Start, why, in the words the preview page uses, with a link to Your plan.
 */
export function PreviewReadyNote({
  id,
  preview,
  destination,
  refusal = null,
}: {
  id: string
  preview: PreviewSummary | null | undefined
  destination: string
  refusal?: string | null
}) {
  const i18n = useI18n()
  const now = useNow()
  if (refusal !== null) {
    return (
      <p id={id} className="rule-note">
        {refusal} <YourPlanLink />
      </p>
    )
  }
  return (
    <p id={id} className="rule-note">
      {previewReadyLabel(i18n, preview, destination, now)}
    </p>
  )
}

/**
 * What a working rule is doing and for how long. It replaces the result line while it lasts; the
 * result is announced separately, so this is not a live region.
 */
export function RuleWorkNote({
  work,
  source,
  destination,
}: {
  work: RuleWork
  source: string
  destination: string
}) {
  const i18n = useI18n()
  const now = useNow(1_000)
  const description = workDescription(i18n, work, source, destination)
  return (
    <div className="rule-work">
      <LoaderCircle aria-hidden="true" className="work-spinner" />
      <p>
        <span>{description}</span>
        <span className="rule-work-meta">{workMeta(i18n, work, now)}</span>
      </p>
      {work.progress && (
        <progress
          className="removal-bar"
          value={work.progress.done}
          max={work.progress.total}
          aria-label={description}
        />
      )}
    </div>
  )
}

export function RuleFeedbackNote({ feedback }: { feedback: RuleFeedback | undefined }) {
  if (!feedback) return null
  if (feedback.tone === "error") {
    return (
      <p className="rule-feedback rule-feedback-error">
        <CircleAlert aria-hidden="true" /> {feedback.text}
      </p>
    )
  }
  return (
    <p className="rule-feedback">
      <CheckCircle2 aria-hidden="true" /> {feedback.text}
    </p>
  )
}

/** Always mounted so assistive technology reliably hears each command result. */
export function LiveAnnouncement({ text }: { text: string }) {
  return (
    <p className="sr-only" role="status" aria-live="polite">
      {text}
    </p>
  )
}
