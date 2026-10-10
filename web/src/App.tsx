import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Activity, CalendarCheck2, LogOut, Menu, Settings2, Users, Waypoints, X } from "lucide-react"
import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { Button } from "@/components/ui/button"
import { ThemeToggle } from "@/components/theme-toggle"
import { AddEmailScreen } from "@/features/add-email-screen"
import { AuthScreen } from "@/features/auth-screen"
import { Dashboard } from "@/features/dashboard"
import { InvitationPage } from "@/features/invitation-page"
import { PasswordResetPage } from "@/features/password-reset-page"
import { rich } from "@/i18n/rich"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { api, type SessionStatus, type SetupStatus } from "@/lib/api"
import { APP_VERSION, HELP_URL, LICENSE_URL, PRODUCT_NAME, SOURCE_URL, documentTitle } from "@/lib/brand"
import {
  appLocationFromPathname,
  appLocationFromUrl,
  appPathForLocation,
  appPathForView,
  isKnownAppPath,
  isPlainLeftClick,
  type AppLocation,
  type AppView,
  type SettingsTab,
  type ViewOptions,
  withSettingsTab,
} from "@/lib/navigation"
import { publicPageAt } from "@/lib/public-links"
import { useAdministratorFlag } from "@/lib/use-administrator-flag"
import { usePeopleAccess } from "@/lib/use-people-access"
import { useUserScopedCache } from "@/lib/use-user-cache"
import { cn } from "@/lib/utils"

const navItems: { id: AppView; labelKey: MessageKey; icon: typeof Waypoints }[] = [
  { id: "overview", labelKey: "app.nav.overview", icon: CalendarCheck2 },
  { id: "rules", labelKey: "app.nav.rules", icon: Waypoints },
  { id: "activity", labelKey: "app.nav.activity", icon: Activity },
  { id: "people", labelKey: "app.nav.people", icon: Users },
  { id: "settings", labelKey: "app.nav.settings", icon: Settings2 },
]

export default function App() {
  // A link to pass on opens its own page, before any session; accepting an Invitation signs in.
  const [publicPage, setPublicPage] = useState(() => publicPageAt(window.location.pathname))
  if (publicPage === "invitation") return <InvitationPage onSignedIn={() => setPublicPage(null)} />
  if (publicPage === "password-reset") return <PasswordResetPage />
  return <SessionGate />
}

/** Waits for the setup and session state, then shows the sign-in steps or the signed-in app. */
function SessionGate() {
  const { t } = useI18n()
  useUserScopedCache()
  const setup = useQuery({ queryKey: ["setup"], queryFn: api.setup })
  const configured = setup.data?.administrator_configured === true
  const session = useQuery({
    queryKey: ["session"],
    queryFn: api.session,
    enabled: configured,
  })

  if (setup.isPending || (configured && session.isPending)) {
    return <div className="startup-loading" role="status" aria-label={t("app.loading")}><GhostMark className="startup-ghost" /></div>
  }
  if (setup.error || session.error) {
    return <main className="fatal-state"><h1>{t("app.unavailable.title")}</h1><p>{t("app.unavailable.body")}</p><Button onClick={() => window.location.reload()}>{t("app.unavailable.reload")}</Button></main>
  }
  return <SignInGate setup={setup.data} session={session.data} />
}

/** Setup, sign-in, or the add-email step, until a User with an email is signed in. */
function SignInGate({ setup, session }: { setup: SetupStatus; session: SessionStatus | undefined }) {
  if (!setup.administrator_configured) return <AuthScreen mode="setup" />
  if (!session?.authenticated) return <AuthScreen mode="login" passwordOnly={setup.password_only_sign_in} />
  if (session.user?.email === null) return <AddEmailScreen />
  // Keyed by the User, so another User signing in drops everything shown or typed for the last
  // one: a revealed token, an open dialog, a copied link.
  return <AuthenticatedApp key={session.user?.id} />
}

