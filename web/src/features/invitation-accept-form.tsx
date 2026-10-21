import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useId, useState, type SyntheticEvent } from "react"

import { NewPasswordFields } from "@/components/new-password-fields"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { ApiError, api } from "@/lib/api"
import { newPasswordReady } from "@/lib/passwords"

type Props = {
  token: string
  isCurrent: (token: string) => boolean
  onSignedIn: () => void
  email: string
  onEmail: (email: string) => void
  onRecheck: () => void
  onUnusable: (error: ApiError) => void
}

export function InvitationAcceptForm({ token, isCurrent, onSignedIn, email, onEmail, onRecheck, onUnusable }: Props) {
  const i18n = useI18n()
  const { t } = i18n
  const emailId = useId()
  const queryClient = useQueryClient()
  const [passwords, setPasswords] = useState({ password: "", confirmation: "" })
  const accept = useMutation({
    onError: (error) => {
      if (!isCurrent(token) || !(error instanceof ApiError)) return
      if (error.code === "invitation_verification_required") onRecheck()
      if (error.status === 410) onUnusable(error)
    },
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
    if (isCurrent(token) && ready && !accept.isPending) accept.mutate()
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
          onChange={(event) => onEmail(event.target.value)}
          maxLength={254}
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
