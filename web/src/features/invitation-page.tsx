import { useMutation, useQueryClient } from "@tanstack/react-query"
import { UserPlus } from "lucide-react"
import { useId, useState, type SyntheticEvent } from "react"

import { AuthFrame } from "@/components/auth-frame"
import { NewPasswordFields } from "@/components/new-password-fields"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api } from "@/lib/api"
import { newPasswordReady } from "@/lib/passwords"
import { useLinkCheck, useLinkToken } from "@/lib/use-link-check"

/**
 * Where an invited person becomes a User: they choose the email and password they sign in with.
 * The Invitation's token is in the address's fragment, so it never reaches a server log.
 */
export function InvitationPage({ onSignedIn }: { onSignedIn: () => void }) {
  const { token, isCurrent } = useLinkToken()
  // A newer link starts over: its own check, an empty form, and no earlier refusal.
  return <InvitationLink key={token} token={token} isCurrent={isCurrent} onSignedIn={onSignedIn} />
}

type LinkProps = { token: string; isCurrent: (token: string) => boolean; onSignedIn: () => void }

function InvitationLink({ token, isCurrent, onSignedIn }: LinkProps) {
  const i18n = useI18n()
  const { t } = i18n
  const { status, error } = useLinkCheck("invitation", token)
  const refused = status === "unusable"
  return (
    <AuthFrame
      heading={t("auth.invitation.heading")}
      intro={t("auth.invitation.intro")}
      panelTitle={refused ? t("auth.invitation.unusable.title") : t("auth.invitation.panel")}
      panelNote={refused ? t("auth.invitation.unusable.body") : t("auth.invitation.note")}
      icon={UserPlus}
    >
      {status === "checking" && <p role="status">{t("auth.invitation.checking")}</p>}
      {status === "failed" && (
        <div className="inline-error" role="alert">
          {apiErrorMessage(i18n, error)}
        </div>
      )}
      {refused && (
        <Button size="lg" asChild>
          <a href="/">{t("auth.invitation.signIn")}</a>
        </Button>
      )}
      {status === "usable" && <AcceptForm token={token} isCurrent={isCurrent} onSignedIn={onSignedIn} />}
    </AuthFrame>
  )
}

function AcceptForm({ token, isCurrent, onSignedIn }: LinkProps) {
  const i18n = useI18n()
  const { t } = i18n
  const emailId = useId()
  const queryClient = useQueryClient()
  const [email, setEmail] = useState("")
  const [passwords, setPasswords] = useState({ password: "", confirmation: "" })
  const accept = useMutation({
    mutationFn: () => api.acceptInvitation(token, email.trim(), passwords.password),
    onSuccess: async (session) => {
      // A newer link was opened while this one was answered: that page is the one to finish.
      if (!isCurrent(token)) return
      queryClient.setQueryData(["session"], session)
      // The token is spent; it should not stay in the address bar or the history.
      window.history.replaceState(null, "", "/overview")
      await queryClient.invalidateQueries()
      onSignedIn()
    },
  })
  const ready = email.trim().length > 0 && newPasswordReady(passwords.password, passwords.confirmation)

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (ready) accept.mutate()
  }

  return (
    <form onSubmit={submit} className="auth-form">
      <div className="field-stack">
        <Label htmlFor={emailId}>{t("auth.email")}</Label>
        <Input
          id={emailId}
          type="email"
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          autoFocus
        />
      </div>
      <NewPasswordFields
        password={passwords.password}
        confirmation={passwords.confirmation}
        onChange={setPasswords}
      />
      {accept.error && (
        <div className="inline-error" role="alert">
          {apiErrorMessage(i18n, accept.error)}
        </div>
      )}
      <Button type="submit" size="lg" disabled={!ready || accept.isPending}>
        {accept.isPending ? t("auth.pleaseWait") : t("auth.invitation.submit")}
      </Button>
    </form>
  )
}
