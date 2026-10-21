import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef, useState, type SyntheticEvent } from "react"

import { CurrentPasswordField } from "@/components/current-password-field"
import { Button } from "@/components/ui/button"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { ApiError, api } from "@/lib/api"

type Props = { token: string; current: () => boolean; onDone: () => void; onExpired: () => void }

export function EmailChangeConfirm({ token, current, onDone, onExpired }: Props) {
  const i18n = useI18n()
  const { t } = i18n
  const client = useQueryClient()
  const [password, setPassword] = useState("")
  const field = useRef<HTMLInputElement>(null)
  const confirm = useMutation({
    mutationFn: () => {
      const request = api.confirmEmailChange(token, password)
      setPassword("")
      return request
    },
    retry: false, gcTime: 0,
    onSuccess: () => {
      if (!current()) return
      window.history.replaceState(null, "", window.location.pathname)
      onDone()
      void client.invalidateQueries({ queryKey: ["session"] })
      void client.invalidateQueries({ queryKey: ["own-email-change"] })
    },
    onError: (error) => {
      if (!current()) return
      if (error instanceof ApiError && error.code === "email_change_proof_unusable") onExpired()
      else field.current?.focus()
    },
  })
  const ready = password.length > 0 && password.length <= 1024
  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (ready && !confirm.isPending && current()) confirm.mutate()
  }
  return (
    <form className="auth-form" onSubmit={submit} aria-busy={confirm.isPending}>
      <CurrentPasswordField ref={field} id="confirm-email-password" value={password} onChange={setPassword} invalid={!!confirm.error} errorId={confirm.error ? "confirm-email-error" : undefined} />
      {confirm.error && <p id="confirm-email-error" className="inline-error" role="alert">{apiErrorMessage(i18n, confirm.error)}</p>}
      <Button type="submit" size="lg" aria-disabled={!ready || confirm.isPending}>{t(confirm.isPending ? "auth.pleaseWait" : "auth.emailChange.confirm")}</Button>
    </form>
  )
}

export function EmailChangeSwitchAccount({ current }: { current: () => boolean }) {
  const i18n = useI18n()
  const { t } = i18n
  const client = useQueryClient()
  const logout = useMutation({
    mutationFn: api.logOut, retry: false,
    onSuccess: () => { if (current()) void client.resetQueries({ queryKey: ["session"] }) },
  })
  return <><Button size="lg" variant="outline" aria-disabled={logout.isPending} onClick={() => { if (!logout.isPending && current()) logout.mutate() }}>{t(logout.isPending ? "auth.pleaseWait" : "auth.emailChange.switchAccount")}</Button>{logout.error && <p className="inline-error" role="alert">{apiErrorMessage(i18n, logout.error)}</p>}</>
}