function AuthenticatedApp() {
  const i18n = useI18n()
  const { t } = i18n
  const [requested, setLocation] = useState<AppLocation>(() =>
    appLocationFromUrl(window.location.pathname, window.location.search),
  )
  const peopleAccess = usePeopleAccess()
  // Someone the People page is not for, or anyone under Only me, finds Overview at its address,
  // as at any unknown one.
  const peopleClosed = requested.view === "people" && peopleAccess === "closed"
  const location: AppLocation = peopleClosed ? { view: "overview", ruleId: null } : requested
  const view = location.view
  const shownNavItems = navItems.filter((item) => item.id !== "people" || peopleAccess === "open")
  // Only what the administrator must fix raises it; people's own problems stay on People quietly.
  const administratorFlag = useAdministratorFlag(peopleAccess === "open")
  const [mobileNav, setMobileNav] = useState(false)
  const [arrival, setArrival] = useState<ViewOptions>({})
  // Counts arrivals so views that read the address, such as Activity's filters, start fresh on
  // every navigation, including back, forward, and links to the page already shown.
  const [visit, setVisit] = useState(0)
  const [announcement, setAnnouncement] = useState("")
  const main = useRef<HTMLElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const navigated = useRef(false)
  const queryClient = useQueryClient()
  const logout = useMutation({ mutationFn: api.logOut, onSuccess: () => queryClient.resetQueries() })

  useEffect(() => {
    if (!isKnownAppPath(window.location.pathname)) {
      const current = appLocationFromPathname(window.location.pathname)
      window.history.replaceState(
        null,
        "",
        `${appPathForLocation(current)}${window.location.search}`,
      )
    }
    const handlePopState = () => {
      navigated.current = true
      setVisit((count) => count + 1)
      setArrival({})
      setLocation(appLocationFromUrl(window.location.pathname, window.location.search))
      setMobileNav(false)
    }
    window.addEventListener("popstate", handlePopState)
    return () => window.removeEventListener("popstate", handlePopState)
  }, [])

  useEffect(() => {
    if (peopleClosed) window.history.replaceState(null, "", appPathForView("overview"))
  }, [peopleClosed])

  // A layout effect runs before the new view's own effects, so a view that focuses its heading
  // (Rule Details, the rule builder) refines this rather than being overridden by it.
  useLayoutEffect(() => {
    const title = location.ruleId
      ? t("app.ruleTitle")
      : t(navItems.find((item) => item.id === view)?.labelKey ?? "app.nav.overview")
    document.title = documentTitle(i18n, title)
    if (navigated.current) main.current?.focus({ preventScroll: true })
  }, [view, location.ruleId, i18n, t])

  useEffect(() => {
    // The live region stays mounted across views; filling it after arrival makes the notice
    // reliably announced even though the view that shows it has just mounted.
    const clear = window.setTimeout(() => setAnnouncement(""), 0)
    const fill = window.setTimeout(() => setAnnouncement(arrival.notice ?? ""), 60)
    return () => {
      window.clearTimeout(clear)
      window.clearTimeout(fill)
    }
  }, [arrival])

  useEffect(() => {
    if (!mobileNav) return
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      setMobileNav(false)
      menuButton.current?.focus()
    }
    document.addEventListener("keydown", close)
    return () => document.removeEventListener("keydown", close)
  }, [mobileNav])

  function navigate(next: AppLocation, options: ViewOptions = {}) {
    const nextPath = `${appPathForLocation(next)}${options.search ?? ""}`
    if (`${window.location.pathname}${window.location.search}` !== nextPath || window.location.hash) {
      window.history.pushState(null, "", nextPath)
    }
    navigated.current = true
    setVisit((count) => count + 1)
    setArrival(options)
    setLocation(withSettingsTab(next, options.search ?? ""))
    setMobileNav(false)
    window.scrollTo(0, 0)
  }

  function changeView(next: AppView, options?: ViewOptions) {
    const tab = next === "settings" && options?.settingsTab ? { settingsTab: options.settingsTab } : {}
    navigate({ view: next, ruleId: null, ...tab }, options)
  }

  function openRule(ruleId: string, options?: ViewOptions) {
    navigate({ view: "rules", ruleId }, options)
  }

  function openPerson(personId: string) {
    navigate({ view: "people", ruleId: null, personId })
  }

  function openSettingsTab(settingsTab: SettingsTab) {
    navigate({ view: "settings", ruleId: null, settingsTab })
  }

  function followSectionLink(event: MouseEvent<HTMLAnchorElement>, next: AppView) {
    if (!isPlainLeftClick(event)) return
    event.preventDefault()
    changeView(next)
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="wordmark" href={appPathForView("overview")} onClick={(event) => followSectionLink(event, "overview")} aria-label={t("app.wordmarkLabel")}>
          <span className="wordmark-icon"><GhostMark /></span><span>{PRODUCT_NAME}</span>
        </a>
        <nav id="primary-nav" className={cn("primary-nav", mobileNav && "open")} aria-label={t("app.nav.primaryLabel")}>
          {shownNavItems.map((item) => {
            const Icon = item.icon
            const flag = item.id === "people" && administratorFlag
            return <a key={item.id} href={appPathForView(item.id)} className={cn("nav-item", view === item.id && "active")} onClick={(event) => followSectionLink(event, item.id)} aria-current={view === item.id ? "page" : undefined}><Icon /><span>{t(item.labelKey)}</span>{flag && <><span className="nav-flag" aria-hidden="true" /><span className="sr-only">{t("app.nav.needsYou")}</span></>}</a>
          })}
        </nav>
        <div className="topbar-actions">
          <ThemeToggle />
          <Button variant="ghost" onClick={() => logout.mutate()} disabled={logout.isPending} aria-label={t("app.signOut")}><LogOut /> <span className="desktop-only">{t("app.signOut")}</span></Button>
          <Button ref={menuButton} className="menu-button" variant="ghost" size="icon" onClick={() => setMobileNav((open) => !open)} aria-expanded={mobileNav} aria-controls="primary-nav" aria-label={mobileNav ? t("app.nav.close") : t("app.nav.open")}>{mobileNav ? <X /> : <Menu />}</Button>
        </div>
      </header>
      <main className="app-main" ref={main} tabIndex={-1}><Dashboard location={location} arrival={arrival} visit={visit} onViewChange={changeView} onOpenRule={openRule} onOpenSettingsTab={openSettingsTab} onOpenPerson={openPerson} /></main>
      <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
      <AppFooter />
    </div>
  )
}

function AppFooter() {
  const { t } = useI18n()
  return (
    <footer className="app-footer">
      <span>{PRODUCT_NAME}</span>
      <span>{t("app.footer.version", { version: APP_VERSION })}</span>
      <span>{t("app.footer.runsHere")}</span>
      <a href="/api/docs">{t("app.footer.apiDocs")}</a>
      <a href={HELP_URL} target="_blank" rel="noreferrer">
        {t("app.footer.help")}
      </a>
      <span className="legal-notice">
        {rich(t("app.footer.legal"), {
          license: (text) => (
            <a href={LICENSE_URL} target="_blank" rel="noreferrer">
              {text}
            </a>
          ),
        })}
      </span>
      <a href={SOURCE_URL} target="_blank" rel="noreferrer">
        {t("app.footer.source")}
      </a>
    </footer>
  )
}
