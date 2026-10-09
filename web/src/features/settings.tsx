import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, ShieldAlert } from "lucide-react"
import { useEffect, useState } from "react"

import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import { Button } from "@/components/ui/button"
import { NativeSelect } from "@/components/ui/native-select"
import { useTheme } from "@/components/theme-provider"
import { useI18n } from "@/i18n/provider"
import { api, type SessionStatus } from "@/lib/api"
import {
  OAUTH_OUTCOME_MESSAGES,
  clearAuthorizationStart,
  oauthOutcome,
  recordAuthorizationStart,
  type OAuthOutcome,
} from "@/lib/oauth-redirect"
import { isAdministrator } from "@/lib/people"
import type { DarkPalette, ThemePreference } from "@/lib/theme"
import { useGoogleReturn } from "@/lib/use-google-return"
import { useRegistration } from "@/lib/use-registration"
import { cn } from "@/lib/utils"
import { AccountsSection } from "@/features/settings-accounts"
import { IntegrationsSection } from "@/features/settings-integrations"
import { OwnAccountSection } from "@/features/settings-own-account"
import { PeopleSection } from "@/features/settings-people"
import { RegistrationSection } from "@/features/settings-registration"
import { StorageSection } from "@/features/settings-storage"

export { GoogleReturnHelp } from "@/features/settings-google-return"
export { IntegrationsSection } from "@/features/settings-integrations"

export function SettingsPage() {
  const { t } = useI18n()
  const google = useQuery({ queryKey: ["google-configuration"], queryFn: api.googleConfiguration })
  const session = useQuery({ queryKey: ["session"], queryFn: api.session })
  if (google.isPending || session.isPending) return <PageSkeleton label={t("settings.page.loading")} />
  if (google.error || session.error) {
    const retry = () => void Promise.all([google.refetch(), session.refetch()])
    return <LoadFailure title={t("settings.page.loadFailure")} onRetry={retry} />
  }
  return (
    <SettingsView
      googleConfigured={google.data.configured}
      redirectUri={google.data.redirect_uri}
      session={session.data}
    />
  )
}

type SettingsArrival = {
  outcome: OAuthOutcome | null
  /** The account Google returned with, or the one a stopped rule pointed to. */
  accountId: string | null
  /** Rules that resumed because the account was reauthorized. */
  resumed: number
}

const ARRIVAL_PARAMS = ["google", "account", "resumed"]

