import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef, useState, type SyntheticEvent } from "react"
import { CurrentPasswordField } from "@/components/current-password-field"
import { NewPasswordFields } from "@/components/new-password-fields"
import { Button } from "@/components/ui/button"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api } from "@/lib/api"
import { newPasswordReady } from "@/lib/passwords"
import { useDisclosureFocus } from "@/lib/use-disclosure-focus"

export function PasswordItem({ hasPassword, currentOwner, onDone }: { hasPassword: boolean; currentOwner: () => boolean; onDone: (message: string) => void }) {
  const i18n = useI18n()
  const { t } = i18n
  const { open, setOpen, current, setCurrent, passwords, setPasswords, save, ready } = usePasswordForm(hasPassword, currentOwner, onDone)
  const toggle = useRef<HTMLButtonElement>(null)
  const first = useRef<HTMLInputElement>(null)
  useDisclosureFocus(open, first, toggle)

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (ready && !save.isPending && currentOwner()) save.mutate()
  }

  function cancel() {
    setOpen(false)
    setCurrent("")
    setPasswords({ password: "", confirmation: "" })
    save.reset()
  }

  return (
    <div className="setting-item">
      <div className="setting-row">
        <div>
          <h3>{t("settings.ownAccount.password.title")}</h3>
          <p>{t(hasPassword ? "settings.ownAccount.password.body" : "settings.signIn.firstPassword")}</p>
        </div>
        {!open && (
          <Button ref={toggle} id="own-password-toggle" type="button" variant="outline" onClick={() => setOpen(true)}>
            {t(hasPassword ? "settings.ownAccount.password.change" : "settings.signIn.setPassword")}
          </Button>
        )}
      </div>
      {open && (
        <form ref={element => { if (element && !hasPassword) first.current = element.querySelector<HTMLInputElement>("input") }} className="setting-form" onSubmit={submit}>
          {hasPassword && <CurrentPasswordField ref={first} id="own-current-password" value={current} onChange={setCurrent} />}
          <NewPasswordFields
            idPrefix="own-new-password"
            maxLength={256}
            password={passwords.password}
            confirmation={passwords.confirmation}
            onChange={setPasswords}
            passwordLabel={t("settings.ownAccount.password.newLabel")}
            confirmationLabel={t("settings.ownAccount.password.confirmLabel")}
          />
          {save.error && (
            <p className="field-error" role="alert">
              {apiErrorMessage(i18n, save.error)}
            </p>
          )}
          <div className="setting-form-actions">
            <Button type="submit" disabled={!ready || save.isPending}>
              {save.isPending ? t("auth.pleaseWait") : t("settings.ownAccount.password.save")}
            </Button>
            <Button type="button" variant="ghost" onClick={cancel}>
              {t("settings.ownAccount.cancel")}
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}


function usePasswordForm(hasPassword: boolean, currentOwner: () => boolean, onDone: (message: string) => void) {
  const queryClient = useQueryClient()
  const i18n = useI18n()
  const { t } = i18n
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState("")
  const [passwords, setPasswords] = useState({ password: "", confirmation: "" })
  const save = useMutation({
    mutationFn: () => {
      const request = hasPassword ? api.changeOwnPassword(current, passwords.password) : api.setOwnPassword(passwords.password)
      setCurrent("")
      setPasswords({ password: "", confirmation: "" })
      return request
    }, retry: false, gcTime: 0,
    onSuccess: () => {
      if (!currentOwner()) return
      setOpen(false)
      setCurrent("")
      setPasswords({ password: "", confirmation: "" })
      onDone(t(hasPassword ? "settings.ownAccount.password.saved" : "settings.signIn.passwordSet"))
      void queryClient.invalidateQueries({ queryKey: ["own-email-change"] })
      void queryClient.invalidateQueries({ queryKey: ["sign-in-methods"] })
    },
  })
  const ready = (!hasPassword || current.length > 0) && passwords.password.length <= 256 && newPasswordReady(passwords.password, passwords.confirmation)

  return { open, setOpen, current, setCurrent, passwords, setPasswords, save, ready }
}
