import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Mail } from "lucide-react"
import { useEffect, useId, useRef, useState, type ReactNode } from "react"

import { AuthFrame } from "@/components/auth-frame"
import { Button } from "@/components/ui/button"
import { EmailChangeConfirm, EmailChangeSwitchAccount } from "@/features/email-change-confirm"
import { EmailChangeSignIn } from "@/features/email-change-sign-in"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api, type SessionStatus } from "@/lib/api"
import { useLinkToken } from "@/lib/use-link-check"

type Scope = { token: string; userId: string; isCurrent: (token: string) => boolean }

/** A proof page with an owning session, separate from token-only public admission. */
export function EmailChangePage() {
  const { token, isCurrent } = useLinkToken()
  const session = useQuery({ queryKey: ["session"], queryFn: api.session, staleTime: 0, retry: false })
  const i18n = useI18n()
  const { t } = i18n
  if (session.isPending) return <EmailFrame><p role="status">{t("auth.emailChange.loading")}</p></EmailFrame>
  if (session.error) return <EmailFrame><p role="alert">{apiErrorMessage(i18n, session.error)}</p><Button onClick={() => void session.refetch()}>{t("common.loadFailure.retry")}</Button></EmailFrame>
  const user = session.data.user
  if (!session.data.authenticated || !user) return <EmailFrame><EmailChangeSignIn key={token} isCurrent={() => isCurrent(token)} /></EmailFrame>
  return <EmailChangeLink key={`${user.id}:${token}`} token={token} userId={user.id} isCurrent={isCurrent} email={user.email} />
}

function EmailFrame({ children, done = false }: { children: ReactNode; done?: boolean }) {
  const { t } = useI18n()
  return (
    <AuthFrame heading={t(done ? "auth.emailChange.doneHeading" : "auth.emailChange.heading")} intro={t(done ? "auth.emailChange.doneIntro" : "auth.emailChange.intro")} panelTitle={t(done ? "auth.emailChange.doneTitle" : "auth.emailChange.panel")} panelNote={t(done ? "auth.emailChange.doneBody" : "auth.emailChange.note")} icon={Mail}>
      {children}
    </AuthFrame>
  )
}

function EmailChangeLink({ token, userId, isCurrent, email }: Scope & { email: string | null }) {
  const i18n = useI18n()
  const { t } = i18n
  const client = useQueryClient()
  const [outcome, setOutcome] = useState<"open" | "expired" | "done">("open")
  // Inspect the cache and fragment synchronously. A stale promise can settle before React has
  // rendered the new User or the browser has delivered hashchange.
  const current = () => isCurrent(token) && client.getQueryData<SessionStatus>(["session"])?.user?.id === userId
  const { valid, check } = useEmailChangeCheck({ token, userId, email, current, outcome })
  if (!current()) return <EmailFrame><p role="status">{t("auth.emailChange.loading")}</p></EmailFrame>
  if (outcome === "done") return <EmailFrame done><p className="sr-only" role="status">{t("auth.emailChange.doneTitle")}</p><AccountLink focus /></EmailFrame>
  if (!valid || outcome === "expired" || check.data?.usable === false) return <EmailFrame><Unusable current={current} /></EmailFrame>
  return <EmailFrame><CheckedEmail email={email} check={check} form={<EmailChangeConfirm token={token} current={current} onDone={() => setOutcome("done")} onExpired={() => setOutcome("expired")} />} /></EmailFrame>
}

function useEmailChangeCheck({ token, userId, email, current, outcome }: { token: string; userId: string; email: string | null; current: () => boolean; outcome: string }) {
  const instance = useId()
  const valid = token.length > 0 && token.length <= 128 && /^[\x20-\x7E]+$/.test(token) && email !== null
  const check = useQuery({
    // Each mounted link owns a fresh check. The proof is never a cache key or mutation variable.
    queryKey: ["email-change-check", userId, instance],
    queryFn: async () => {
      const result = await api.checkEmailChange(token)
      if (!result.usable || !current()) return { usable: false, pending: null }
      const status = await api.ownEmailChange()
      return current() ? { usable: status.pending !== null, pending: status.pending } : { usable: false, pending: null }
    },
    enabled: valid && outcome === "open", retry: false, gcTime: 0, staleTime: 0,
  })
  return { valid, check }
}

function CheckedEmail({ email, check, form }: { email: string | null; check: ReturnType<typeof useEmailChangeCheck>["check"]; form: ReactNode }) {
  const i18n = useI18n()
  const { t } = i18n
  return <>
    <p className="field-hint [overflow-wrap:anywhere]">{t("auth.emailChange.signedIn", { email: email ?? "" })}</p>
    {check.isPending && <p role="status">{t("auth.emailChange.loading")}</p>}
    {check.error && <div className="auth-form"><p className="inline-error" role="alert">{apiErrorMessage(i18n, check.error)}</p><Button onClick={() => void check.refetch()}>{t("common.loadFailure.retry")}</Button></div>}
    {check.data?.usable && !check.error && <><p className="font-medium [overflow-wrap:anywhere]">{t("auth.emailChange.target", { email: check.data.pending?.email ?? "" })}</p>{form}</>}
  </>
}

function AccountLink({ focus = false }: { focus?: boolean }) {
  const { t } = useI18n()
  const link = useRef<HTMLAnchorElement>(null)
  useEffect(() => { if (focus) link.current?.focus() }, [focus])
  return <Button asChild size="lg"><a ref={link} href="/settings/account">{t("settings.tabs.account")}</a></Button>
}

function Unusable({ current }: { current: () => boolean }) {
  const { t } = useI18n()
  return <div className="auth-form"><p role="status">{t("auth.emailChange.unusable")}</p><AccountLink /><EmailChangeSwitchAccount current={current} /></div>
}
