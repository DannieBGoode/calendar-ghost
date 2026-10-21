import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api, type SessionStatus } from "@/lib/api"
import { SIGN_IN_NAMES, isSignInProvider } from "@/lib/sign-in-providers"

type Setting = Awaited<ReturnType<typeof api.signInProviderSettings>>[number]
export function SignInProvidersSection() {
  const i18n = useI18n()
  const { t } = i18n
  const settings = useQuery({ queryKey: ["sign-in-provider-settings"], queryFn: api.signInProviderSettings, staleTime: 0 })
  return <section className="settings-section" aria-labelledby="sign-in-providers-title"><div className="section-heading"><div><h2 id="sign-in-providers-title">{t("settings.signInProviders.title")}</h2><p>{t("settings.signInProviders.intro")}</p></div></div>
    {settings.isPending && <Skeleton className="h-24 w-full" />}
    {settings.error && <div className="inline-error" role="alert"><p>{apiErrorMessage(i18n, settings.error)}</p><Button variant="outline" onClick={() => void settings.refetch()}>{t("common.loadFailure.retry")}</Button></div>}
    {Array.isArray(settings.data) && <div className="settings-list">{settings.data.map(setting => <ProviderSettingRow key={setting.provider} setting={setting} />)}</div>}
  </section>
}

function ProviderSettingRow({ setting }: { setting: Setting }) {
  const i18n = useI18n()
  const { t } = i18n
  const client = useQueryClient()
  const owner = client.getQueryData<SessionStatus>(["session"])?.user?.id
  const change = useMutation({
    mutationFn: (enabled: boolean) => api.setSignInProvider(setting.provider, enabled), retry: false,
    onSuccess: () => {
      if (client.getQueryData<SessionStatus>(["session"])?.user?.id !== owner) return
      void client.invalidateQueries({ queryKey: ["sign-in-provider-settings"] })
      void client.invalidateQueries({ queryKey: ["sign-in-providers"] })
    },
  })
  if (!isSignInProvider(setting.provider)) return null
  const name = t(SIGN_IN_NAMES[setting.provider])
  const label = `sign-in-provider-${setting.provider}`
  return <div className="setting-item"><div className="setting-row"><div><h3 id={label}>{name}</h3><p>{t(setting.available ? "settings.signInProviders.ready" : "settings.signInProviders.unavailable")}</p></div><Switch aria-labelledby={label} checked={change.isPending ? change.variables : setting.enabled} pending={change.isPending} disabled={!setting.available && !setting.enabled} onCheckedChange={enabled => change.mutate(enabled)} stateLabels={{ on: t("settings.signInProviders.on"), off: t("settings.signInProviders.off") }} /></div>
    <details className="provider-setup"><summary>{t("settings.signInProviders.setup", { provider: name })}</summary><p>{t("settings.signInProviders.client")}</p>{setting.callback_uri ? <><p>{t("settings.signInProviders.callback")}</p><code className="provider-callback">{setting.callback_uri}</code></> : <p>{t("settings.signInProviders.origin")}</p>}<p>{t("settings.signInProviders.scopes")}</p></details>
    {change.error && <div className="field-error" role="alert"><p>{apiErrorMessage(i18n, change.error)}</p><p>{t("settings.signInProviders.recovery")}</p></div>}
  </div>
}
