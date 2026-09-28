import type { RulePreview } from "@/lib/api"

type PreviewCounts = Pick<RulePreview, "eligible_events" | "excluded_events" | "recurring_series" | "occurrence_changes">

function plural(count: number, noun: string, pluralNoun = `${noun}s`): string {
  return `${count} ${count === 1 ? noun : pluralNoun}`
}

export function previewSummary(preview: PreviewCounts): string {
  const base = `Preview found ${preview.eligible_events} eligible and ${preview.excluded_events} excluded events`
  const recurring = [
    preview.recurring_series > 0 ? plural(preview.recurring_series, "recurring series", "recurring series") : null,
    preview.occurrence_changes > 0 ? plural(preview.occurrence_changes, "changed occurrence") : null,
  ].filter(Boolean)
  return recurring.length ? `${base}, including ${recurring.join(" and ")}.` : `${base}.`
}
