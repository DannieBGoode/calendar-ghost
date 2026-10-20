import { useMutation, useQuery } from "@tanstack/react-query"
import { KeyRound } from "lucide-react"
import { useId, useState, type SyntheticEvent } from "react"

import { AuthFrame } from "@/components/auth-frame"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { ApiError, api } from "@/lib/api"

/** Email recovery is public, independently of the browser's current session. */
export function ForgotPasswordPage() {
  const i18n = useI18n()
  const { t } = i18n
  const setup = useQuery({ queryKey: ["setup"], queryFn: api.setup })
  const available = setup.data?.password_reset_available === true
  return (
    <AuthFrame
      heading={t("auth.forgotPassword.heading")}
      intro={t("auth.forgotPassword.intro")}
      panelTitle={t(available || setup.isPending ? "auth.forgotPassword.panel" : "auth.forgotPassword.unavailable.title")}
      panelNote={t(available || setup.isPending ? "auth.forgotPassword.note" : "auth.forgotPassword.unavailable.body")}
      icon={KeyRound}
    >
      {setup.isPending && <p role="status">{t("auth.pleaseWait")}</p>}
      {setup.error && <div className="inline-error" role="alert">{apiErrorMessage(i18n, setup.error)}</div>}
      <div className="mt-8 flex flex-col gap-6">
        {available && <RequestForm />}
        <Button variant="ghost" size="lg" asChild><a href="/">{t("auth.forgotPassword.signIn")}</a></Button>
      </div>
    </AuthFrame>
  )
}

function RequestForm() {
  const i18n = useI18n()
  const { t } = i18n
  const id = useId()
  const [email, setEmail] = useState("")
  const request = useMutation({ mutationFn: () => api.requestPasswordReset(email.trim()) })

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (email.trim() && !request.isPending) request.mutate()
  }

  function retry() {
    request.reset()
  }

  if (request.isSuccess) {
    return (
      <div className="flex flex-col gap-6">
        <p role="status" tabIndex={-1} ref={(node) => { node?.focus() }}>{t("auth.forgotPassword.sent")}</p>
        <Button type="button" variant="outline" onClick={retry}>{t("auth.forgotPassword.retry")}</Button>
      </div>
    )
  }
  const unavailable = request.error instanceof ApiError && request.error.code === "identity_email_not_configured"
  return (
    <form onSubmit={submit} className="flex flex-col gap-6">
      <div className="field-stack">
        <Label htmlFor={id}>{t("auth.email")}</Label>
        <Input id={id} type="email" autoComplete="email" maxLength={254} value={email}
          onChange={(event) => setEmail(event.target.value)} required autoFocus />
      </div>
      {request.error && <div className="inline-error" role="alert">{unavailable
        ? t("auth.forgotPassword.unavailable.body") : apiErrorMessage(i18n, request.error)}</div>}
      <Button type="submit" size="lg" disabled={!email.trim() || request.isPending}>
        {request.isPending ? t("auth.pleaseWait") : t("auth.forgotPassword.submit")}
      </Button>
    </form>
  )
}
