import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Check, LockKeyhole } from "lucide-react"
import { useId, useState, type ReactNode, type SyntheticEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ThemeToggle } from "@/components/theme-toggle"
import { GhostMark } from "@/components/ghost-mark"
import { api } from "@/lib/api"
import { LICENSE_URL, PRODUCT_NAME, SOURCE_URL, TAGLINE } from "@/lib/brand"

type AuthScreenProps = { mode: "setup" | "login" }

export function AuthScreen({ mode }: AuthScreenProps) {
  const passwordId = useId()
  const confirmationId = useId()
  const queryClient = useQueryClient()
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const isSetup = mode === "setup"

  const mutation = useMutation({
    mutationFn: () => (isSetup ? api.createAdmin(password) : api.logIn(password)),
    onSuccess: async () => {
      await queryClient.invalidateQueries()
    },
  })

  const mismatch = isSetup && confirmation.length > 0 && password !== confirmation
  const canSubmit = password.length >= 12 && (!isSetup || password === confirmation)

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
          <div className="field-stack">
            <Label htmlFor={passwordId}>Password</Label>
            <Input
              id={passwordId}
              type="password"
              autoComplete={isSetup ? "new-password" : "current-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-describedby={`${passwordId}-hint`}
              required
              minLength={12}
              autoFocus
            />
            <p id={`${passwordId}-hint`} className="field-hint">At least 12 characters.</p>
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
            <div className="inline-error" role="alert">{mutation.error.message}</div>
          )}
          <Button type="submit" size="lg" disabled={!canSubmit || mutation.isPending}>
            {submitLabel(isSetup, mutation.isPending)}
          </Button>
        </form>
      </AuthFormPanel>
    </main>
  )
}

function AuthIntro({ isSetup }: { isSetup: boolean }) {
  return (
    <section className="auth-intro" aria-labelledby="auth-title">
      <GhostMark className="brand-mark" />
      <p className="product-name">{PRODUCT_NAME}</p>
      <p className="auth-tagline">{TAGLINE}</p>
      <h1 id="auth-title">
        {isSetup ? "Your calendars, under your control." : "Welcome back."}
      </h1>
      <p className="auth-copy">
        {isSetup
          ? "Create the local administrator who can connect accounts, preview rules, and respond when synchronization needs attention."
          : "Sign in to check synchronization health and manage this installation."}
      </p>
      {isSetup && (
        <ul className="privacy-list" aria-label="Installation privacy">
          <li><Check aria-hidden="true" /> Runs on this device</li>
          <li><Check aria-hidden="true" /> No mandatory telemetry</li>
          <li><Check aria-hidden="true" /> Event history is local, not in a vendor cloud</li>
        </ul>
      )}
    </section>
  )
}

function AuthFormPanel({ isSetup, children }: { isSetup: boolean; children: ReactNode }) {
  return (
    <section className="auth-form-panel" aria-label={isSetup ? "Create administrator" : "Sign in"}>
      <div className="form-heading">
        <LockKeyhole aria-hidden="true" />
        <div>
          <h2>{isSetup ? "Create administrator" : "Administrator sign in"}</h2>
          <p>{isSetup ? "This password stays on your installation." : "Use your local administrator password."}</p>
        </div>
      </div>
      {children}
      <p className="auth-legal">
        © 2026 Calendar Ghost contributors · No warranty. Share and modify under the <a href={LICENSE_URL} target="_blank" rel="noreferrer">AGPLv3+ license</a>; view the <a href={SOURCE_URL} target="_blank" rel="noreferrer">source</a>.
      </p>
    </section>
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
  return (
    <div className="field-stack">
      <Label htmlFor={id}>Confirm password</Label>
      <Input
        id={id}
        type="password"
        autoComplete="new-password"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={mismatch}
        required
      />
      {mismatch && <p className="field-error" role="alert">Passwords do not match.</p>}
    </div>
  )
}

function submitLabel(isSetup: boolean, pending: boolean): string {
  if (pending) return "Please wait…"
  return isSetup ? "Create administrator" : "Sign in"
}
