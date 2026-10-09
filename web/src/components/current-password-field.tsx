import type { Ref } from "react"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/i18n/provider"

/** The signed-in User's current password, which confirms a change to their own sign-in. */
export function CurrentPasswordField({
  id,
  value,
  onChange,
  ref,
}: {
  id: string
  value: string
  onChange: (value: string) => void
  ref?: Ref<HTMLInputElement>
}) {
  const { t } = useI18n()
  return (
    <div className="field-stack">
      <Label htmlFor={id}>{t("settings.ownAccount.currentPassword")}</Label>
      <Input
        ref={ref}
        id={id}
        type="password"
        autoComplete="current-password"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required
      />
    </div>
  )
}
