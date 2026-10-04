import type { I18n } from "@/i18n/translator"
import type { RulePreview } from "@/lib/api"

type PreviewCounts = Pick<RulePreview, "eligible_events" | "excluded_events" | "recurring_series" | "occurrence_changes">

export function previewSummary(i18n: I18n, preview: PreviewCounts): string {
  const { eligible_events: eligible, excluded_events: excluded } = preview
  const recurring = [
    preview.recurring_series > 0 ? i18n.t("ruleDetails.preview.recurringSeries", { count: preview.recurring_series }) : null,
    preview.occurrence_changes > 0
      ? i18n.t("ruleDetails.preview.changedOccurrences", { count: preview.occurrence_changes })
      : null,
  ].filter((part): part is string => part !== null)
  return recurring.length
    ? i18n.t("ruleDetails.preview.summaryIncluding", { eligible, excluded, details: i18n.format.list(recurring) })
    : i18n.t("ruleDetails.preview.summary", { eligible, excluded })
}
