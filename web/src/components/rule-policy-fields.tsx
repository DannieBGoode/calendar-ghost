import type { Ref } from "react"

import { InvitationResponseFields } from "@/components/invitation-response-fields"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { useI18n } from "@/i18n/provider"
import type { RulePolicyPayload } from "@/lib/api"
import { privacyHint } from "@/lib/privacy-policy"

/**
 * A rule's policy, shared by the rule builder and the policy editor: the choices of how events
 * look in one group, and the kinds of event to include in the other.
 */
export function RulePolicyFields({
  idPrefix,
  policy,
  destination,
  privacyRef,
  onChange,
}: {
  idPrefix: string
  policy: RulePolicyPayload
  destination: string
  privacyRef?: Ref<HTMLSelectElement>
  onChange: (next: RulePolicyPayload) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const privacyId = `${idPrefix}privacy-policy`
  return (
    <div className="policy-groups">
      <div className="policy-group">
        <div className="field-stack">
          <Label htmlFor={privacyId}>{t("rules.policy.privacyLabel")}</Label>
          <NativeSelect
            ref={privacyRef}
            id={privacyId}
            value={policy.privacy_policy}
            aria-describedby={`${privacyId}-hint`}
            onChange={(event) =>
              onChange({ ...policy, privacy_policy: event.target.value as RulePolicyPayload["privacy_policy"] })
            }
          >
            <option value="busy_only">{t("rules.policy.privacyOption.busyOnly")}</option>
            <option value="copy_details">{t("rules.policy.privacyOption.copyDetails")}</option>
          </NativeSelect>
          <p
            id={`${privacyId}-hint`}
            className="field-hint"
            data-tone={policy.privacy_policy === "copy_details" ? "attention" : undefined}
          >
            {privacyHint(i18n, policy.privacy_policy, destination)}
          </p>
        </div>
        <InvitationResponseFields
          idPrefix={idPrefix}
          policy={policy}
          onChange={(change) => onChange({ ...policy, ...change })}
        />
      </div>
      <div className="policy-group">
        <PolicyCheckbox
          id={`${idPrefix}sync-all-day`}
          label={t("rules.policy.allDay.label")}
          hint={t("rules.policy.allDay.hint")}
          checked={policy.sync_all_day_events}
          onChange={(checked) => onChange({ ...policy, sync_all_day_events: checked })}
        />
        <PolicyCheckbox
          id={`${idPrefix}sync-birthdays`}
          label={t("rules.policy.birthdays.label")}
          hint={t("rules.policy.birthdays.hint")}
          checked={policy.sync_birthdays}
          onChange={(checked) => onChange({ ...policy, sync_birthdays: checked })}
        />
      </div>
    </div>
  )
}

/** A checkbox named by its title alone; its hint is read as its description. */
function PolicyCheckbox({
  id,
  label,
  hint,
  checked,
  onChange,
}: {
  id: string
  label: string
  hint: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="checkbox-row" htmlFor={id}>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        aria-labelledby={`${id}-label`}
        aria-describedby={`${id}-hint`}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>
        <strong id={`${id}-label`}>{label}</strong>
        <small id={`${id}-hint`}>{hint}</small>
      </span>
    </label>
  )
}