/** What brought the administrator here, read once; returning ends the authorization attempt. */
function useSettingsArrival(): SettingsArrival {
  const [arrival] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    // Any outcome, even one this version cannot name, ends the attempt started here.
    if (params.get("google")) clearAuthorizationStart()
    return {
      outcome: oauthOutcome(window.location.search),
      accountId: params.get("account"),
      resumed: Number(params.get("resumed")) || 0,
    }
  })
  useEffect(() => {
    // A reload should not announce the same connection, or point at the same account, again.
    const url = new URL(window.location.href)
    if (!ARRIVAL_PARAMS.some((name) => url.searchParams.has(name))) return
    for (const name of ARRIVAL_PARAMS) url.searchParams.delete(name)
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`)
  }, [])
  return arrival
}

function SettingsView({
  googleConfigured,
  redirectUri,
  session,
}: {
  googleConfigured: boolean
  redirectUri: string | null
  session: SessionStatus
}) {
  const { t } = useI18n()
  const { outcome, accountId, resumed } = useSettingsArrival()
  const returnHelp = useGoogleReturn(redirectUri)
  const { user } = session
  const administrator = isAdministrator(user)

  return (
    <div className="page-section settings-page">
      <div>
        <h1>{t("settings.page.title")}</h1>
        <p className="page-intro">{t("settings.page.intro")}</p>
      </div>

      {outcome && <OAuthOutcomeNotice outcome={outcome} resumed={resumed} googleConfigured={googleConfigured} />}

      <AccountsSection
        googleConfigured={googleConfigured}
        justConnected={outcome === "connected"}
        focusAccountId={accountId}
        returnHelp={returnHelp}
      />

      {user && <OwnAccountSection user={user} sendsEmail={session.installation_sends_email} />}

      {administrator && user && <AdministrationSections currentUserId={user.id} />}

      {administrator && <StorageSection />}

      <IntegrationsSection administrator={administrator} />

      <AppearanceSection />
    </div>
  )
}

/**
 * Who can join and, unless only the administrator may use this installation, the people here.
 * Only an Installation Administrator sees them; the server refuses everyone else.
 */
function AdministrationSections({ currentUserId }: { currentUserId: string }) {
  const registration = useRegistration()
  const policy = registration.registration.data?.policy
  return (
    <>
      <RegistrationSection commands={registration} />
      {policy === "invitation_only" && <PeopleSection currentUserId={currentUserId} />}
    </>
  )
}

/** The notice for the outcome the OAuth callback reported; failures offer to try again. */
function OAuthOutcomeNotice({
  outcome,
  resumed,
  googleConfigured,
}: {
  outcome: OAuthOutcome
  resumed: number
  googleConfigured: boolean
}) {
  const { t } = useI18n()
  const messages = OAUTH_OUTCOME_MESSAGES[outcome]
  const succeeded = outcome === "connected"
  return (
    <div
      className={cn("oauth-feedback", succeeded ? "oauth-feedback-success" : "oauth-feedback-warning")}
      role={outcome === "authorization_failed" ? "alert" : "status"}
    >
      {succeeded ? <CheckCircle2 aria-hidden="true" /> : <ShieldAlert aria-hidden="true" />}
      <div>
        <h2>{t(messages.title)}</h2>
        <p>
          {succeeded && resumed > 0 ? t("settings.oauthOutcome.connected.resumed", { count: resumed }) : t(messages.body)}
        </p>
      </div>
      {!succeeded && googleConfigured && (
        <Button variant="outline" asChild>
          <a href="/api/v1/oauth/google/start" onClick={() => recordAuthorizationStart()}>
            {t("settings.oauthOutcome.tryAgain")}
          </a>
        </Button>
      )}
    </div>
  )
}

function AppearanceSection() {
  const { t } = useI18n()
  const { preference, setPreference, darkPalette, setDarkPalette } = useTheme()
  return (
    <section className="settings-section" aria-labelledby="appearance-title">
      <div className="section-heading">
        <div>
          <h2 id="appearance-title">{t("settings.appearance.title")}</h2>
          <p>{t("settings.appearance.intro")}</p>
        </div>
      </div>
      <div className="settings-list">
        <div className="setting-row">
          <div>
            <h3 id="theme-title">{t("settings.appearance.theme.title")}</h3>
            <p>{t("settings.appearance.theme.body")}</p>
          </div>
          <div className="appearance-control">
            <NativeSelect
              id="theme-preference"
              aria-labelledby="theme-title"
              value={preference}
              onChange={(event) => setPreference(event.target.value as ThemePreference)}
            >
              <option value="system">{t("settings.appearance.theme.system")}</option>
              <option value="light">{t("settings.appearance.theme.light")}</option>
              <option value="dark">{t("settings.appearance.theme.dark")}</option>
            </NativeSelect>
          </div>
        </div>
        <div className="setting-row">
          <div>
            <h3 id="dark-palette-title">{t("settings.appearance.darkPalette.title")}</h3>
            <p>{t("settings.appearance.darkPalette.body")}</p>
          </div>
          <div className="appearance-control">
            <NativeSelect
              id="dark-palette"
              aria-labelledby="dark-palette-title"
              value={darkPalette}
              onChange={(event) => setDarkPalette(event.target.value as DarkPalette)}
            >
              <option value="twilight">{t("settings.appearance.darkPalette.twilight")}</option>
              <option value="midnight">{t("settings.appearance.darkPalette.midnight")}</option>
            </NativeSelect>
          </div>
        </div>
      </div>
    </section>
  )
}
