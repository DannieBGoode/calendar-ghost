import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"
import { useRef, useState } from "react"

import { CurrentPasswordField } from "@/components/current-password-field"
import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { Button } from "@/components/ui/button"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api, type ProjectionHandling } from "@/lib/api"

/**
 * User Deletion of the signed-in User. They choose whether the events their rules wrote are
 * deleted (recommended) or kept as ordinary events, and confirm with their password. Afterward
 * the app returns to the sign-in screen.
 */
export function SelfDeletionItem() {
  const i18n = useI18n()
  const { t } = i18n
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [projections, setProjections] = useState<ProjectionHandling>("delete")
  const [password, setPassword] = useState("")
  const toggle = useRef<HTMLButtonElement>(null)
  const remove = useMutation({
    mutationFn: () => api.deleteOwnAccount(password, projections),
    // The session ended with the User. Resetting drops every answer they could see and asks for
    // the session again, which shows the sign-in screen; `clear()` alone would leave the mounted
    // session query detached from the cache, so the app would not notice.
    onSuccess: () => queryClient.resetQueries(),
  })

  function close() {
    setOpen(false)
    setPassword("")
    remove.reset()
    toggle.current?.focus()
  }

  return (
    <div className="setting-item">
      <div className="setting-row">
        <div>
          <h3>{t("settings.ownAccount.delete.title")}</h3>
          <p>{t("settings.ownAccount.delete.body")}</p>
        </div>
        <Button
          ref={toggle}
          id="own-delete-toggle"
          type="button"
          variant="outline"
          aria-expanded={open}
          aria-controls="own-delete-confirmation"
          onClick={() => setOpen(true)}
        >
          <Trash2 aria-hidden="true" />
          {t("settings.ownAccount.delete.open")}
        </Button>
      </div>
      {open && (
        <DestructiveConfirmation
          id="own-delete-confirmation"
          title={t("settings.ownAccount.delete.confirmTitle")}
          body={t("settings.ownAccount.delete.confirmBody")}
          cancelLabel={t("settings.ownAccount.delete.keep")}
          confirmLabel={t("settings.ownAccount.delete.confirm")}
          pendingLabel={t("settings.ownAccount.delete.pending")}
          pending={remove.isPending}
          confirmDisabled={!password}
          onConfirm={() => remove.mutate()}
          onCancel={close}
        >
          <div className="confirmation-fields">
            <ProjectionsChoice value={projections} onChange={setProjections} />
            <CurrentPasswordField id="own-delete-password" value={password} onChange={setPassword} />
            {remove.error && (
              <p className="field-error" role="alert">
                {apiErrorMessage(i18n, remove.error)}
              </p>
            )}
          </div>
        </DestructiveConfirmation>
      )}
    </div>
  )
}

function ProjectionsChoice({
  value,
  onChange,
}: {
  value: ProjectionHandling
  onChange: (value: ProjectionHandling) => void
}) {
  const { t } = useI18n()
  return (
    <fieldset className="projection-choice">
      <legend>{t("settings.ownAccount.delete.legend")}</legend>
      <div className="radio-options">
        <label className="radio-row">
          <input
            type="radio"
            name="own-delete-projections"
            value="delete"
            checked={value === "delete"}
            onChange={() => onChange("delete")}
          />
          <span>
            <strong>{t("settings.ownAccount.delete.deleteEvents")}</strong>
            <small>{t("settings.ownAccount.delete.deleteEventsHint")}</small>
          </span>
        </label>
        <label className="radio-row">
          <input
            type="radio"
            name="own-delete-projections"
            value="detach"
            checked={value === "detach"}
            onChange={() => onChange("detach")}
          />
          <span>
            <strong>{t("settings.ownAccount.delete.keepEvents")}</strong>
            <small>{t("settings.ownAccount.delete.keepEventsHint")}</small>
          </span>
        </label>
      </div>
    </fieldset>
  )
}
