import { useMutation, useQuery } from "@tanstack/react-query"
import { KeyRound } from "lucide-react"
import { useState, type SyntheticEvent } from "react"

import { AuthFrame } from "@/components/auth-frame"
import { NewPasswordFields } from "@/components/new-password-fields"
import { Button } from "@/components/ui/button"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { ApiError, api } from "@/lib/api"
import { newPasswordReady } from "@/lib/passwords"
import type { LinkStatus } from "@/lib/public-links"
import { useLinkCheck, useLinkToken } from "@/lib/use-link-check"

type PanelCopy = { title: MessageKey; note: MessageKey }

const PANEL: Record<"form" | "unusable" | "done", PanelCopy> = {
  form: { title: "auth.passwordReset.panel", note: "auth.passwordReset.note" },
  unusable: { title: "auth.passwordReset.unusable.title", note: "auth.passwordReset.unusable.body" },
  done: { title: "auth.passwordReset.done.title", note: "auth.passwordReset.done.body" },
}

function panelFor(status: LinkStatus, done: boolean): PanelCopy {
  if (done) return PANEL.done
  return status === "unusable" ? PANEL.unusable : PANEL.form
}

/**
 * Where a User opens an emailed or administrator-issued Password Reset Link and chooses a
 * new password. Completion always returns to sign-in.
 */
export function PasswordResetPage() {
  const { token, isCurrent } = useLinkToken()
  // A newer link starts over: its own check, an empty form, and no earlier outcome.
  return <PasswordResetLink key={token} token={token} isCurrent={isCurrent} />
}

type IsCurrent = (token: string) => boolean

function PasswordResetLink({ token, isCurrent }: { token: string; isCurrent: IsCurrent }) {
  const i18n = useI18n()
  const { t } = i18n
  const check = useLinkCheck("password-reset", token)
  const [expired, setExpired] = useState(false)
  const status = expired ? "unusable" : check.status
  const setup = useQuery({ queryKey: ["setup"], queryFn: api.setup, enabled: status === "unusable" })
  const canRecover = status === "unusable" && setup.data?.password_reset_available === true
  const [done, setDone] = useState(false)
  const panel = panelFor(status, done)
  return (
    <AuthFrame
      heading={t("auth.passwordReset.heading")}
      intro={t("auth.passwordReset.intro")}
      panelTitle={t(panel.title)}
      panelNote={t(canRecover ? "auth.passwordReset.unusable.recoveryBody" : panel.note)}
      icon={KeyRound}
    >
      {status === "checking" && <p role="status">{t("auth.passwordReset.checking")}</p>}
      {status === "failed" && (
        <div className="inline-error" role="alert">
          {apiErrorMessage(i18n, check.error)}
        </div>
      )}
      {done && <p className="sr-only" role="status">{t("auth.passwordReset.done.title")}</p>}
      <ResetActions done={done} canRecover={canRecover} status={status} />
      {status === "usable" && !done && <ResetForm token={token} isCurrent={isCurrent} onDone={() => setDone(true)} onExpired={() => setExpired(true)} />}
    </AuthFrame>
  )
}

function ResetActions({ done, canRecover, status }: { done: boolean; canRecover: boolean; status: LinkStatus }) {
  const { t } = useI18n()
  if (!done && status !== "unusable" && status !== "failed") return null
  return (
    <div className="auth-form">
      {canRecover && <Button size="lg" asChild><a href="/forgot-password">{t("auth.forgotPassword.requestNew")}</a></Button>}
      <Button size="lg" variant={canRecover ? "outline" : "default"} asChild>
        <a href="/">{t("auth.passwordReset.signIn")}</a>
      </Button>
    </div>
  )
}

type ResetFormProps = { token: string; isCurrent: IsCurrent; onDone: () => void; onExpired: () => void }

function ResetForm({ token, isCurrent, onDone, onExpired }: ResetFormProps) {
  const i18n = useI18n()
  const { t } = i18n
  const [passwords, setPasswords] = useState({ password: "", confirmation: "" })
  const reset = useMutation({
    mutationFn: () => api.resetPassword(token, passwords.password),
    onError: (error) => {
      if (isCurrent(token) && error instanceof ApiError && error.code === "link_unusable") onExpired()
    },
    onSuccess: () => {
      // A newer link was opened while this one was answered: its token stays in the address.
      if (!isCurrent(token)) return
      // The link is spent; it should not stay in the address bar.
      window.history.replaceState(null, "", window.location.pathname)
      onDone()
    },
  })
  const ready = passwords.password.length <= 1024 && newPasswordReady(passwords.password, passwords.confirmation)

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (ready && !reset.isPending) reset.mutate()
  }

  return (
    <form onSubmit={submit} className="auth-form">
      <NewPasswordFields
        password={passwords.password}
        confirmation={passwords.confirmation}
        onChange={setPasswords}
        passwordLabel={t("auth.passwordReset.newPassword")}
        maxLength={1024}
      />
      {reset.error && (
        <div className="inline-error" role="alert">
          {apiErrorMessage(i18n, reset.error)}
        </div>
      )}
      <Button type="submit" size="lg" disabled={!ready || reset.isPending}>
        {reset.isPending ? t("auth.pleaseWait") : t("auth.passwordReset.submit")}
      </Button>
    </form>
  )
}
