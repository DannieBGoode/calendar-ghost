import { useMutation } from "@tanstack/react-query"
import { KeyRound } from "lucide-react"
import { useState, type SyntheticEvent } from "react"

import { AuthFrame } from "@/components/auth-frame"
import { NewPasswordFields } from "@/components/new-password-fields"
import { Button } from "@/components/ui/button"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { api } from "@/lib/api"
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
 * Where a User opens the Password Reset Link an administrator passed on and chooses a new
 * password. The administrator never sees or sets it.
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
  const { status, error } = useLinkCheck("password-reset", token)
  const [done, setDone] = useState(false)
  const panel = panelFor(status, done)
  const offerSignIn = done || status === "unusable"
  return (
    <AuthFrame
      heading={t("auth.passwordReset.heading")}
      intro={t("auth.passwordReset.intro")}
      panelTitle={t(panel.title)}
      panelNote={t(panel.note)}
      icon={KeyRound}
    >
      {status === "checking" && <p role="status">{t("auth.passwordReset.checking")}</p>}
      {status === "failed" && (
        <div className="inline-error" role="alert">
          {apiErrorMessage(i18n, error)}
        </div>
      )}
      {offerSignIn && (
        <Button size="lg" asChild>
          <a href="/">{t("auth.passwordReset.signIn")}</a>
        </Button>
      )}
      {status === "usable" && !done && <ResetForm token={token} isCurrent={isCurrent} onDone={() => setDone(true)} />}
    </AuthFrame>
  )
}

function ResetForm({ token, isCurrent, onDone }: { token: string; isCurrent: IsCurrent; onDone: () => void }) {
  const i18n = useI18n()
  const { t } = i18n
  const [passwords, setPasswords] = useState({ password: "", confirmation: "" })
  const reset = useMutation({
    mutationFn: () => api.resetPassword(token, passwords.password),
    onSuccess: () => {
      // A newer link was opened while this one was answered: its token stays in the address.
      if (!isCurrent(token)) return
      // The link is spent; it should not stay in the address bar.
      window.history.replaceState(null, "", window.location.pathname)
      onDone()
    },
  })
  const ready = newPasswordReady(passwords.password, passwords.confirmation)

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (ready) reset.mutate()
  }

  return (
    <form onSubmit={submit} className="auth-form">
      <NewPasswordFields
        password={passwords.password}
        confirmation={passwords.confirmation}
        onChange={setPasswords}
        passwordLabel={t("auth.passwordReset.newPassword")}
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
