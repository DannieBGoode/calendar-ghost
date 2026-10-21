import { useMutation, useQueryClient } from "@tanstack/react-query"
import { UserPlus } from "lucide-react"
import { useState, type SyntheticEvent } from "react"

import { AuthFrame } from "@/components/auth-frame"
import { NewPasswordFields } from "@/components/new-password-fields"
import { Button } from "@/components/ui/button"
import { RegistrationRecovery } from "@/features/registration-recovery"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { ApiError, api } from "@/lib/api"
import type { LinkStatus } from "@/lib/public-links"
import { newPasswordReady } from "@/lib/passwords"
import { useLinkCheck, useLinkToken } from "@/lib/use-link-check"

type Props = { token: string; isCurrent: (token: string) => boolean; onSignedIn: () => void }

export function RegistrationPage({ onSignedIn }: { onSignedIn: () => void }) {
  const { token, isCurrent } = useLinkToken()
  return <RegistrationLink key={token} token={token} isCurrent={isCurrent} onSignedIn={onSignedIn} />
}

function RegistrationLink(props: Props) {
  const { t } = useI18n()
  const check = useLinkCheck("registration", props.token)
  const [outcome, setOutcome] = useState<"unusable" | "session" | null>(null)
  const unusable = outcome === "unusable" || check.status === "unusable"
  const sessionFailed = outcome === "session"
  return (
    <AuthFrame heading={t("auth.registration.heading")} intro={t("auth.registration.intro")}
      {...registrationPanel(t, sessionFailed, unusable)} icon={UserPlus}>
      <RegistrationCheckState status={check.status} error={check.error} onRecheck={() => { void check.recheck() }} />
      {(unusable || sessionFailed) && <RegistrationRecovery sessionFailed={sessionFailed} />}
      {!outcome && check.status === "usable" && check.data?.email && <RegistrationForm {...props} email={check.data.email} onRefused={setOutcome} />}
    </AuthFrame>
  )
}

type FormProps = Props & { email: string; onRefused: (outcome: "unusable" | "session") => void }

function RegistrationForm({ token, isCurrent, onSignedIn, email, onRefused }: FormProps) {
  const i18n = useI18n()
  const { t } = i18n
  const client = useQueryClient()
  const [passwords, setPasswords] = useState({ password: "", confirmation: "" })
  const complete = useMutation({
    mutationFn: () => api.completeRegistration(token, passwords.password),
    onError: (error) => {
      if (!isCurrent(token) || !(error instanceof ApiError)) return
      if (error.status === 410) onRefused("unusable")
      if (error.status === 401 && error.code === "incorrect_credentials") {
        window.history.replaceState(null, "", window.location.pathname)
        onRefused("session")
      }
    },
    onSuccess: async (session) => {
      if (!isCurrent(token)) return
      client.setQueryData(["session"], session)
      window.history.replaceState(null, "", "/overview")
      await client.invalidateQueries()
      onSignedIn()
    },
  })
  const ready = passwords.password.length <= 1024 && newPasswordReady(passwords.password, passwords.confirmation)
  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isCurrent(token) && ready && !complete.isPending) complete.mutate()
  }
  return (
    <form className="auth-form" onSubmit={submit}>
      <p className="break-words">{t("auth.registration.email", { email })}</p>
      <NewPasswordFields {...passwords} onChange={setPasswords} maxLength={1024} />
      {complete.error && <p className="inline-error" role="alert">{complete.error instanceof ApiError && complete.error.status === 503 ? t("auth.signUp.unavailable") : apiErrorMessage(i18n, complete.error)}</p>}
      <Button type="submit" size="lg" disabled={!ready || complete.isPending}>{t(complete.isPending ? "auth.pleaseWait" : "auth.registration.submit")}</Button>
    </form>
  )
}

function registrationPanel(t: ReturnType<typeof useI18n>["t"], sessionFailed: boolean, unusable: boolean) {
  if (sessionFailed) return { panelTitle: t("auth.registration.sessionTitle"), panelNote: t("auth.registration.sessionBody") }
  if (unusable) return { panelTitle: t("auth.registration.unusableTitle"), panelNote: t("auth.registration.unusable") }
  return { panelTitle: t("auth.registration.panel"), panelNote: t("auth.registration.note") }
}

function RegistrationCheckState({ status, error, onRecheck }: { status: LinkStatus; error: unknown; onRecheck: () => void }) {
  const i18n = useI18n()
  const { t } = i18n
  if (status === "checking") return <p role="status">{t("auth.registration.checking")}</p>
  if (status !== "failed") return null
  const message = error instanceof ApiError && error.status === 503 ? t("auth.signUp.unavailable") : apiErrorMessage(i18n, error)
  return <div className="auth-form"><p className="inline-error" role="alert">{message}</p><Button onClick={onRecheck}>{t("auth.registration.tryAgain")}</Button><Button variant="ghost" asChild><a href="/">{t("auth.signIn")}</a></Button></div>
}
