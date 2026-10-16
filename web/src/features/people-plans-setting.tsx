import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { NativeSelect } from "@/components/ui/native-select"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { PlansOverview } from "@/lib/api"
import { limitedPeople } from "@/lib/plans"
import type { PlanCommands } from "@/lib/use-plans"

type Setting = PlanCommands["setting"]

/**
 * Whether the last change of the Plans setting came from the on/off box: only the box changes
 * whether Plans are on, while Save default keeps it as it is. A refusal shows under the control
 * that sent it.
 */
function sentByBox(setting: Setting, overview: PlansOverview): boolean {
  return setting.variables !== undefined && setting.variables.enabled !== overview.enabled
}

/** Whether Plans are on, and whom they limit: what the on/off box says beside it. */
function enabledState({ t }: I18n, { enabled, default_plan, plans }: PlansOverview): string {
  if (!enabled) return t(default_plan === null ? "people.plans.enabled.offNoDefault" : "people.plans.enabled.off")
  const count = limitedPeople(plans)
  return count > 0 ? t("people.plans.enabled.on", { count }) : t("people.plans.enabled.onNobody")
}

/**
 * The installation's Plans setting, after the Plans it needs: the Default Plan, then whether Plans
 * limit people. While a change is on its way both controls keep focus but ignore input; a refusal
 * shows under the control that sent it, which takes focus.
 */
export function PlansSetting({ overview, commands }: { overview: PlansOverview; commands: PlanCommands }) {
  return (
    <div className="settings-list">
      <DefaultItem overview={overview} commands={commands} />
      <EnabledItem overview={overview} commands={commands} />
    </div>
  )
}

/**
 * The Default Plan as chosen here: the choice, which follows the saved default until another is
 * chosen, and its refusal, which takes focus as it arrives. Saving it sends nothing new while the
 * choice is the saved default or a change is on its way, and returns focus to the choice once saved.
 */
function useDefaultChoice(overview: PlansOverview, setting: Setting) {
  const select = useRef<HTMLSelectElement>(null)
  // The plan chosen but not saved yet; null follows the saved default.
  const [choice, setChoice] = useState<string | null>(null)
  const pending = setting.isPending
  const saved = overview.default_plan ?? ""
  const value = choice ?? saved
  const refused = setting.error && !sentByBox(setting, overview) ? setting.error : null
  useEffect(() => {
    if (refused) select.current?.focus()
  }, [refused])

  const choose = (next: string) => {
    if (pending) return
    if (refused) setting.reset()
    setChoice(next === saved ? null : next)
  }
  const save = () => {
    if (pending || value === saved) return
    setting.mutate(
      { enabled: overview.enabled, defaultPlan: value || null },
      {
        // Save default goes once the choice is saved, so focus returns to the choice.
        onSuccess: () => {
          setChoice(null)
          select.current?.focus()
        },
      },
    )
  }
  return { select, value, changed: value !== saved, refused, choose, save }
}

/**
 * The Default Plan. Choosing one saves nothing until Save default, which shows only while the
 * choice differs from the saved default. It cannot be cleared while Plans limit people.
 */
function DefaultItem({ overview, commands }: { overview: PlansOverview; commands: PlanCommands }) {
  const i18n = useI18n()
  const { t } = i18n
  const { setting } = commands
  const pending = setting.isPending || undefined
  const { select, value, changed, refused, choose, save } = useDefaultChoice(overview, setting)

  return (
    <div className="setting-item">
      <div className="setting-row">
        <div className="setting-copy">
          <h3 id="plans-default-title">{t("people.plans.default.label")}</h3>
          <p id="plans-default-hint">{t("people.plans.default.hint")}</p>
        </div>
        <div className="plans-default-control">
          <div className="appearance-control">
            <NativeSelect
              ref={select}
              id="plans-default"
              aria-labelledby="plans-default-title"
              aria-describedby={refused ? "plans-default-hint plans-default-error" : "plans-default-hint"}
              aria-invalid={refused ? true : undefined}
              aria-disabled={pending}
              value={value}
              onChange={(event) => choose(event.target.value)}
            >
              <option value="" disabled={overview.enabled}>
                {t("people.plans.default.none")}
              </option>
              {overview.plans.map((plan) => (
                <option key={plan.key} value={plan.key}>
                  {plan.name}
                </option>
              ))}
            </NativeSelect>
          </div>
          {changed && (
            <Button type="button" aria-disabled={pending} aria-busy={pending} onClick={save}>
              {t("people.plans.default.save")}
            </Button>
          )}
        </div>
      </div>
      {refused && (
        <p id="plans-default-error" className="field-error" role="alert">
          {apiErrorMessage(i18n, refused)}
        </p>
      )}
    </div>
  )
}

/**
 * Whether Plans limit people, last, since it needs a Plan to have. With no default, turning it on
 * makes the server add a No limits Plan as the default, so it says so before.
 */
function EnabledItem({ overview, commands }: { overview: PlansOverview; commands: PlanCommands }) {
  const i18n = useI18n()
  const { t } = i18n
  const { setting } = commands
  const box = useRef<HTMLInputElement>(null)
  const pending = setting.isPending
  // While a change is on its way, the box shows what was asked for.
  const checked = pending ? setting.variables.enabled : overview.enabled
  const refused = setting.error && sentByBox(setting, overview) ? setting.error : null
  useEffect(() => {
    if (refused) box.current?.focus()
  }, [refused])

  return (
    <div className="setting-item">
      <div className="setting-row">
        <label className="checkbox-row" htmlFor="plans-enabled">
          <input
            ref={box}
            id="plans-enabled"
            type="checkbox"
            checked={checked}
            aria-labelledby="plans-enabled-label"
            aria-describedby={refused ? "plans-enabled-hint plans-enabled-error" : "plans-enabled-hint"}
            aria-invalid={refused ? true : undefined}
            aria-disabled={pending || undefined}
            onChange={(event) =>
              !pending && setting.mutate({ enabled: event.target.checked, defaultPlan: overview.default_plan })
            }
          />
          <span>
            <strong id="plans-enabled-label">{t("people.plans.enabled.label")}</strong>
            <small id="plans-enabled-hint">{enabledState(i18n, overview)}</small>
          </span>
        </label>
      </div>
      {refused && (
        <p id="plans-enabled-error" className="field-error" role="alert">
          {apiErrorMessage(i18n, refused)}
        </p>
      )}
    </div>
  )
}
