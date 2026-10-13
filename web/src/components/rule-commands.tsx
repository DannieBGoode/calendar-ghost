import { useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, CircleAlert, CircleDot, CirclePause, LoaderCircle, ShieldAlert } from "lucide-react"

import { OverflowMenu, type OverflowMenuItem } from "@/components/overflow-menu"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { PreviewSummary } from "@/lib/api"
import { accountSearch, appPathForRulePreview, connectionsPath, isPlainLeftClick, type ViewChange } from "@/lib/navigation"
import { ruleStateLabel } from "@/lib/rule-change"
import { previewReadyLabel } from "@/lib/rule-run"
import { workDescription, workLabel, workMeta, type RuleWork, type RuleWorkKind } from "@/lib/rule-work"
import { useNow } from "@/lib/use-now"
import { PENDING_LABELS, rulePreviewKey, type RuleCommand, type RuleFeedback, type RunnableCommand } from "@/lib/use-rule-commands"

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
  ruleId,
  state,
  reauthorize,
  pending,
  describedBy,
  onRun,
  onPreview,
  onViewChange,
}: {
  ruleId: string
  state: string
  /** An account of the rule to reauthorize first; its Settings row is the next step. */
  reauthorize: { id: string } | undefined
  pending: RuleCommand | undefined
  describedBy?: string | undefined
  onRun: (command: RunnableCommand) => void
  /** Opens the rule's preview page, which previews it. */
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

/** Opens a rule's preview page for a fresh preview, never one kept from earlier in the session. */
function useFreshPreview(ruleId: string, onPreview: () => void) {
  const queryClient = useQueryClient()
  return () => {
    queryClient.removeQueries({ queryKey: rulePreviewKey(ruleId) })
    onPreview()
  }
}

export function RuleCommandMenu({
  ruleId,
  state,
  unauthorized,
  pending,
  source,
  destination,
  reserveSpace = false,
  onRun,
  onPreview,
}: {
  ruleId: string
  state: string
  /** Whether an account of the rule needs reauthorization, so running it now would fail. */
  unauthorized: boolean
  pending: RuleCommand | undefined
  source: string
  destination: string
  /** Keeps list rows aligned when a rule has no routine commands. */
  reserveSpace?: boolean
  onRun: (command: RunnableCommand) => void
  /** Opens the rule's preview page. */
  onPreview: () => void
}) {
  const { t } = useI18n()
  const previewAgain = useFreshPreview(ruleId, onPreview)
  const busy = pending !== undefined
  const items: OverflowMenuItem[] = []
  if (state === "dry_run_validated") {
    items.push({
      id: "preview",
      label: t("ruleDetails.commands.previewAgain"),
      description: t("ruleDetails.commands.previewAgainDescription", { destination }),
      disabled: busy,
      onSelect: previewAgain,
    })
  }
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
      description: t("ruleDetails.commands.pauseDescription", { destination }),
      disabled: busy,
      onSelect: () => onRun("pause"),
    })
  }
  if (!items.length) return reserveSpace ? <span className="overflow-menu-spacer" aria-hidden="true" /> : null
  return <OverflowMenu label={t("ruleDetails.commands.moreActions", { source, destination })} items={items} />
}

/** What the latest preview found, which the Start syncing button refers to, and a way to see it. */
export function PreviewReadyNote({
  id,
  ruleId,
  preview,
  destination,
  onPreview,
}: {
  id: string
  ruleId: string
  preview: PreviewSummary | null | undefined
  destination: string
  onPreview: () => void
}) {
  const i18n = useI18n()
  const now = useNow()
  const previewAgain = useFreshPreview(ruleId, onPreview)
  return (
    <p className="rule-note">
      <span id={id}>{previewReadyLabel(i18n, preview, destination, now)}</span>{" "}
      <button type="button" className="rule-note-action" onClick={previewAgain}>
        {i18n.t("ruleDetails.commands.previewAgain")}
      </button>
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
