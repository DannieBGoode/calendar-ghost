import { Check, CircleSlash, Minus, Pin, Plus, X } from "lucide-react"
import type { ComponentType, SVGProps } from "react"

import type { ChangeMark } from "@/lib/activity"

/** A tilde in Lucide's stroke style: the "changed in place" sign beside + and − in a diff. */
function Tilde(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" {...props}>
      <path d="M4 14q4-6.5 8-2t8-2" />
    </svg>
  )
}

const SIGNS: Record<ChangeMark, ComponentType<SVGProps<SVGSVGElement>>> = {
  added: Plus,
  removed: Minus,
  changed: Tilde,
  blocked: X,
  kept: Pin,
  current: Check,
  skipped: CircleSlash,
}

/**
 * The one sign for each outcome, used by Activity and the Overview alike: + added, − removed,
 * ~ changed, × blocked, and quiet signs for events left as they were.
 */
export function ChangeSign({ mark, ...props }: { mark: ChangeMark } & SVGProps<SVGSVGElement>) {
  const Sign = SIGNS[mark]
  return <Sign aria-hidden="true" {...props} />
}
