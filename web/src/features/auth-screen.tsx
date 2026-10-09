import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Check, LockKeyhole } from "lucide-react"
import { useId, useState, type ReactNode, type SyntheticEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ThemeToggle } from "@/components/theme-toggle"
import { GhostMark } from "@/components/ghost-mark"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { rich } from "@/i18n/rich"
import type { I18n } from "@/i18n/translator"
import { api } from "@/lib/api"
import { LICENSE_URL, PRODUCT_NAME, SOURCE_URL } from "@/lib/brand"

type AuthScreenProps = {
  mode: "setup" | "login"
  /** The upgraded first User has no email yet, so sign-in may leave it empty. */
  passwordOnly?: boolean
}

export function AuthScreen({ mode, passwordOnly = false }: AuthScreenProps) {
  const i18n = useI18n()
  const { t } = i18n
  const passwordId = useId()
  const confirmationId = useId()
  const isSetup = mode === "setup"
  const form = useCredentials(isSetup, passwordOnly)
  const { password, setPassword, confirmation, setConfirmation, mismatch, canSubmit, mutation } = form

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (canSubmit) mutation.mutate()
  }

  return (
    <main className="auth-shell">
      <div className="auth-theme-control">
        <ThemeToggle />
      </div>
      <AuthIntro isSetup={isSetup} />

      <AuthFormPanel isSetup={isSetup}>
        <form onSubmit={submit} className="auth-form">
          <EmailField value={form.email} required={form.emailRequired} onChange={form.setEmail} />
          <div className="field-stack">
            <Label htmlFor={passwordId}>{t("auth.password")}</Label>
            <Input
              id={passwordId}
              type="password"
              autoComplete={isSetup ? "new-password" : "current-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-describedby={`${passwordId}-hint`}
              required
              minLength={12}
            />
            <p id={`${passwordId}-hint`} className="field-hint">{t("auth.passwordHint")}</p>
          </div>
          {isSetup && (
            <ConfirmationField
              id={confirmationId}
              value={confirmation}
              mismatch={mismatch}
              onChange={setConfirmation}
            />
          )}
          {mutation.error && (
            <div className="inline-error" role="alert">{apiErrorMessage(i18n, mutation.error)}</div>
          )}
          <Button type="submit" size="lg" disabled={!canSubmit || mutation.isPending}>
            {submitLabel(i18n, isSetup, mutation.isPending)}
          </Button>
        </form>
      </AuthFormPanel>
    </main>
  )
}

function AuthIntro({ isSetup }: { isSetup: boolean }) {
  const { t } = useI18n()
  return (
    <section className="auth-intro" aria-labelledby="auth-title">
      <GhostMark className="brand-mark" />
      <p className="product-name">{PRODUCT_NAME}</p>
      <p className="auth-tagline">{t("auth.tagline")}</p>
      <h1 id="auth-title">{isSetup ? t("auth.setup.heading") : t("auth.login.heading")}</h1>
      <p className="auth-copy">{isSetup ? t("auth.setup.intro") : t("auth.login.intro")}</p>
      {isSetup && (
        <ul className="privacy-list" aria-label={t("auth.setup.privacyLabel")}>
          <li><Check aria-hidden="true" /> {t("auth.setup.privacy.runsHere")}</li>
          <li><Check aria-hidden="true" /> {t("auth.setup.privacy.noTelemetry")}</li>
          <li><Check aria-hidden="true" /> {t("auth.setup.privacy.localHistory")}</li>
        </ul>
      )}
    </section>
  )
}

function AuthFormPanel({ isSetup, children }: { isSetup: boolean; children: ReactNode }) {
  const { t } = useI18n()
  return (
    <section className="auth-form-panel" aria-label={isSetup ? t("auth.createAdministrator") : t("auth.signIn")}>
      <div className="form-heading">
        <LockKeyhole aria-hidden="true" />
        <div>
          <h2>{isSetup ? t("auth.createAdministrator") : t("auth.signInHeading")}</h2>
          <p>{isSetup ? t("auth.setup.emailNote") : t("auth.login.passwordNote")}</p>
        </div>
      </div>
      {children}
      <p className="auth-legal">
        {rich(t("auth.legal"), {
          license: (text) => (
            <a href={LICENSE_URL} target="_blank" rel="noreferrer">
              {text}
            </a>
          ),
          source: (text) => (
            <a href={SOURCE_URL} target="_blank" rel="noreferrer">
              {text}
            </a>
          ),
        })}
      </p>
    </section>
  )
}

/** What the form holds and whether it may be sent: setup needs every field, sign-in may omit
 * the email only while the upgraded first User has none. */
function useCredentials(isSetup: boolean, passwordOnly: boolean) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const emailRequired = isSetup || !passwordOnly
  const address = email.trim()
  const mutation = useMutation({
    mutationFn: () =>
      isSetup ? api.createAdmin(address, password) : api.logIn(address || null, password),
    onSuccess: async () => {
      await queryClient.invalidateQueries()
    },
  })
  const mismatch = isSetup && confirmation.length > 0 && password !== confirmation
  const complete = password.length >= 12 && (!emailRequired || address.length > 0)
  const canSubmit = complete && (!isSetup || password === confirmation)
  return { email, setEmail, password, setPassword, confirmation, setConfirmation, emailRequired, mismatch, canSubmit, mutation }
}

/** The email a User signs in with; optional only while the upgraded first User has none. */
function EmailField({
  value,
  required,
  onChange,
}: {
  value: string
  required: boolean
  onChange: (value: string) => void
}) {
  const { t } = useI18n()
  const id = useId()
  return (
    <div className="field-stack">
      <Label htmlFor={id}>{t("auth.email")}</Label>
      <Input
        id={id}
        type="email"
        autoComplete="username"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-describedby={required ? undefined : `${id}-hint`}
        required={required}
        autoFocus
      />
      {!required && <p id={`${id}-hint`} className="field-hint">{t("auth.login.passwordOnlyHint")}</p>}
    </div>
  )
}

function ConfirmationField({
  id,
  value,
  mismatch,
  onChange,
}: {
  id: string
  value: string
  mismatch: boolean
  onChange: (value: string) => void
}) {
  const { t } = useI18n()
  return (
    <div className="field-stack">
      <Label htmlFor={id}>{t("auth.confirmPassword")}</Label>
      <Input
        id={id}
        type="password"
        autoComplete="new-password"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={mismatch}
        required
      />
      {mismatch && <p className="field-error" role="alert">{t("auth.passwordMismatch")}</p>}
    </div>
  )
}

function submitLabel({ t }: I18n, isSetup: boolean, pending: boolean): string {
  if (pending) return t("auth.pleaseWait")
  return isSetup ? t("auth.createAdministrator") : t("auth.signIn")
}
