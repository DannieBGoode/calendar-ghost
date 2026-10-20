import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import type { IdentityEmail } from "@/lib/api"
import { useIdentityEmail } from "@/lib/use-identity-email"

const REASONS: Record<NonNullable<IdentityEmail["unavailable_reason"]>, MessageKey> = {
  smtp_missing: "settings.identityEmail.smtpMissing",
  smtp_security: "settings.identityEmail.smtpSecurity",
  origin_missing: "settings.identityEmail.originMissing",
  origin_invalid: "settings.identityEmail.originInvalid",
  origin_insecure: "settings.identityEmail.originInsecure",
  master_key_missing: "settings.identityEmail.masterKeyMissing",
}
const STATES: Record<IdentityEmail["test_state"], MessageKey> = {
  idle: "settings.identityEmail.idle",
  queued: "settings.identityEmail.pending",
  sending: "settings.identityEmail.pending",
  accepted: "settings.identityEmail.accepted",
  failed: "settings.identityEmail.failed",
}

/** Identity mail is tested only to the current administrator, never a chosen recipient. */
export function IdentityEmailSection() {
  const i18n = useI18n()
  const { t } = i18n
  const { readiness, test } = useIdentityEmail()
  const data = readiness.data
  const pending = test.isPending || data?.test_state === "queued" || data?.test_state === "sending"
  return (
    <section className="settings-section" aria-labelledby="identity-email-title">
      <div className="section-heading">
        <div>
          <h2 id="identity-email-title">{t("settings.identityEmail.title")}</h2>
          <p>{t("settings.identityEmail.intro")}</p>
        </div>
      </div>
      {readiness.isPending && <Skeleton className="h-16 w-full" />}
      {readiness.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("settings.identityEmail.loadError")}</span>
          <Button variant="outline" onClick={() => void readiness.refetch()}>{t("settings.identityEmail.retry")}</Button>
        </div>
      )}
      {data && <IdentityEmailStatus data={data} pending={pending} unavailable={!!readiness.error} onSend={() => test.mutate()} />}
      {test.error && <p className="field-error" role="alert">{apiErrorMessage(i18n, test.error)}</p>}
    </section>
  )
}

function IdentityEmailStatus({ data, pending, unavailable, onSend }: {
  data: IdentityEmail
  pending: boolean
  unavailable: boolean
  onSend: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <div className="settings-list">
      <div className="setting-row">
        <div className="min-w-0 break-words">
          <p role="status">{t(data.unavailable_reason ? REASONS[data.unavailable_reason] : STATES[data.test_state])}</p>
          {data.tested_at && <p>{t("settings.identityEmail.lastVerified", { time: i18n.format.dateTime(data.tested_at) })}</p>}
        </div>
        <Button variant="outline" className="shrink-0" disabled={!data.configured || pending || unavailable} onClick={onSend}>
          {t(pending ? "settings.identityEmail.pending" : "settings.identityEmail.send")}
        </Button>
      </div>
    </div>
  )
}
