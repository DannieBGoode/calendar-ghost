import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useRef, useState, type RefObject } from "react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { OwnEmailForm } from "@/features/settings-own-email-form"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { api, type SessionStatus } from "@/lib/api"
import { useDisclosureFocus } from "@/lib/use-disclosure-focus"

type EmailStatus = Awaited<ReturnType<typeof api.ownEmailChange>>

/** The current sign-in stays visible until verification completes. */
export function OwnEmailItem({ email, onDone }: { email: string | null; onDone: (message: string) => void }) {
  const i18n = useI18n()
  const { t } = i18n
  const { status, current, refresh } = useEmailStatus()
  const [open, setOpen] = useState(false)
  const toggle = useRef<HTMLButtonElement>(null)
  const first = useRef<HTMLInputElement>(null)
  useDisclosureFocus(open, first, toggle)
  const data = status.data
  const available = canChangeEmail(data) && !status.error
  return (
    <div className="setting-item">
      <div className="setting-row">
        <div className="min-w-0 [overflow-wrap:anywhere]">
          <h3>{t("settings.ownAccount.email.title")}</h3>
          <p>{email ?? t("settings.ownAccount.email.none")}</p>
        </div>
        {!open && <Button ref={toggle} id="own-email-toggle" type="button" variant="outline" disabled={!available} onClick={() => setOpen(true)}>{t("settings.ownAccount.email.change")}</Button>}
      </div>
      <EmailStatusNote status={status} current={current} refresh={refresh} onDone={onDone} toggle={open ? first : toggle} />
      {open && data && <OwnEmailForm key={email} mode={data.mode} available={available} first={first} current={current} onClose={() => setOpen(false)} onDone={onDone} onRefresh={refresh} />}
    </div>
  )
}

function canChangeEmail(data: EmailStatus | undefined): boolean {
  if (!data || data.mode === "unavailable") return false
  return data.mode === "verified" || data.pending === null
}

function EmailModeNote({ data }: { data: EmailStatus | undefined }) {
  const { t } = useI18n()
  if (data?.mode === "unavailable") return <UnavailableEmail reason={data.reason} />
  if (data?.mode === "direct" && data.pending) return <p className="field-hint">{t("settings.ownAccount.email.cancelBeforeDirect")}</p>
  return null
}

function useEmailStatus() {
  const client = useQueryClient()
  const session = useQuery({ queryKey: ["session"], queryFn: api.session, enabled: false })
  const userId = session.data?.user?.id
  const status = useQuery({
    queryKey: ["own-email-change", userId], queryFn: api.ownEmailChange,
    enabled: !!userId, staleTime: 0, refetchOnWindowFocus: "always",
  })
  const current = () => client.getQueryData<SessionStatus>(["session"])?.user?.id === userId
  const refresh = () => client.invalidateQueries({ queryKey: ["own-email-change", userId] })
  return { status, current, refresh }
}

function EmailStatusNote({ status, current, refresh, onDone, toggle }: ReturnType<typeof useEmailStatus> & { onDone: (message: string) => void; toggle: RefObject<HTMLElement | null> }) {
  const i18n = useI18n()
  const { t } = i18n
  const client = useQueryClient()
  const cancel = useMutation({
    mutationFn: (id: string) => api.cancelEmailChange(id), retry: false,
    onSuccess: (_, id) => {
      if (!current()) return
      const latest = client.getQueriesData<EmailStatus>({ queryKey: ["own-email-change"] })
      if (latest.some(([, data]) => data?.pending?.id === id)) onDone(t("settings.ownAccount.email.cancelled"))
      toggle.current?.focus()
    },
    onSettled: () => { if (current()) void refresh() },
  })
  const data = status.data
  return <>
    {status.isPending && <Skeleton className="h-8 w-full" />}
    {status.error && <div className="inline-error" role="alert"><p>{apiErrorMessage(i18n, status.error)}</p><Button variant="outline" onClick={() => void status.refetch()}>{t("common.loadFailure.retry")}</Button></div>}
    <EmailModeNote data={data} />
    {data?.pending && <PendingEmail pending={data.pending} busy={cancel.isPending} onCancel={() => { if (!cancel.isPending && data.pending) cancel.mutate(data.pending.id) }} />}
    {cancel.error && <p className="field-error" role="alert">{apiErrorMessage(i18n, cancel.error)}</p>}
  </>
}

function PendingEmail({ pending, busy, onCancel }: { pending: NonNullable<EmailStatus["pending"]>; busy: boolean; onCancel: () => void }) {
  const { t, format } = useI18n()
  return (
    <div className="setting-row pt-5">
      <div className="min-w-0 [overflow-wrap:anywhere]">
        <p><strong>{t("settings.ownAccount.email.pending", { email: pending.email })}</strong></p>
        <p>{t("settings.ownAccount.email.pendingNote")}</p>
        <p>{t("settings.ownAccount.email.expires")} <time dateTime={pending.expires_at}>{format.dateTime(pending.expires_at)}</time></p>
      </div>
      <Button type="button" variant="outline" aria-disabled={busy} onClick={onCancel}>{t(busy ? "auth.pleaseWait" : "settings.ownAccount.email.cancelPending")}</Button>
    </div>
  )
}

const CONFIGURATION_REASONS: Record<NonNullable<EmailStatus["reason"]>, MessageKey> = {
  smtp_missing: "settings.identityEmail.smtpMissing",
  smtp_security: "settings.identityEmail.smtpSecurity",
  origin_missing: "settings.identityEmail.originMissing",
  origin_invalid: "settings.identityEmail.originInvalid",
  origin_insecure: "settings.identityEmail.originInsecure",
  master_key_missing: "settings.identityEmail.masterKeyMissing",
}

function UnavailableEmail({ reason }: { reason: EmailStatus["reason"] }) {
  const { t } = useI18n()
  return <div className="field-hint"><p>{t("settings.ownAccount.email.unavailable")}</p>{reason && <p>{t(CONFIGURATION_REASONS[reason])}</p>}</div>
}
