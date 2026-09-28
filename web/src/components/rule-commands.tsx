import { CheckCircle2, CircleAlert, CircleDot, CirclePause, LoaderCircle, ShieldAlert } from "lucide-react"

import { OverflowMenu, type OverflowMenuItem } from "@/components/overflow-menu"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { PreviewSummary } from "@/lib/api"
import { appPathForView, isPlainLeftClick, type AppView } from "@/lib/navigation"
import { ruleStateLabel } from "@/lib/rule-change"
import { enableSummary } from "@/lib/rule-run"
import { PENDING_LABELS, type RuleCommand, type RuleFeedback } from "@/lib/use-rule-commands"

const PREVIEWABLE_STATES = ["draft", "paused", "degraded"]

/** `removing` is a display state for a Rule Removal running in this session, not a stored one. */
export function RuleStatusBadge({ state, stopped }: { state: string; stopped: boolean }) {
  if (state === "removing") {
    return (
      <Badge variant="neutral">
        <LoaderCircle aria-hidden="true" className="removal-spinner" /> {ruleStateLabel(state)}
      </Badge>
    )
  }
  if (stopped || state === "disabled") {
    return (
      <Badge variant="attention">
        <ShieldAlert aria-hidden="true" /> {state === "disabled" ? ruleStateLabel(state) : "Stopped"}
      </Badge>
    )
  }
  if (state === "enabled") {
    return (
      <Badge variant="healthy">
        <CheckCircle2 aria-hidden="true" /> Enabled
      </Badge>
    )
  }
  return (
    <Badge variant="neutral">
      {state === "paused" ? <CirclePause aria-hidden="true" /> : <CircleDot aria-hidden="true" />}{" "}
      {ruleStateLabel(state)}
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
  describedBy?: string
  onRun: (command: RuleCommand) => void
  onViewChange: (view: AppView) => void
}) {
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
          Reauthorize in Settings
        </a>
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
      {pending === "preview" ? PENDING_LABELS.preview : state === "degraded" ? "Preview to restart" : "Preview rule"}
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
  const busy = pending !== undefined
  const items: OverflowMenuItem[] = []
  if (state === "enabled" && !disconnected) {
    items.push(
      {
        id: "sync",
        label: "Sync now",
        description: `Apply changes made in ${source} since the last run. Runs by itself every five minutes.`,
        disabled: busy,
        onSelect: () => onRun("sync"),
      },
      {
        id: "reconcile",
        label: "Reconcile now",
        description: `Check every event this rule wrote to ${destination} and repair any that were edited or deleted there. Runs by itself once a day.`,
        disabled: busy,
        onSelect: () => onRun("reconcile"),
      },
    )
  }
  if (state === "enabled" || state === "degraded") {
    items.push({
      id: "pause",
      label: "Pause rule",
      description: `Stop writing to ${destination}. Existing events stay; resuming needs a new preview.`,
      disabled: busy,
      onSelect: () => onRun("pause"),
    })
  }
  if (!items.length) return reserveSpace ? <span className="overflow-menu-spacer" aria-hidden="true" /> : null
  return <OverflowMenu label={`More actions for ${source} to ${destination}`} items={items} />
}

export function EnableReview({
  preview,
  source,
  destination,
  privacy,
  pending,
  describedBy,
  onEnable,
}: {
  preview: Pick<PreviewSummary, "eligible_events" | "excluded_events"> | null | undefined
  source: string
  destination: string
  privacy: "busy_only" | "copy_details"
  pending: RuleCommand | undefined
  describedBy?: string
  onEnable: () => void
}) {
  return (
    <div className="enable-review">
      <p>
        <strong>Preview passed.</strong> {enableSummary({ preview: preview ?? undefined, source, destination, privacy })}
      </p>
      <Button
        aria-disabled={pending !== undefined || undefined}
        aria-describedby={describedBy}
        onClick={() => pending === undefined && onEnable()}
      >
        {pending === "enable" ? PENDING_LABELS.enable : "Start syncing"}
      </Button>
    </div>
  )
}

export function RuleFeedbackNote({
  pending,
  feedback,
}: {
  pending: RuleCommand | undefined
  feedback: RuleFeedback | undefined
}) {
  if (pending && pending !== "preview" && pending !== "enable") {
    return <p className="rule-feedback rule-feedback-pending">{PENDING_LABELS[pending]}</p>
  }
  if (!feedback) return null
  if (feedback.tone === "error") {
    return (
      <p className="rule-feedback rule-feedback-error">
        <CircleAlert aria-hidden="true" /> {feedback.text}
      </p>
    )
  }
  return <p className="rule-feedback">{feedback.text}</p>
}

/** Always mounted so assistive technology reliably hears each command result. */
export function LiveAnnouncement({ text }: { text: string }) {
  return (
    <p className="sr-only" role="status" aria-live="polite">
      {text}
    </p>
  )
}
