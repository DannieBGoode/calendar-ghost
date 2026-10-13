import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, LoaderCircle } from "lucide-react"
import { useEffect, useRef } from "react"

import { Button } from "@/components/ui/button"
import { OutcomeSigns } from "@/features/rule-preview-table"
import { useI18n } from "@/i18n/provider"
import { ApiError, api, type RuleDetail } from "@/lib/api"
import { appPathForRule, isPlainLeftClick, type OpenRule } from "@/lib/navigation"
import { outcomeCounts, type PreviewNames, type PreviewRun } from "@/lib/rule-preview"
import { outcomeParts } from "@/lib/rule-preview-text"
import { enabledMessage } from "@/lib/rule-run"
import { RULE_CHANGE_QUERIES, rulePreviewKey } from "@/lib/use-rule-commands"

/** What enabling answers when the rule is no longer the one previewed. */
const CHANGED_CODES = ["rule_not_executable", "invalid_state_transition"]
/** Why starting the rule did not work: it changed since the preview, or something else. */
type StartFailure = "changed" | "failed"

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
  // Another tab or a scheduled run moved the rule on; its details are refetched below.
  const changed = enable.error instanceof ApiError && CHANGED_CODES.includes(enable.error.code ?? "")
  const canStart = run !== undefined && !failed && !changed && detail.state === "dry_run_validated"
  const startFailure: StartFailure | null = enable.error ? (changed ? "changed" : "failed") : null
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
        <StartSummary run={run} destination={names.destination} outcome={startFailure} />
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
 * starting did not work.
 */
function StartSummary({
  run,
  destination,
  outcome,
}: {
  run: PreviewRun | undefined
  destination: string
  outcome: StartFailure | null
}) {
  const i18n = useI18n()
  const { t } = i18n
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
  starting,
  waiting,
  onStart,
}: {
  destination: string
  sharesDetails: boolean
  ready: boolean
  starting: boolean
  /** Whether Start waits on a preview that is reading; a failed one says why in its own panel. */
  waiting: boolean
  onStart: () => void
}) {
  const { t } = useI18n()
  const blocked = !ready || starting
  return (
    <div className="rule-preview-start">
      <Button
        className="rule-preview-start-button"
        aria-disabled={blocked ? true : undefined}
        aria-describedby={waiting ? "rule-preview-start-note" : undefined}
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
      {waiting ? (
        <span id="rule-preview-start-note" className="rule-preview-start-note">
          {t("rulePreview.page.availableWhenDone")}
        </span>
      ) : (
        // Beside the counts on wide screens; here, under the button, where narrow screens put it.
        ready && <span className="rule-preview-start-note rule-preview-start-reassure">{t("rulePreview.page.pauseAnyTime")}</span>
      )}
    </div>
  )
}
