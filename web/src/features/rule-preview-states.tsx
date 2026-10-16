import { CircleAlert, RefreshCw, ShieldAlert } from "lucide-react"
import { useState, type ReactNode } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import { accountSearch, appPathForRule, connectionsPath, isPlainLeftClick, type ViewChange } from "@/lib/navigation"
import { providerWords } from "@/lib/providers"
import type { PreviewFailure } from "@/lib/rule-preview-failure"
import { withYear } from "@/lib/rule-preview-text"
import { useNow } from "@/lib/use-now"

function Panel({ variant, icon, title, body, action }: { variant: "stopped" | "attention" | "quiet"; icon: ReactNode; title: string; body: string; action: ReactNode }) {
  return (
    <section className="rule-preview-panel" data-tone={variant} role="alert">
      {icon}
      <div>
        <h2>{title}</h2>
        <p>{body}</p>
        {action}
      </div>
    </section>
  )
}

function navigationLink(href: string, label: string, onFollow: () => void) {
  return (
    <Button variant="outline" asChild>
      <a
        href={href}
        onClick={(event) => {
          if (!isPlainLeftClick(event)) return
          event.preventDefault()
          onFollow()
        }}
      >
        {label}
      </a>
    </Button>
  )
}

function retryButton(i18n: I18n, busy: boolean, onRetry: () => void) {
  return (
    // While busy, a press only moves focus to the page's Refresh, which stays once this panel goes.
    <Button variant="outline" aria-disabled={busy ? true : undefined} onClick={onRetry}>
      <RefreshCw aria-hidden="true" /> {i18n.t("rulePreview.page.previewAgain")}
    </Button>
  )
}

/** One panel in place of the table, with the one step that helps. */
export function PreviewFailurePanel({
  failure,
  ruleId,
  busy,
  onRetry,
  onOpenRule,
  onViewChange,
}: {
  failure: PreviewFailure
  ruleId: string
  /** Whether a retry is reading now; the panel stays until it finishes. */
  busy: boolean
  onRetry: () => void
  onOpenRule: () => void
  onViewChange: ViewChange
}) {
  const i18n = useI18n()
  const { t } = i18n
  switch (failure.kind) {
    case "lapsed": {
      const search = failure.account ? accountSearch(failure.account.id) : ""
      // The account's address when it is known, otherwise "Your Google account", never a bare noun.
      const title = failure.account
        ? t("rulePreview.states.lapsedTitle", { account: failure.account.email })
        : t("rulePreview.states.lapsedTitleProvider", { account: providerWords(i18n, failure.provider).account })
      return (
        <Panel variant="stopped" icon={<ShieldAlert aria-hidden="true" />} title={title} body={t("rulePreview.states.lapsedBody")}
          action={navigationLink(connectionsPath(search), t("rulePreview.states.reauthorize"), () => onViewChange("settings", { search, settingsTab: "connections" }))}
        />
      )
    }
    case "unavailable":
      return (
        <Panel variant="attention" icon={<CircleAlert aria-hidden="true" />} title={t("rulePreview.states.unavailableTitle", providerWords(i18n, failure.provider))} body={t("rulePreview.states.unavailableBody")} action={retryButton(i18n, busy, onRetry)} />
      )
    case "changed":
      return <Panel variant="quiet" icon={<CircleAlert aria-hidden="true" />} title={t("rulePreview.states.changedTitle")} body={t("rulePreview.states.changedBody")} action={retryButton(i18n, busy, onRetry)} />
    case "syncing":
      return (
        <Panel variant="quiet" icon={<CircleAlert aria-hidden="true" />} title={t("rulePreview.states.syncingTitle")} body={t("rulePreview.states.syncingBody")}
          action={navigationLink(appPathForRule(ruleId), t("rulePreview.states.openRule"), onOpenRule)}
        />
      )
    case "failed":
      return <Panel variant="attention" icon={<CircleAlert aria-hidden="true" />} title={t("rulePreview.states.failedTitle")} body={failure.message} action={retryButton(i18n, busy, onRetry)} />
  }
}

/** The source has nothing in the window yet; the rule still syncs what arrives. */
export function PreviewEmpty({ source, from, now }: { source: string; from: Date; now: Date }) {
  const i18n = useI18n()
  return (
    <section className="rule-preview-empty">
      <span className="rule-preview-ghost"><GhostMark /></span>
      <h2>{i18n.t("rulePreview.states.emptyTitle", { source, date: i18n.format.date(from, withYear(from, now)) })}</h2>
      <p>{i18n.t("rulePreview.states.emptyBody")}</p>
    </section>
  )
}

/** After this many seconds the status counts them, so a long read is seen to move on. */
const COUNT_AFTER = 3
/** After this many, it also says that a large calendar takes longer. */
const REASSURE_AFTER = 12

/**
 * What the preview is reading, above the rows it will replace, with a line that changes as the
 * seconds pass, so the page never looks stopped, even without motion. It is not a live region:
 * the page announces the read once, not each second.
 */
export function PreviewReading({ text }: { text: string }) {
  const { t } = useI18n()
  const [startedAt] = useState(() => Date.now())
  const now = useNow(1_000)
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1_000))
  return (
    <div className="rule-preview-reading">
      <span className="rule-preview-reading-ghost">
        <GhostMark />
      </span>
      <div>
        <p className="rule-preview-reading-title">{text}</p>
        <p className="rule-preview-reading-detail">
          {seconds < COUNT_AFTER ? t("rulePreview.reading.checking") : t("rulePreview.reading.elapsed", { count: seconds })}
          {seconds >= REASSURE_AFTER && ` ${t("rulePreview.reading.large")}`}
        </p>
      </div>
    </div>
  )
}

/** Rows that stand in for the table while the source is read. */
export function PreviewSkeleton() {
  return (
    <div className="rule-preview-skeleton" aria-hidden="true">
      {Array.from({ length: 6 }, (_, index) => (
        <Skeleton key={index} className="h-10 w-full" />
      ))}
    </div>
  )
}
