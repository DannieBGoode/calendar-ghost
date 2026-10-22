import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef, useState, type SyntheticEvent } from "react"

import { CurrentPasswordField } from "@/components/current-password-field"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { ProviderSignInOptions } from "@/features/provider-sign-in-options"
import { api } from "@/lib/api"

/** Sign in in place: the proof stays in component memory and the fragment, never a return URL. */
export function EmailChangeSignIn({ isCurrent }: { isCurrent: () => boolean }) {
  const i18n = useI18n()
  const { t } = i18n
  const client = useQueryClient()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const field = useRef<HTMLInputElement>(null)
  const login = useMutation({
    mutationFn: () => {
      const request = api.logIn(email.trim(), password)
      setPassword("")
      return request
    },
    retry: false, gcTime: 0,
    onSuccess: () => { if (isCurrent()) void client.invalidateQueries({ queryKey: ["session"] }) },
    onError: () => { if (isCurrent()) field.current?.focus() },
  })
  const ready = email.trim().length > 0 && password.length > 0 && password.length <= 1024
  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (ready && !login.isPending && isCurrent()) login.mutate()
  }
  return (
    <>
    <ProviderSignInOptions isCurrent={isCurrent}><p className="field-hint">{t("auth.provider.emailChange")}</p></ProviderSignInOptions>
    <form className="auth-form" onSubmit={submit} aria-busy={login.isPending}>
      <p>{t("auth.emailChange.signIn")}</p>
      <div className="field-stack">
        <Label htmlFor="email-change-sign-in">{t("auth.email")}</Label>
        <Input id="email-change-sign-in" type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={254} required />
      </div>
      <CurrentPasswordField ref={field} id="email-change-sign-in-password" value={password} onChange={setPassword} invalid={!!login.error} errorId={login.error ? "email-change-sign-in-error" : undefined} />
      {login.error && <p id="email-change-sign-in-error" className="inline-error" role="alert">{apiErrorMessage(i18n, login.error)}</p>}
      <Button type="submit" size="lg" aria-disabled={!ready || login.isPending}>{t(login.isPending ? "auth.pleaseWait" : "auth.signIn")}</Button>
      <p className="field-hint">{t("auth.emailChange.reopen")}</p>
    </form></>
  )
}
