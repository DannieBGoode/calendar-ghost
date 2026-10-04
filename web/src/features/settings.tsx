import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, ShieldAlert } from "lucide-react"
import { useEffect, useState } from "react"

import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import { Button } from "@/components/ui/button"
import { NativeSelect } from "@/components/ui/native-select"
import { useTheme } from "@/components/theme-provider"
import { api } from "@/lib/api"
import { clearAuthorizationStart, recordAuthorizationStart } from "@/lib/oauth-redirect"
import type { DarkPalette, ThemePreference } from "@/lib/theme"
import { useGoogleReturn } from "@/lib/use-google-return"
import { AccountsSection } from "@/features/settings-accounts"
import { StorageSection } from "@/features/settings-storage"

export { GoogleReturnHelp } from "@/features/settings-google-return"

export function SettingsPage() {
  const google = useQuery({ queryKey: ["google-configuration"], queryFn: api.googleConfiguration })
  if (google.isPending) return <PageSkeleton label="Loading settings" />
  if (google.error) return <LoadFailure title="Settings could not load" onRetry={() => void google.refetch()} />
  return <SettingsView googleConfigured={google.data.configured} redirectUri={google.data.redirect_uri} />
}

/** The outcome Google returned with, read once; returning ends the authorization attempt. */
function useOAuthOutcome(): string | null {
  const [oauthOutcome] = useState(() => {
    const outcome = new URLSearchParams(window.location.search).get("google")
    if (outcome) clearAuthorizationStart()
    return outcome
  })
  useEffect(() => {
    // A reload should not announce the same connection again.
    const url = new URL(window.location.href)
    if (!url.searchParams.has("google")) return
    url.searchParams.delete("google")
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`)
  }, [])
  return oauthOutcome
}

function SettingsView({
  googleConfigured,
  redirectUri,
}: {
  googleConfigured: boolean
  redirectUri: string | null
}) {
  const oauthOutcome = useOAuthOutcome()
  const returnHelp = useGoogleReturn(redirectUri)

  return (
    <div className="page-section settings-page">
      <div>
        <h1>Settings</h1>
        <p className="page-intro">
          Accounts and storage for this installation. Appearance applies to this browser only.
        </p>
      </div>

      <OAuthOutcomeFeedback outcome={oauthOutcome} googleConfigured={googleConfigured} />

      <AccountsSection
        googleConfigured={googleConfigured}
        justConnected={oauthOutcome === "connected"}
        returnHelp={returnHelp}
      />

      <StorageSection />

      <AppearanceSection />
    </div>
  )
}

function OAuthOutcomeFeedback({ outcome, googleConfigured }: { outcome: string | null; googleConfigured: boolean }) {
  return (
    <>
      {outcome === "connected" && (
        <div className="oauth-feedback oauth-feedback-success" role="status">
          <CheckCircle2 aria-hidden="true" />
          <div>
            <h2>Google account connected</h2>
            <p>Calendar permissions were confirmed and the account is ready for Directional Sync Rules.</p>
          </div>
        </div>
      )}
      {outcome === "calendar_permission_required" && (
        <div className="oauth-feedback oauth-feedback-warning" role="status">
          <ShieldAlert aria-hidden="true" />
          <div>
            <h2>Calendar access wasn’t granted</h2>
            <p>
              No account was connected. Calendar-list and event permissions are required to
              discover calendars and run Directional Sync Rules.
            </p>
          </div>
          {googleConfigured && (
            <Button variant="outline" asChild>
              <a href="/api/v1/oauth/google/start" onClick={() => recordAuthorizationStart()}>Try again</a>
            </Button>
          )}
        </div>
      )}
      {outcome === "authorization_failed" && (
        <div className="oauth-feedback oauth-feedback-warning" role="alert">
          <ShieldAlert aria-hidden="true" />
          <div>
            <h2>Google authorization could not be completed</h2>
            <p>The account was not connected. Try again, then use Check access to confirm permissions.</p>
          </div>
          {googleConfigured && (
            <Button variant="outline" asChild>
              <a href="/api/v1/oauth/google/start" onClick={() => recordAuthorizationStart()}>Try again</a>
            </Button>
          )}
        </div>
      )}
    </>
  )
}

function AppearanceSection() {
  const { preference, setPreference, darkPalette, setDarkPalette } = useTheme()
  return (
    <section className="settings-section" aria-labelledby="appearance-title">
      <div className="section-heading">
        <div>
          <h2 id="appearance-title">Appearance</h2>
          <p>Saved in this browser only.</p>
        </div>
      </div>
      <div className="settings-list">
        <div className="setting-row">
          <div>
            <h3 id="theme-title">Theme</h3>
            <p>Follow this device, or keep the interface light or dark.</p>
          </div>
          <div className="appearance-control">
            <NativeSelect
              id="theme-preference"
              aria-labelledby="theme-title"
              value={preference}
              onChange={(event) => setPreference(event.target.value as ThemePreference)}
            >
              <option value="system">Device setting</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </NativeSelect>
          </div>
        </div>
        <div className="setting-row">
          <div>
            <h3 id="dark-palette-title">Dark palette</h3>
            <p>The colors used whenever the interface is dark.</p>
          </div>
          <div className="appearance-control">
            <NativeSelect
              id="dark-palette"
              aria-labelledby="dark-palette-title"
              value={darkPalette}
              onChange={(event) => setDarkPalette(event.target.value as DarkPalette)}
            >
              <option value="twilight">Twilight (indigo)</option>
              <option value="midnight">Midnight (blue)</option>
            </NativeSelect>
          </div>
        </div>
      </div>
    </section>
  )
}
