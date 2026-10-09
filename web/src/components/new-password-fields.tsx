import { useId } from "react"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/i18n/provider"
import { passwordMismatch } from "@/lib/passwords"

/** A new password and its confirmation, with the length rule and a mismatch note. */
export function NewPasswordFields({
  idPrefix,
  password,
  confirmation,
  onChange,
  passwordLabel,
  confirmationLabel,
}: {
  /** Fixed ids, so a page can point at the fields; generated when absent. */
  idPrefix?: string
  password: string
  confirmation: string
  onChange: (next: { password: string; confirmation: string }) => void
  passwordLabel?: string
  confirmationLabel?: string
}) {
  const { t } = useI18n()
  const generated = useId()
  const id = idPrefix ?? generated
  const mismatch = passwordMismatch(password, confirmation)
  return (
    <>
      <div className="field-stack">
        <Label htmlFor={id}>{passwordLabel ?? t("auth.password")}</Label>
        <Input
          id={id}
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(event) => onChange({ password: event.target.value, confirmation })}
          aria-describedby={`${id}-hint`}
          required
          minLength={12}
        />
        <p id={`${id}-hint`} className="field-hint">
          {t("auth.passwordHint")}
        </p>
      </div>
      <div className="field-stack">
        <Label htmlFor={`${id}-confirmation`}>{confirmationLabel ?? t("auth.confirmPassword")}</Label>
        <Input
          id={`${id}-confirmation`}
          type="password"
          autoComplete="new-password"
          value={confirmation}
          onChange={(event) => onChange({ password, confirmation: event.target.value })}
          aria-invalid={mismatch}
          required
        />
        {mismatch && (
          <p className="field-error" role="alert">
            {t("auth.passwordMismatch")}
          </p>
        )}
      </div>
    </>
  )
}
