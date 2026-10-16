import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, LoaderCircle } from "lucide-react"
import { useEffect, useRef } from "react"

import { Button } from "@/components/ui/button"
import { YourPlanLink } from "@/components/your-plan-link"
import { OutcomeSigns } from "@/features/rule-preview-table"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { ApiError, api, type RuleDetail } from "@/lib/api"
import { appPathForRule, isPlainLeftClick, type OpenRule } from "@/lib/navigation"
import { startRefusal } from "@/lib/plans"
import { outcomeCounts, type PreviewNames, type PreviewRun } from "@/lib/rule-preview"
import { outcomeParts } from "@/lib/rule-preview-text"
import { enabledMessage } from "@/lib/rule-run"
import { RULE_CHANGE_QUERIES, rulePreviewKey } from "@/lib/use-rule-commands"

/** What enabling answers when the rule is no longer the one previewed. */
const CHANGED_CODES = ["rule_not_executable", "invalid_state_transition"]
/**
 * Why starting the rule did not work: it changed since the preview, its User's plan has no room
 * for another rule that syncs, or something else.
 */
type StartFailure = "changed" | "limited" | "failed"

/** Why enabling failed, read from the server's code. */
function startFailure(error: Error | null): StartFailure | null {
  if (!error) return null
  const code = error instanceof ApiError ? error.code : null
  if (CHANGED_CODES.includes(code ?? "")) return "changed"
  return code === "plan_limit_reached" ? "limited" : "failed"
}

/**
 * Keeps `--rule-preview-footer` on the page at the footer's height, which grows with text size and
 * with what it holds, so focus moved by keyboard always stops above it.
 */
function useFooterHeight() {
  const footer = useRef<HTMLElement>(null)
  useEffect(() => {
    const element = footer.current
    if (!element) return
    const root = document.documentElement
    const observer = new ResizeObserver(([entry]) => {
      if (entry) root.style.setProperty("--rule-preview-footer", `${entry.borderBoxSize[0]?.blockSize ?? element.offsetHeight}px`)
    })
    observer.observe(element)
    return () => {
      observer.disconnect()
      root.style.removeProperty("--rule-preview-footer")
    }
  }, [])
  return footer
}

/** Back to the rule, when the preview was made, and the page's one primary action. */
export function PreviewFooter({
  detail,
  names,
  run,
  busy,
  failed,
  onRetry,
  onOpenRule,
}: {
  detail: RuleDetail
  names: PreviewNames
  run: PreviewRun | undefined
  busy: boolean
  failed: boolean
  onRetry: () => void
  onOpenRule: OpenRule
}) {
  const i18n = useI18n()
  const queryClient = useQueryClient()
  const enable = useMutation({
    mutationFn: () => api.enableRule(detail.id),
    onError: () => void queryClient.invalidateQueries({ queryKey: ["rule", detail.id] }),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: rulePreviewKey(detail.id) })
      await Promise.all(
        [...RULE_CHANGE_QUERIES, ["rule", detail.id]].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      )
      onOpenRule(detail.id, { notice: enabledMessage(i18n, names.destination) })
    },
  })
  const failure = startFailure(enable.error)
  // Another tab or a scheduled run moved the rule on; its details are refetched below.
  const changed = failure === "changed"
  // What the plan says before Start; once a Start was refused, the summary already says it.
  const refusal = failure === "limited" ? null : startRefusal(i18n, detail)
  const canStart = run !== undefined && !failed && !changed && detail.state === "dry_run_validated" && detail.can_start
  const footer = useFooterHeight()
  return (
    <footer ref={footer} className="rule-preview-footer">
      <div className="rule-preview-footer-inner">
        <a
          className="back-link"
          href={appPathForRule(detail.id)}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onOpenRule(detail.id)
          }}
        >
          <ArrowLeft aria-hidden="true" /> {i18n.t("rulePreview.page.back")}
        </a>
        <StartSummary run={run} destination={names.destination} outcome={failure} error={enable.error} />
        {changed ? (
          // Start would only fail again, so a fresh preview takes its place as the one action.
          <RefreshInstead
            onRefresh={() => {
              enable.reset()
              onRetry()
            }}
          />
        ) : detail.state !== "enabled" && (
          <StartButton
            destination={names.destination}
            sharesDetails={detail.privacy_policy === "copy_details"}
            ready={canStart}
            refusal={refusal}
            starting={enable.isPending}
            waiting={busy}
            onStart={() => enable.mutate()}
          />
        )}
      </div>
    </footer>
  )
}

