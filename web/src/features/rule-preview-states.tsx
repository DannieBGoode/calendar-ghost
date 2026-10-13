import { CircleAlert, RefreshCw, ShieldAlert } from "lucide-react"
import type { ReactNode } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import { accountSearch, appPathForRule, connectionsPath, isPlainLeftClick, type ViewChange } from "@/lib/navigation"
import { providerWords } from "@/lib/providers"
import type { PreviewFailure } from "@/lib/rule-preview-failure"

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
    <Button variant="outline" aria-disabled={busy ? true : undefined} onClick={() => !busy && onRetry()}>
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
      const account = failure.account?.email ?? providerWords(i18n, null).account
      return (
        <Panel variant="stopped" icon={<ShieldAlert aria-hidden="true" />} title={t("rulePreview.states.lapsedTitle", { account })} body={t("rulePreview.states.lapsedBody")}
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
export function PreviewEmpty({ source, from }: { source: string; from: Date }) {
  const i18n = useI18n()
  return (
    <section className="rule-preview-empty">
      <span className="rule-preview-ghost"><GhostMark /></span>
      <h2>{i18n.t("rulePreview.states.emptyTitle", { source, date: i18n.format.date(from, { day: "numeric", month: "short" }) })}</h2>
      <p>{i18n.t("rulePreview.states.emptyBody")}</p>
    </section>
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
