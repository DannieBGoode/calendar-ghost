import { CheckCircle2, CircleAlert, CircleDot, CirclePause, LoaderCircle, ShieldAlert } from "lucide-react"

import { OverflowMenu, type OverflowMenuItem } from "@/components/overflow-menu"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { PreviewSummary } from "@/lib/api"
import { appPathForView, isPlainLeftClick, type AppView } from "@/lib/navigation"
import { ruleStateLabel } from "@/lib/rule-change"
import { previewReadyLabel } from "@/lib/rule-run"
import { workDescription, workLabel, workMeta, type RuleWork, type RuleWorkKind } from "@/lib/rule-work"
import { useNow } from "@/lib/use-now"
import { PENDING_LABELS, type RuleCommand, type RuleFeedback } from "@/lib/use-rule-commands"

const PREVIEWABLE_STATES = ["draft", "paused", "degraded"]

/**
 * `removing` is a display state for a running Rule Removal, not a stored one. `working` names
 * other work running now, which says more than the stored state while it lasts.
 */
export function RuleStatusBadge({
  state,
  stopped,
  working,
}: {
  state: string
  stopped: boolean
  working?: RuleWorkKind | undefined
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
      {ruleStateLabel(i18n, state)}
    </Badge>
  )
}

/**
 * The one visible next step for a rule; routine commands live in the overflow menu. While a
 * command runs the button is aria-disabled rather than disabled, so it keeps keyboard focus.
 */
export function RuleNextAction({
  state,
  disconnected,
  pending,
  describedBy,
  onRun,
  onViewChange,
}: {
  state: string
  disconnected: boolean
  pending: RuleCommand | undefined
  describedBy?: string | undefined
  onRun: (command: RuleCommand) => void
  onViewChange: (view: AppView) => void
}) {
  const { t } = useI18n()
  if (state === "disabled" || state === "removing") return null
  if (disconnected) {
    return (
      <Button variant="outline" asChild>
        <a
          href={appPathForView("settings")}
          aria-describedby={describedBy}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onViewChange("settings")
          }}
        >
          {t("ruleDetails.commands.reauthorize")}
        </a>
      </Button>
    )
  }
  if (state === "dry_run_validated") {
    return (
      <Button
        aria-disabled={pending !== undefined || undefined}
        aria-describedby={describedBy}
        onClick={() => pending === undefined && onRun("enable")}
      >
        {pending === "enable" ? (
          <>
            <LoaderCircle aria-hidden="true" className="work-spinner" /> {t(PENDING_LABELS.enable)}
          </>
        ) : (
          t("ruleDetails.commands.startSyncing")
        )}
      </Button>
    )
  }
  if (!PREVIEWABLE_STATES.includes(state)) return null
  return (
    <Button
      variant="outline"
      aria-disabled={pending !== undefined || undefined}
      aria-describedby={describedBy}
      onClick={() => pending === undefined && onRun("preview")}
    >
      {/* The badge and work note say it is previewing; the label stays so it does not echo them. */}
      {state === "degraded" ? t("ruleDetails.commands.previewToRestart") : t("ruleDetails.commands.preview")}
    </Button>
  )
}

export function RuleCommandMenu({
  state,
  disconnected,
  pending,
  source,
  destination,
  reserveSpace = false,
  onRun,
}: {
  state: string
  disconnected: boolean
  pending: RuleCommand | undefined
  source: string
  destination: string
  /** Keeps list rows aligned when a rule has no routine commands. */
  reserveSpace?: boolean
  onRun: (command: RuleCommand) => void
}) {
  const { t } = useI18n()
  const busy = pending !== undefined
  const items: OverflowMenuItem[] = []
  if (state === "enabled" && !disconnected) {
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
      description: t("ruleDetails.commands.pauseDescription", { destination }),
      disabled: busy,
      onSelect: () => onRun("pause"),
    })
  }
  if (!items.length) return reserveSpace ? <span className="overflow-menu-spacer" aria-hidden="true" /> : null
  return <OverflowMenu label={t("ruleDetails.commands.moreActions", { source, destination })} items={items} />
}

/** What the latest preview found, which the Start syncing button refers to. */
export function PreviewReadyNote({
  id,
  preview,
  destination,
}: {
  id: string
  preview: PreviewSummary | null | undefined
  destination: string
}) {
  const i18n = useI18n()
  const now = useNow()
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
