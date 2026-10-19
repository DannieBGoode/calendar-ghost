import { useToast, type Toast } from "@/components/ui/toast-context"
import { answerUndo } from "@/features/undo"
import { useI18n } from "@/i18n/provider"
import type { PlansOverview } from "@/lib/api"
import { settingResult, undoOf } from "@/lib/plans-catalog"
import type { PlanCommands, SettingChange } from "@/lib/use-plans"

/** Sends a change of the Plans setting, from the setting as it was before it. */
export type ChangeSetting = (change: SettingChange, before: PlansOverview) => void

/**
 * Changes the Plans setting at once, as the switch and Make default do, and says what changed in
 * a toast with Undo, which changes it back the same way.
 */
export function useSettingChange(setting: PlanCommands["setting"]): ChangeSetting {
  const i18n = useI18n()
  const toasts = useToast()
  const changed = (before: PlansOverview, after: PlansOverview): Toast => ({
    message: settingResult(i18n, before, after),
    action: {
      label: i18n.t("common.toast.undo"),
      onSelect: () =>
        answerUndo(toasts, i18n, setting.mutateAsync({ ...undoOf(before, after), undo: true }), (undone) => changed(after, undone)),
    },
  })
  return (change, before) => {
    setting.mutate(change, { onSuccess: (after) => toasts.show(changed(before, after)) })
  }
}
