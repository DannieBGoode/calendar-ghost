import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { OwnEmailItem } from "@/features/settings-own-email"
import { InstantSyncItem } from "@/features/settings-instant-sync"
import { SelfDeletionItem } from "@/features/settings-self-deletion"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api, type SignedInUser } from "@/lib/api"
import { EMAIL_NOTIFICATIONS_HELP_URL } from "@/lib/brand"
import { isAdministrator } from "@/lib/people"

import { SignInMethods } from "@/features/settings-sign-in-methods"
import { useSignInMethods } from "@/lib/use-sign-in-methods"

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
  const { methods } = useSignInMethods(user.id)
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
        <OwnEmailItem key={user.id} email={user.email} hasPassword={methods.data?.has_password ?? null} />
        <SignInMethods key={`methods-${user.id}`} userId={user.id} onDone={setMessage} />
        <EmailNotificationsItem user={user} sendsEmail={sendsEmail} onDone={setMessage} />
        <InstantSyncItem user={user} onDone={setMessage} />
        <SelfDeletionItem hasPassword={methods.data?.has_password ?? null} onOpenPeople={onOpenPeople} />
      </div>
      {/* Always present, so a screen reader announces each message as it arrives. */}
      <p role="status" className={message ? undefined : "sr-only"}>
        {message}
      </p>
    </section>
  )
}

/**
 * The shared preference for Incident Notifications and Plan notices.
 * Activity keeps incidents; Your plan and held-rule views keep the Plan notice fallback.
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
