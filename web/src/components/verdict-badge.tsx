import { CheckCircle2, CircleDashed, CirclePause, Hourglass, ShieldAlert, TriangleAlert, UserX } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/i18n/provider"
import type { Verdict } from "@/lib/api"
import { verdictTone } from "@/lib/operator-overview"

const ICONS: Record<Verdict, typeof CheckCircle2> = {
  stalled: ShieldAlert,
  stopped: ShieldAlert,
  review: TriangleAlert,
  waiting: Hourglass,
  paused: CirclePause,
  setup: CircleDashed,
  healthy: CheckCircle2,
}

/** A person's or the installation's sync status, as color, an icon, and words, never color alone. */
export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const { t } = useI18n()
  const Icon = ICONS[verdict]
  return (
    <Badge variant={verdictTone(verdict)}>
      <Icon aria-hidden="true" /> {t(`people.verdicts.${verdict}`)}
    </Badge>
  )
}

/** Someone an administrator stopped from signing in: a deliberate choice, so quiet, not red. */
export function DisabledBadge() {
  const { t } = useI18n()
  return (
    <Badge variant="neutral">
      <UserX aria-hidden="true" /> {t("people.states.disabled")}
    </Badge>
  )
}

/** The icon a verdict carries, for controls that name a verdict without a badge. */
export function VerdictIcon({ verdict }: { verdict: Verdict }) {
  const Icon = ICONS[verdict]
  return <Icon aria-hidden="true" />
}
