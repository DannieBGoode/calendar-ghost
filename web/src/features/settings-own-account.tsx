import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef, useState, type SyntheticEvent } from "react"

import { CurrentPasswordField } from "@/components/current-password-field"
import { NewPasswordFields } from "@/components/new-password-fields"
import { Button } from "@/components/ui/button"
import { OwnEmailItem } from "@/features/settings-own-email"
import { InstantSyncItem } from "@/features/settings-instant-sync"
import { SelfDeletionItem } from "@/features/settings-self-deletion"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api, type SignedInUser } from "@/lib/api"
import { EMAIL_NOTIFICATIONS_HELP_URL } from "@/lib/brand"
import { newPasswordReady } from "@/lib/passwords"
import { isAdministrator } from "@/lib/people"
import { useDisclosureFocus } from "@/lib/use-disclosure-focus"

type Announce = (message: string) => void

/**
 * The signed-in User's own sign-in, email notifications, Instant Sync, and deletion; every User has it.
 * `onOpenPeople` opens the People page, where an administrator names another one.
 */
export function OwnAccountSection({
  user,
  sendsEmail,
  onOpenPeople,
}: {
  user: SignedInUser
  sendsEmail: boolean
  onOpenPeople: () => void
}) {
  const { t } = useI18n()
  const [message, setMessage] = useState("")
  return (
    <section className="settings-section" aria-labelledby="own-account-title">
      <div className="section-heading">
        <div>
          <h2 id="own-account-title">{t("settings.ownAccount.title")}</h2>
          <p>{t("settings.ownAccount.intro")}</p>
        </div>
      </div>
      <div className="settings-list">
        <OwnEmailItem email={user.email} onDone={setMessage} />
        <PasswordItem onDone={setMessage} />
        <EmailNotificationsItem user={user} sendsEmail={sendsEmail} onDone={setMessage} />
        <InstantSyncItem user={user} onDone={setMessage} />
        <SelfDeletionItem onOpenPeople={onOpenPeople} />
      </div>
      {/* Always present, so a screen reader announces each message as it arrives. */}
      <p role="status" className={message ? undefined : "sr-only"}>
        {message}
      </p>
    </section>
  )
}

function PasswordItem({ onDone }: { onDone: Announce }) {
  const queryClient = useQueryClient()
  const i18n = useI18n()
  const { t } = i18n
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState("")
  const [passwords, setPasswords] = useState({ password: "", confirmation: "" })
  const toggle = useRef<HTMLButtonElement>(null)
  const first = useRef<HTMLInputElement>(null)
  useDisclosureFocus(open, first, toggle)
  const save = useMutation({
    mutationFn: () => api.changeOwnPassword(current, passwords.password),
    onSuccess: () => {
      setOpen(false)
      setCurrent("")
      setPasswords({ password: "", confirmation: "" })
      onDone(t("settings.ownAccount.password.saved"))
      void queryClient.invalidateQueries({ queryKey: ["own-email-change"] })
    },
  })
  const ready = current.length > 0 && newPasswordReady(passwords.password, passwords.confirmation)

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (ready) save.mutate()
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
          <p>{t("settings.ownAccount.password.body")}</p>
        </div>
        {!open && (
          <Button ref={toggle} id="own-password-toggle" type="button" variant="outline" onClick={() => setOpen(true)}>
            {t("settings.ownAccount.password.change")}
          </Button>
        )}
      </div>
      {open && (
        <form className="setting-form" onSubmit={submit}>
          <CurrentPasswordField ref={first} id="own-current-password" value={current} onChange={setCurrent} />
          <NewPasswordFields
            idPrefix="own-new-password"
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

/**
 * The shared preference for Incident Notifications and Plan notices, once Plan Hold is active.
 * The Web UI keeps every incident in Activity; PR 3 adds the visible Plan notice fallback.
 * Where the installation sends no email there is nothing to choose, so it says who can set it up.
 */
function EmailNotificationsItem({
  user,
  sendsEmail,
  onDone,
}: {
  user: SignedInUser
  sendsEmail: boolean
  onDone: Announce
}) {
  return sendsEmail ? <EmailNotificationsChoice user={user} onDone={onDone} /> : <EmailNotificationsUnavailable user={user} />
}

function EmailNotificationsUnavailable({ user }: { user: SignedInUser }) {
  const { t } = useI18n()
  const administrator = isAdministrator(user)
  return (
    <div className="setting-item">
      <div className="setting-row">
        <div>
          <h3>{t("settings.ownAccount.notifications.title")}</h3>
          <p>
            {administrator
              ? t("settings.ownAccount.notifications.unavailableAdministrator")
              : t("settings.ownAccount.notifications.unavailable")}
          </p>
        </div>
        {administrator && (
          <a className="text-link" href={EMAIL_NOTIFICATIONS_HELP_URL} target="_blank" rel="noreferrer">
            {t("settings.ownAccount.notifications.setUpEmail")}
            <span className="sr-only">{t("common.opensInNewTab")}</span>
          </a>
        )}
      </div>
    </div>
  )
}

function EmailNotificationsChoice({ user, onDone }: { user: SignedInUser; onDone: Announce }) {
  const i18n = useI18n()
  const { t } = i18n
  const queryClient = useQueryClient()
  const change = useMutation({
    mutationFn: (notify: boolean) => api.setIncidentEmails(notify),
    onSuccess: async (changed) => {
      onDone(changed.notify_by_email ? t("settings.ownAccount.notifications.on") : t("settings.ownAccount.notifications.off"))
      await queryClient.invalidateQueries({ queryKey: ["session"] })
    },
  })
  const saved = change.data?.notify_by_email ?? user.notify_by_email
  const checked = change.isPending ? change.variables : saved
  return (
    <div className="setting-item">
      <div className="setting-row">
        <div>
          <h3>{t("settings.ownAccount.notifications.title")}</h3>
          <p>{t("settings.ownAccount.notifications.body")}</p>
        </div>
        <label className="checkbox-row" htmlFor="own-email-notifications">
          <input
            id="own-email-notifications"
            type="checkbox"
            checked={checked}
            disabled={change.isPending}
            onChange={(event) => change.mutate(event.target.checked)}
          />
          <span>
            <strong>{t("settings.ownAccount.notifications.label")}</strong>
          </span>
        </label>
      </div>
      {change.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, change.error)}
        </p>
      )}
    </div>
  )
}