/**
 * Beside Start syncing, what it will do, so the decision is made with the counts in view; or why
 * starting did not work. A plan's refusal says what the plan allows, with a link to Your plan.
 */
function StartSummary({
  run,
  destination,
  outcome,
  error,
}: {
  run: PreviewRun | undefined
  destination: string
  outcome: StartFailure | null
  error: Error | null
}) {
  const i18n = useI18n()
  const { t } = i18n
  if (outcome === "limited") {
    return (
      <p className="rule-preview-summary" role="alert">
        {apiErrorMessage(i18n, error)} <YourPlanLink />
      </p>
    )
  }
  if (outcome) {
    return (
      <p className="rule-preview-summary" role="alert">
        {outcome === "changed" ? t("rulePreview.page.changedSincePreview") : t("rulePreview.page.enableFailed")}
      </p>
    )
  }
  if (!run) return <p className="rule-preview-summary" />
  return (
    <div className="rule-preview-summary">
      <p className="rule-preview-counts">
        <span className="sr-only">{t("rulePreview.counts.label", { destination })}</span>
        <OutcomeSigns parts={outcomeParts(i18n, outcomeCounts(run.items))} />
      </p>
      <p className="rule-preview-consequence">{t("rulePreview.page.pauseAnyTime")}</p>
    </div>
  )
}

/** In Start's place once the rule changed, taking the focus Start had when it was pressed. */
function RefreshInstead({ onRefresh }: { onRefresh: () => void }) {
  const { t } = useI18n()
  const button = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    button.current?.focus()
  }, [])
  return (
    <div className="rule-preview-start">
      <Button ref={button} className="rule-preview-start-button" onClick={onRefresh}>
        {t("rulePreview.page.previewAgain")}
      </Button>
    </div>
  )
}

function StartButton({
  destination,
  sharesDetails,
  ready,
  refusal,
  starting,
  waiting,
  onStart,
}: {
  destination: string
  sharesDetails: boolean
  ready: boolean
  /** Why the User's plan refuses this Start, in the words a refused Start shows; null when it may start. */
  refusal: string | null
  starting: boolean
  /** Whether Start waits on a preview that is reading; a failed one says why in its own panel. */
  waiting: boolean
  onStart: () => void
}) {
  const { t } = useI18n()
  const blocked = !ready || starting
  const described = refusal !== null || waiting
  return (
    <div className="rule-preview-start">
      <Button
        className="rule-preview-start-button"
        aria-disabled={blocked ? true : undefined}
        aria-describedby={described ? "rule-preview-start-note" : undefined}
        onClick={() => !blocked && onStart()}
      >
        {starting ? (
          <>
            <LoaderCircle aria-hidden="true" className="work-spinner" /> {t("rulePreview.page.starting")}
          </>
        ) : (
          t(sharesDetails ? "rulePreview.page.startSyncingDetails" : "rulePreview.page.startSyncing", { destination })
        )}
      </Button>
      <StartNote refusal={refusal} waiting={waiting} ready={ready} />
    </div>
  )
}

/**
 * Under Start: why the plan refuses it, with a link to Your plan; that it waits for the preview;
 * or, once it may start, that the rule can be paused later.
 */
function StartNote({ refusal, waiting, ready }: { refusal: string | null; waiting: boolean; ready: boolean }) {
  const { t } = useI18n()
  if (refusal !== null) {
    return (
      <span id="rule-preview-start-note" className="rule-preview-start-note">
        {refusal} <YourPlanLink />
      </span>
    )
  }
  if (waiting) {
    return (
      <span id="rule-preview-start-note" className="rule-preview-start-note">
        {t("rulePreview.page.availableWhenDone")}
      </span>
    )
  }
  // Beside the counts on wide screens; here, under the button, where narrow screens put it.
  if (!ready) return null
  return <span className="rule-preview-start-note rule-preview-start-reassure">{t("rulePreview.page.pauseAnyTime")}</span>
}
