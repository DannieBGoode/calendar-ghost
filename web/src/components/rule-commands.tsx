import { CheckCircle2, CircleAlert, CircleDot, CirclePause, LoaderCircle, ShieldAlert } from "lucide-react"

import { OverflowMenu, type OverflowMenuItem } from "@/components/overflow-menu"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { PreviewSummary } from "@/lib/api"
import { appPathForView, isPlainLeftClick, type AppView } from "@/lib/navigation"
import { ruleStateLabel } from "@/lib/rule-change"
import { elapsedLabel } from "@/lib/rule-removal"
import { previewReadyLabel } from "@/lib/rule-run"
import { workDescription, workLabel, type RuleWork, type RuleWorkKind } from "@/lib/rule-work"
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
  working?: RuleWorkKind
}) {
  if (state === "removing" || working) {
    return (
      <Badge variant="neutral">
        <LoaderCircle aria-hidden="true" className="work-spinner" />{" "}
        {working ? workLabel(working) : ruleStateLabel(state)}
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
  if (state === "dry_run_validated") {
    return (
      <Button
        aria-disabled={pending !== undefined || undefined}
        aria-describedby={describedBy}
        onClick={() => pending === undefined && onRun("enable")}
      >
        {pending === "enable" ? (
          <>
            <LoaderCircle aria-hidden="true" className="work-spinner" /> {PENDING_LABELS.enable}
          </>
        ) : (
          "Start syncing"
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
      {state === "degraded" ? "Preview to restart" : "Preview rule"}
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
  const now = useNow()
  return (
    <p id={id} className="rule-note">
      {previewReadyLabel(preview, destination, now)}
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
  const now = useNow(1_000)
  return (
    <div className="rule-work">
      <LoaderCircle aria-hidden="true" className="work-spinner" />
      <p>
        <span>{workDescription(work, source, destination)}</span>
        <span className="rule-work-meta">
          {work.startedAt !== null && `Running for ${elapsedLabel(now - work.startedAt)} · `}
          It keeps running if you leave this page.
        </span>
      </p>
      {work.progress && (
        <progress
          className="removal-bar"
          value={work.progress.done}
          max={work.progress.total}
          aria-label={workDescription(work, source, destination)}
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
