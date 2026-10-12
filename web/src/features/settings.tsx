import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, ShieldAlert } from "lucide-react"
import { useEffect, useState } from "react"

import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import { api, type CalendarProvider, type SessionStatus } from "@/lib/api"
import {
  DEFAULT_SETTINGS_TAB,
  SETTINGS_ARRIVAL_PARAMS,
  type OpenSettingsTab,
  type SettingsTab,
} from "@/lib/navigation"
import {
  OAUTH_OUTCOME_MESSAGES,
  clearAuthorizationStart,
  oauthOutcome,
  oauthProvider,
  recordAuthorizationStart,
  type OAuthOutcome,
} from "@/lib/oauth-redirect"
import { isAdministrator } from "@/lib/people"
import { accountNoun, connectUrl, providerDisplayName, providerOf } from "@/lib/providers"
import { useOAuthReturn } from "@/lib/use-oauth-return"
import { useRegistration } from "@/lib/use-registration"
import { cn } from "@/lib/utils"
import { AccountsSection } from "@/features/settings-accounts"
import { AppearanceSection } from "@/features/settings-appearance"
import { IntegrationsSection } from "@/features/settings-integrations"
import { OwnAccountSection } from "@/features/settings-own-account"
import { RegistrationSection } from "@/features/settings-registration"
import { StorageSection } from "@/features/settings-storage"
import { SettingsTabs } from "@/features/settings-tabs"

export { OAuthReturnHelp } from "@/features/settings-oauth-return"
export { IntegrationsSection } from "@/features/settings-integrations"

/** Settings at one tab. Every tab waits for the calendar providers and the session. */
export function SettingsPage({
  tab,
  onOpenTab,
  onOpenPeople,
}: {
  tab: SettingsTab
  onOpenTab: OpenSettingsTab
  onOpenPeople: () => void
  /** Where the signed-in User goes to act on a problem administrators can see. */
}) {
  const { t } = useI18n()
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const session = useQuery({ queryKey: ["session"], queryFn: api.session })
  if (providers.isPending || session.isPending) return <PageSkeleton label={t("settings.page.loading")} />
  if (providers.error || session.error) {
    const retry = () => void Promise.all([providers.refetch(), session.refetch()])
    return <LoadFailure title={t("settings.page.loadFailure")} onRetry={retry} />
  }
  return (
    <SettingsView
      providers={providers.data}
      session={session.data}
      tab={tab}
      onOpenTab={onOpenTab}
      onOpenPeople={onOpenPeople}
    />
  )
}

type SettingsArrival = {
  outcome: OAuthOutcome | null
  /** The Provider Kind whose connection flow returned. */
  provider: string | null
  /** The account a provider returned with, or the one a stopped rule pointed to. */
  accountId: string | null
  /** Rules that resumed because the account was reauthorized. */
  resumed: number
}

/** What brought the administrator here, read once; returning ends the authorization attempt. */
function useSettingsArrival(): SettingsArrival {
  const [arrival] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    // Any outcome, even one this version cannot name, ends the attempt started here.
    if (params.get("oauth")) clearAuthorizationStart()
    return {
      outcome: oauthOutcome(window.location.search),
      provider: oauthProvider(window.location.search),
      accountId: params.get("account"),
      resumed: Number(params.get("resumed")) || 0,
    }
  })
  useEffect(() => {
    // A reload should not announce the same connection, or point at the same account, again.
    const url = new URL(window.location.href)
    if (!SETTINGS_ARRIVAL_PARAMS.some((name) => url.searchParams.has(name))) return
    for (const name of SETTINGS_ARRIVAL_PARAMS) url.searchParams.delete(name)
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`)
  }, [])
  return arrival
}

type SettingsViewProps = {
  providers: CalendarProvider[]
  session: SessionStatus
  tab: SettingsTab
  onOpenTab: OpenSettingsTab
  onOpenPeople: () => void
}

function SettingsView({ session, tab, onOpenTab, onOpenPeople, ...connections }: SettingsViewProps) {
  const { t } = useI18n()
  const { user } = session
  const administrator = isAdministrator(user)
  // Someone else opening Administration's address sees Your account, as Settings itself shows.
  const shown = tab === "administration" && !administrator ? DEFAULT_SETTINGS_TAB : tab

  return (
    <div className="page-section settings-page">
      <div>
        <h1>{t("settings.page.title")}</h1>
        <p className="page-intro">{t(administrator ? "settings.page.introAdministrator" : "settings.page.intro")}</p>
      </div>
      <SettingsTabs current={shown} administrator={administrator} onOpen={onOpenTab} />
      {shown === "account" && user && (
        <OwnAccountSection user={user} sendsEmail={session.installation_sends_email} onOpenPeople={onOpenPeople} />
      )}
      {shown === "account" && <AppearanceSection />}
      {shown === "connections" && <ConnectionsTab providers={connections.providers} administrator={administrator} />}
      {shown === "administration" && <AdministrationTab />}
    </div>
  )
}

/** Calendar accounts, with what brought the User back from a provider above them, and Integrations. */
function ConnectionsTab({ providers, administrator }: { providers: CalendarProvider[]; administrator: boolean }) {
  const { outcome, provider, accountId, resumed } = useSettingsArrival()
  const returnHelp = useOAuthReturn(providers)
  return (
    <>
      {outcome && <OAuthOutcomeNotice outcome={outcome} provider={provider} resumed={resumed} providers={providers} />}
      <AccountsSection
        providers={providers}
        justConnected={outcome === "connected"}
        focusAccountId={accountId}
        returnHelp={returnHelp}
      />
      <IntegrationsSection administrator={administrator} />
    </>
  )
}

/**
 * Who can join, and storage. Only an Installation Administrator sees them; the server refuses
 * everyone else. The people here and their invitations have their own page.
 */
function AdministrationTab() {
  const registration = useRegistration()
  return (
    <>
      <RegistrationSection commands={registration} />
      <StorageSection />
    </>
  )
}

/** The notice for the outcome the OAuth callback reported; failures offer to try again. */
function OAuthOutcomeNotice({
  outcome,
  provider,
  resumed,
  providers,
}: {
  outcome: OAuthOutcome
  provider: string | null
  resumed: number
  providers: CalendarProvider[]
}) {
  const i18n = useI18n()
  const { t } = i18n
  const messages = OAUTH_OUTCOME_MESSAGES[outcome]
  const succeeded = outcome === "connected"
  const names = { account: accountNoun(i18n, provider, providers), provider: providerDisplayName(i18n, provider, providers) }
  const retry = providerOf(providers, provider)
  return (
    <div
      className={cn("oauth-feedback", succeeded ? "oauth-feedback-success" : "oauth-feedback-warning")}
      role={outcome === "authorization_failed" ? "alert" : "status"}
    >
      {succeeded ? <CheckCircle2 aria-hidden="true" /> : <ShieldAlert aria-hidden="true" />}
      <div>
        <h2>{t(messages.title, names)}</h2>
        <p>
          {succeeded && resumed > 0 ? t("settings.oauthOutcome.connected.resumed", { count: resumed }) : t(messages.body)}
        </p>
      </div>
      {!succeeded && retry && (
        <Button variant="outline" asChild>
          <a href={connectUrl(retry)} onClick={() => recordAuthorizationStart(retry.kind)}>
            {t("settings.oauthOutcome.tryAgain")}
          </a>
        </Button>
      )}
    </div>
  )
}
