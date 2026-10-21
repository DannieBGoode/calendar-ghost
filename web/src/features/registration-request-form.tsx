import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useId, useState, type SyntheticEvent } from "react"

import { ProviderSignInOptions } from "@/features/provider-sign-in-options"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { ApiError, api } from "@/lib/api"

type Props = {
  invitationToken?: string
  initialEmail?: string
  isCurrent?: (token: string) => boolean
  onEmail?: (email: string) => void
  onUnavailable?: () => void
}

/** Public and invited requests use the same bounded email-only form and generic acceptance. */
export function RegistrationRequestForm({ invitationToken, initialEmail = "", isCurrent, onUnavailable, onEmail }: Props) {
  const i18n = useI18n()
  const { t } = i18n
  const id = useId()
  const client = useQueryClient()
  const [email, setEmail] = useState(initialEmail)
  const request = useMutation({
    mutationFn: () => api.requestRegistration(email.trim(), invitationToken ?? null),
    onSuccess: () => client.invalidateQueries({ queryKey: ["setup"], refetchType: "none" }),
    onError: (error) => {
      if (invitationToken && !isCurrent?.(invitationToken)) return
      if (error instanceof ApiError && error.status === 503) onUnavailable?.()
    },
  })
  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (invitationToken && !isCurrent?.(invitationToken)) return
    if (email.trim() && email.trim().length <= 254 && !request.isPending) request.mutate()
  }
  if (request.isSuccess) return (
    <div className="auth-form">
      <p role="status" tabIndex={-1} ref={(node) => { node?.focus() }}>{t("auth.signUp.sent")}</p>
      <Button variant="outline" onClick={() => request.reset()}>{t("auth.signUp.retry")}</Button>
    </div>
  )
  return (
    <form onSubmit={submit} className="auth-form">
      <div className="field-stack">
        <Label htmlFor={id}>{t("auth.email")}</Label>
        <Input id={id} type="email" autoComplete="email" maxLength={254} value={email} onChange={(event) => { setEmail(event.target.value); onEmail?.(event.target.value) }} required autoFocus />
      </div>
      {invitationToken && <ProviderSignInOptions invitation={{ token: invitationToken, email }} isCurrent={() => isCurrent?.(invitationToken) === true} />}
      {request.error && <p className="inline-error" role="alert">{request.error instanceof ApiError && request.error.status === 503 ? t("auth.signUp.unavailable") : apiErrorMessage(i18n, request.error)}</p>}
      <Button type="submit" size="lg" disabled={!email.trim() || request.isPending}>{t(request.isPending ? "auth.pleaseWait" : "auth.signUp.submit")}</Button>
    </form>
  )
}
