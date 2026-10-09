import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { Registration, RegistrationPolicy } from "@/lib/api"
import type { RegistrationCommands } from "@/lib/use-registration"

/**
 * The Registration Policy: Only me, where nobody can join, or Invitation only. Only me is offered
 * again only while the administrator is the only person here.
 */
export function RegistrationSection({ commands }: { commands: RegistrationCommands }) {
  const i18n = useI18n()
  const { t } = i18n
  const { registration, change, message } = commands
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
          onChoose={(policy) => change.mutate(policy)}
        />
      )}
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
      </div>
    </fieldset>
  )
}
