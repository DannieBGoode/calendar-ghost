import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef, useState, type RefObject, type SyntheticEvent } from "react"

import { CurrentPasswordField } from "@/components/current-password-field"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { api } from "@/lib/api"

type Props = {
  mode: Awaited<ReturnType<typeof api.ownEmailChange>>["mode"]
  available: boolean
  first: RefObject<HTMLInputElement | null>
  current: () => boolean
  onClose: () => void
  onDone: (message: string) => void
  onRefresh: () => Promise<void>
}

export function OwnEmailForm({ mode, available, first, current, onClose, onDone, onRefresh }: Props) {
  const i18n = useI18n()
  const { t } = i18n
  const client = useQueryClient()
  const [next, setNext] = useState("")
  const [password, setPassword] = useState("")
  const passwordField = useRef<HTMLInputElement>(null)
  const verified = mode === "verified"
  const save = useMutation({
    mutationFn: async () => {
      const email = next.trim()
      const request = verified ? api.requestEmailChange(email, password) : api.setOwnEmail(email, password)
      setPassword("")
      await request
      return { verified, email }
    },
    retry: false, gcTime: 0,
    onSuccess: async (result) => {
      if (!current()) return
      onClose()
      onDone(result.verified ? t("settings.ownAccount.email.requested") : t("settings.ownAccount.email.saved", { email: result.email }))
      await client.invalidateQueries({ queryKey: ["session"] })
    },
    onError: () => { if (current()) passwordField.current?.focus() },
    onSettled: () => { if (current()) void onRefresh() },
  })
  const ready = available && next.trim().length > 0 && password.length > 0 && password.length <= 1024
  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (ready && !save.isPending && current()) save.mutate()
  }
  return (
    <form className="setting-form" onSubmit={submit} aria-busy={save.isPending}>
      <p className="field-hint">{t(verified ? "settings.ownAccount.email.verifyNote" : "settings.ownAccount.email.directNote")}</p>
      {verified && <p className="field-hint">{t("settings.ownAccount.email.cooldown", { count: 60 })}</p>}
      <div className="field-stack">
        <Label htmlFor="own-email">{t("settings.ownAccount.email.newLabel")}</Label>
        <Input ref={first} id="own-email" type="email" autoComplete="email" value={next} onChange={(event) => setNext(event.target.value)} maxLength={254} required />
      </div>
      <CurrentPasswordField ref={passwordField} id="own-email-password" value={password} onChange={setPassword} invalid={!!save.error} errorId={save.error ? "own-email-error" : undefined} />
      {save.error && <p id="own-email-error" className="field-error" role="alert">{apiErrorMessage(i18n, save.error)}</p>}
      <div className="setting-form-actions">
        <Button type="submit" aria-disabled={!ready || save.isPending}>{t(saveLabel(save.isPending, verified))}</Button>
        <Button type="button" variant="ghost" aria-disabled={save.isPending} onClick={() => { if (!save.isPending) onClose() }}>{t("settings.ownAccount.cancel")}</Button>
      </div>
    </form>
  )
}


function saveLabel(pending: boolean, verified: boolean): MessageKey {
  if (pending) return "auth.pleaseWait"
  return verified ? "settings.ownAccount.email.request" : "settings.ownAccount.email.save"
}
