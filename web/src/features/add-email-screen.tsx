import { useMutation, useQueryClient } from "@tanstack/react-query"
import { AtSign } from "lucide-react"
import { useId, useState, type SyntheticEvent } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { ThemeToggle } from "@/components/theme-toggle"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api } from "@/lib/api"
import { PRODUCT_NAME } from "@/lib/brand"

/**
 * The step the upgraded first User must take before anything else: add the email they sign in
 * with from now on. Signing in by password alone ends once it is saved.
 */
export function AddEmailScreen() {
  const i18n = useI18n()
  const { t } = i18n
  const id = useId()
  const queryClient = useQueryClient()
  const [email, setEmail] = useState("")
  const save = useMutation({
    mutationFn: () => api.setOwnEmail(email.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries()
    },
  })
  const signOut = useMutation({ mutationFn: api.logOut, onSuccess: () => queryClient.clear() })

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (email.trim()) save.mutate()
  }

  return (
    <main className="auth-shell">
      <div className="auth-theme-control">
        <ThemeToggle />
      </div>
      <section className="auth-intro" aria-labelledby="add-email-title">
        <GhostMark className="brand-mark" />
        <p className="product-name">{PRODUCT_NAME}</p>
        <h1 id="add-email-title">{t("auth.addEmail.heading")}</h1>
        <p className="auth-copy">{t("auth.addEmail.intro")}</p>
      </section>
      <section className="auth-form-panel" aria-label={t("auth.addEmail.panel")}>
        <div className="form-heading">
          <AtSign aria-hidden="true" />
          <div>
            <h2>{t("auth.addEmail.panel")}</h2>
            <p>{t("auth.addEmail.note")}</p>
          </div>
        </div>
        <form onSubmit={submit} className="auth-form">
          <div className="field-stack">
            <Label htmlFor={id}>{t("auth.email")}</Label>
            <Input
              id={id}
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              autoFocus
            />
          </div>
          {save.error && <div className="inline-error" role="alert">{apiErrorMessage(i18n, save.error)}</div>}
          <Button type="submit" size="lg" disabled={!email.trim() || save.isPending}>
            {save.isPending ? t("auth.pleaseWait") : t("auth.addEmail.submit")}
          </Button>
          <Button type="button" variant="ghost" onClick={() => signOut.mutate()} disabled={signOut.isPending}>
            {t("auth.addEmail.signOut")}
          </Button>
        </form>
      </section>
    </main>
  )
}
