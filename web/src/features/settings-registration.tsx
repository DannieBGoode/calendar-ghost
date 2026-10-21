import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { SOURCE_URL } from "@/lib/brand"
import type { Registration, RegistrationPolicy } from "@/lib/api"
import type { RegistrationCommands } from "@/lib/use-registration"

/**
 * The Registration Policy and current Open readiness. Only me is offered again only while
 * the administrator is the only person here.
 */
export function RegistrationSection({ commands }: { commands: RegistrationCommands }) {
  const i18n = useI18n()
  const { t } = i18n
  const { registration, change, message } = commands
  const [confirmClose, setConfirmClose] = useState(false)
  return (
    <section className="settings-section" aria-labelledby="registration-title">
      <div className="section-heading">
        <div>
          <h2 id="registration-title">{t("settings.registration.title")}</h2>
          <p>{t("settings.registration.intro")}</p>
        </div>
      </div>
      {registration.isPending && <Skeleton className="h-16 w-full" />}
      {registration.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("settings.registration.loadError")}</span>
          <Button type="button" variant="outline" onClick={() => void registration.refetch()}>
            {t("settings.registration.tryAgain")}
          </Button>
        </div>
      )}
      {registration.data && (
        <PolicyChoice
          registration={registration.data}
          pending={change.isPending}
          onChoose={(policy) => {
            if (registration.data.policy === "open" && policy === "invitation_only") setConfirmClose(true)
            else change.mutate(policy)
          }}
        />
      )}
      {confirmClose && registration.data?.policy === "open" && <div className="settings-list p-6">
        <p>{t("settings.registration.closeWarning")}</p>
        <div className="mt-4 flex flex-wrap gap-3"><Button disabled={change.isPending} onClick={() => change.mutate("invitation_only", { onSuccess: () => setConfirmClose(false) })}>{t("settings.registration.closeConfirm")}</Button><Button variant="outline" onClick={() => setConfirmClose(false)}>{t("settings.registration.keepOpen")}</Button></div>
      </div>}
      <p className="field-hint">{t("settings.registration.plansOff")}</p>
      {change.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, change.error)}
        </p>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  )
}

function PolicyChoice({
  registration,
  pending,
  onChoose,
}: {
  registration: Registration
  pending: boolean
  onChoose: (policy: RegistrationPolicy) => void
}) {
  const { t } = useI18n()
  const { policy } = registration
  const onlyMeBlocked = !registration.only_me_available && policy !== "only_me"
  return (
    <fieldset className="settings-list projection-choice registration-choice" aria-labelledby="registration-title">
      <div className="radio-options">
        <label className="radio-row">
          <input
            type="radio"
            name="registration-policy"
            value="only_me"
            checked={policy === "only_me"}
            disabled={pending || onlyMeBlocked}
            onChange={() => onChoose("only_me")}
          />
          <span>
            <strong>{t("settings.registration.onlyMe")}</strong>
            <small>
              {onlyMeBlocked ? t("settings.registration.onlyMeUnavailable") : t("settings.registration.onlyMeHint")}
            </small>
          </span>
        </label>
        <label className="radio-row">
          <input
            type="radio"
            name="registration-policy"
            value="invitation_only"
            checked={policy === "invitation_only"}
            disabled={pending}
            onChange={() => onChoose("invitation_only")}
          />
          <span>
            <strong>{t("settings.registration.invitationOnly")}</strong>
            <small>{t("settings.registration.invitationOnlyHint")}</small>
          </span>
        </label>
        <label className="radio-row">
          <input type="radio" name="registration-policy" value="open" checked={policy === "open"} disabled={pending || !registration.open_available} onChange={() => onChoose("open")} />
          <span><strong>{t("settings.registration.open")}</strong><small>{t("settings.registration.openHint")}</small></span>
        </label>
      </div>
      {!registration.open_available && <div className="p-5">
        <p role="status">{t(registration.open_unavailable_reason === "identity_email_not_tested" ? "settings.registration.notTested" : "settings.registration.notConfigured")}</p>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-3"><a className="text-link" href="#identity-email-title">{t("settings.registration.identityEmail")}</a><a className="text-link" href={`${SOURCE_URL}/docs/deployment.md#trusted-proxy-headers`} target="_blank" rel="noreferrer">{t("settings.registration.proxyGuide")}</a></div>
      </div>}
    </fieldset>
  )
}
