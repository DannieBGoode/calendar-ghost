import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { ThemeToggle } from "@/components/theme-toggle"
import { PRODUCT_NAME } from "@/lib/brand"

/**
 * The sign-in screen's two panels, for pages someone opens without a session, such as an
 * Invitation or a Password Reset Link: the brand and an explanation, then the form.
 */
export function AuthFrame({
  heading,
  intro,
  panelTitle,
  panelNote,
  icon: Icon,
  children,
}: {
  heading: string
  intro: string
  panelTitle: string
  panelNote: string
  icon: LucideIcon
  children: ReactNode
}) {
  return (
    <main className="auth-shell">
      <div className="auth-theme-control">
        <ThemeToggle />
      </div>
      <section className="auth-intro" aria-labelledby="public-page-title">
        <GhostMark className="brand-mark" />
        <p className="product-name">{PRODUCT_NAME}</p>
        <h1 id="public-page-title">{heading}</h1>
        <p className="auth-copy">{intro}</p>
      </section>
      <section className="auth-form-panel" aria-labelledby="public-panel-title">
        <div className="form-heading">
          <Icon aria-hidden="true" />
          <div>
            <h2 id="public-panel-title">{panelTitle}</h2>
            <p>{panelNote}</p>
          </div>
        </div>
        {children}
      </section>
    </main>
  )
}
