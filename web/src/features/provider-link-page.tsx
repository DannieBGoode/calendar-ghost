import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { LockKeyhole } from "lucide-react"
import { useRef, useState, type SyntheticEvent } from "react"
import { AuthFrame } from "@/components/auth-frame"
import { CurrentPasswordField } from "@/components/current-password-field"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/i18n/provider"
import { api, type SessionStatus } from "@/lib/api"

export function ProviderLinkPage() {
  const { t } = useI18n()
  const pending = useQuery({ queryKey: ["provider-link-pending"], queryFn: api.pendingProviderLink, retry: false, gcTime: 0, staleTime: 0 })
  return <AuthFrame heading={t("auth.provider.linkHeading")} intro={t("auth.provider.linkIntro")} panelTitle={t("auth.provider.linkPanel")} panelNote={t("auth.provider.linkNote")} icon={LockKeyhole}>
    {pending.isPending && <p role="status">{t("auth.pleaseWait")}</p>}
    {pending.data?.password_required && !pending.error ? <ProviderLinkForm /> : !pending.isPending && <p className="inline-error" role="alert">{t("auth.provider.expired")}</p>}
    <p className="field-hint provider-link-newcomer">{t("auth.provider.newcomer")}</p>
    <div className="setting-form-actions mt-4"><Button variant="outline" asChild><a href="/sign-up">{t("auth.signUp.heading")}</a></Button><Button variant="ghost" asChild><a href="/sign-in">{t("auth.signIn")}</a></Button></div>
  </AuthFrame>
}

function ProviderLinkForm() {
  const { t } = useI18n()
  const client = useQueryClient()
  const owner = client.getQueryData<SessionStatus>(["session"])?.user?.id
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const first = useRef<HTMLInputElement>(null)
  const confirm = useMutation({
    mutationFn: async () => {
      const request = api.confirmProviderLink(email.trim(), password)
      setPassword("")
      await request
      if (client.getQueryData<SessionStatus>(["session"])?.user?.id === owner) window.location.assign("/overview")
    }, retry: false, gcTime: 0,
    onError: () => first.current?.focus(),
  })
  const ready = email.trim().length > 0 && password.length > 0
  function submit(event: SyntheticEvent<HTMLFormElement>) { event.preventDefault(); if (ready && !confirm.isPending) confirm.mutate() }
  return <form className="auth-form" onSubmit={submit}>
    <div className="field-stack"><Label htmlFor="provider-link-email">{t("auth.email")}</Label><Input ref={first} id="provider-link-email" type="email" autoComplete="username" value={email} onChange={event => setEmail(event.target.value)} maxLength={254} required /></div>
    <CurrentPasswordField id="provider-link-password" value={password} onChange={setPassword} />
    {confirm.error && <p className="inline-error" role="alert">{t("auth.provider.confirmFailed")}</p>}
    <Button type="submit" aria-disabled={!ready || confirm.isPending}>{t(confirm.isPending ? "auth.pleaseWait" : "auth.provider.confirm")}</Button>
  </form>
}
