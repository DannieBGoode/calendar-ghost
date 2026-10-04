// Lucide icons (ISC license, https://lucide.dev), bundled from `lucide-static` as SVG markup, so
// the page requests nothing from another host. Render them with components/Icon.astro.
import Activity from "lucide-static/icons/activity.svg?raw"
import ArrowRight from "lucide-static/icons/arrow-right.svg?raw"
import ArrowUpRight from "lucide-static/icons/arrow-up-right.svg?raw"
import Check from "lucide-static/icons/check.svg?raw"
import CircleCheck from "lucide-static/icons/circle-check.svg?raw"
import CircleSlash from "lucide-static/icons/circle-slash.svg?raw"
import Eye from "lucide-static/icons/eye.svg?raw"
import House from "lucide-static/icons/house.svg?raw"
import ListChecks from "lucide-static/icons/list-checks.svg?raw"
import Mail from "lucide-static/icons/mail.svg?raw"
import MailX from "lucide-static/icons/mail-x.svg?raw"
import Minus from "lucide-static/icons/minus.svg?raw"
import RefreshCwOff from "lucide-static/icons/refresh-cw-off.svg?raw"
import Repeat from "lucide-static/icons/repeat.svg?raw"
import RotateCcw from "lucide-static/icons/rotate-ccw.svg?raw"
import ShieldCheck from "lucide-static/icons/shield-check.svg?raw"
import Trash2 from "lucide-static/icons/trash-2.svg?raw"
import User from "lucide-static/icons/user.svg?raw"

/** The app's "changed in place" sign (web/src/components/change-sign.tsx), in Lucide's style. */
const Tilde = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 14q4-6.5 8-2t8-2" /></svg>`

export const ICONS = {
  activity: Activity,
  arrowRight: ArrowRight,
  arrowUpRight: ArrowUpRight,
  check: Check,
  circleCheck: CircleCheck,
  circleSlash: CircleSlash,
  eye: Eye,
  house: House,
  listChecks: ListChecks,
  mail: Mail,
  mailX: MailX,
  minus: Minus,
  refreshCwOff: RefreshCwOff,
  repeat: Repeat,
  rotateCcw: RotateCcw,
  shieldCheck: ShieldCheck,
  tilde: Tilde,
  trash: Trash2,
  user: User,
} satisfies Record<string, string>

export type IconName = keyof typeof ICONS

/** The SVG markup for `name`, decorative, with the license comment and fixed size removed. */
export function iconMarkup(name: IconName, className = "icon"): string {
  return ICONS[name]
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/\s(?:width|height)="24"/g, "")
    .replace(/\sclass="[^"]*"/, "")
    .replace("<svg", `<svg class="${className}" aria-hidden="true" focusable="false"`)
    .trim()
}
