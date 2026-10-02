import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Activity, CalendarCheck2, LogOut, Menu, Settings2, Waypoints, X } from "lucide-react"
import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { Button } from "@/components/ui/button"
import { ThemeToggle } from "@/components/theme-toggle"
import { AuthScreen } from "@/features/auth-screen"
import { Dashboard } from "@/features/dashboard"
import { api } from "@/lib/api"
import { APP_VERSION, PRODUCT_NAME, documentTitle } from "@/lib/brand"
import {
  appLocationFromPathname,
  appPathForLocation,
  appPathForView,
  isKnownAppPath,
  isPlainLeftClick,
  type AppLocation,
  type AppView,
  type ViewOptions,
} from "@/lib/navigation"
import { cn } from "@/lib/utils"

const navItems: { id: AppView; label: string; icon: typeof Waypoints }[] = [
  { id: "overview", label: "Overview", icon: CalendarCheck2 },
  { id: "rules", label: "Rules", icon: Waypoints },
  { id: "activity", label: "Activity", icon: Activity },
  { id: "settings", label: "Settings", icon: Settings2 },
]

export default function App() {
  const setup = useQuery({ queryKey: ["setup"], queryFn: api.setup })
  const session = useQuery({
    queryKey: ["session"],
    queryFn: api.session,
    enabled: setup.data?.administrator_configured === true,
  })

  if (setup.isPending || (setup.data?.administrator_configured && session.isPending)) {
    return <div className="startup-loading" role="status" aria-label={`Loading ${PRODUCT_NAME}`}><GhostMark className="startup-ghost" /></div>
  }
  if (setup.error || session.error) {
    return <main className="fatal-state"><h1>{PRODUCT_NAME} is unavailable</h1><p>The browser could not reach the local service.</p><Button onClick={() => window.location.reload()}>Reload page</Button></main>
  }
  if (!setup.data.administrator_configured) return <AuthScreen mode="setup" />
  if (!session.data?.authenticated) return <AuthScreen mode="login" />
  return <AuthenticatedApp />
}
function AuthenticatedApp() {
  const [location, setLocation] = useState<AppLocation>(() =>
    appLocationFromPathname(window.location.pathname),
  )
  const view = location.view
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
  const logout = useMutation({ mutationFn: api.logOut, onSuccess: () => queryClient.clear() })

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
      setLocation(appLocationFromPathname(window.location.pathname))
      setMobileNav(false)
    }
    window.addEventListener("popstate", handlePopState)
    return () => window.removeEventListener("popstate", handlePopState)
  }, [])

  // A layout effect runs before the new view's own effects, so a view that focuses its heading
  // (Rule Details, the rule builder) refines this rather than being overridden by it.
  useLayoutEffect(() => {
    const title = navItems.find((item) => item.id === view)?.label ?? "Overview"
    document.title = documentTitle(location.ruleId ? "Rule" : title)
    if (navigated.current) main.current?.focus({ preventScroll: true })
  }, [view, location.ruleId])

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
    setLocation(next)
    setMobileNav(false)
    window.scrollTo(0, 0)
  }

  function changeView(next: AppView, options?: ViewOptions) {
    navigate({ view: next, ruleId: null }, options)
  }

  function openRule(ruleId: string, options?: ViewOptions) {
    navigate({ view: "rules", ruleId }, options)
  }

  function followSectionLink(event: MouseEvent<HTMLAnchorElement>, next: AppView) {
    if (!isPlainLeftClick(event)) return
    event.preventDefault()
    changeView(next)
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="wordmark" href={appPathForView("overview")} onClick={(event) => followSectionLink(event, "overview")} aria-label={`${PRODUCT_NAME} overview`}>
          <span className="wordmark-icon"><GhostMark /></span><span>{PRODUCT_NAME}</span>
        </a>
        <nav id="primary-nav" className={cn("primary-nav", mobileNav && "open")} aria-label="Primary navigation">
          {navItems.map((item) => {
            const Icon = item.icon
            return <a key={item.id} href={appPathForView(item.id)} className={cn("nav-item", view === item.id && "active")} onClick={(event) => followSectionLink(event, item.id)} aria-current={view === item.id ? "page" : undefined}><Icon /><span>{item.label}</span></a>
          })}
        </nav>
        <div className="topbar-actions">
          <ThemeToggle />
          <Button variant="ghost" onClick={() => logout.mutate()} disabled={logout.isPending} aria-label="Sign out"><LogOut /> <span className="desktop-only">Sign out</span></Button>
          <Button ref={menuButton} className="menu-button" variant="ghost" size="icon" onClick={() => setMobileNav((open) => !open)} aria-expanded={mobileNav} aria-controls="primary-nav" aria-label={mobileNav ? "Close navigation" : "Open navigation"}>{mobileNav ? <X /> : <Menu />}</Button>
        </div>
      </header>
      <main className="app-main" ref={main} tabIndex={-1}><Dashboard location={location} arrival={arrival} visit={visit} onViewChange={changeView} onOpenRule={openRule} /></main>
      <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
      <footer className="app-footer"><span>{PRODUCT_NAME}</span><span aria-hidden="true">·</span><span>v{APP_VERSION}</span><span aria-hidden="true">·</span><span>Runs on this device</span><span aria-hidden="true">·</span><a href="/api/docs">API documentation</a></footer>
    </div>
  )
}
