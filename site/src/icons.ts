// Lucide icons (ISC license, https://lucide.dev), bundled from `lucide-static` as SVG markup, so
// the page requests nothing from another host. Render them with components/Icon.astro.
import Activity from "lucide-static/icons/activity.svg?raw"
import AlignLeft from "lucide-static/icons/align-left.svg?raw"
import ArrowRight from "lucide-static/icons/arrow-right.svg?raw"
import ArrowUpRight from "lucide-static/icons/arrow-up-right.svg?raw"
import Bell from "lucide-static/icons/bell.svg?raw"
import Box from "lucide-static/icons/box.svg?raw"
import Check from "lucide-static/icons/check.svg?raw"
import CircleCheck from "lucide-static/icons/circle-check.svg?raw"
import CircleSlash from "lucide-static/icons/circle-slash.svg?raw"
import Clock from "lucide-static/icons/clock.svg?raw"
import Cpu from "lucide-static/icons/cpu.svg?raw"
import Database from "lucide-static/icons/database.svg?raw"
import Eye from "lucide-static/icons/eye.svg?raw"
import EyeOff from "lucide-static/icons/eye-off.svg?raw"
import ListChecks from "lucide-static/icons/list-checks.svg?raw"
import Mail from "lucide-static/icons/mail.svg?raw"
import MailX from "lucide-static/icons/mail-x.svg?raw"
import MapPin from "lucide-static/icons/map-pin.svg?raw"
import Minus from "lucide-static/icons/minus.svg?raw"
import Moon from "lucide-static/icons/moon.svg?raw"
import Paperclip from "lucide-static/icons/paperclip.svg?raw"
import Pause from "lucide-static/icons/pause.svg?raw"
import Play from "lucide-static/icons/play.svg?raw"
import Plus from "lucide-static/icons/plus.svg?raw"
import RefreshCwOff from "lucide-static/icons/refresh-cw-off.svg?raw"
import Repeat from "lucide-static/icons/repeat.svg?raw"
import RotateCcw from "lucide-static/icons/rotate-ccw.svg?raw"
import ShieldCheck from "lucide-static/icons/shield-check.svg?raw"
import SquareTerminal from "lucide-static/icons/square-terminal.svg?raw"
import Sun from "lucide-static/icons/sun.svg?raw"
import Trash2 from "lucide-static/icons/trash-2.svg?raw"
import User from "lucide-static/icons/user.svg?raw"
import UserRound from "lucide-static/icons/user-round.svg?raw"
import Users from "lucide-static/icons/users.svg?raw"
import UserX from "lucide-static/icons/user-x.svg?raw"
import Video from "lucide-static/icons/video.svg?raw"

/** The app's "changed in place" sign (web/src/components/change-sign.tsx), in Lucide's style. */
const Tilde = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 14q4-6.5 8-2t8-2" /></svg>`

export const ICONS = {
  activity: Activity,
  alignLeft: AlignLeft,
  arrowRight: ArrowRight,
  arrowUpRight: ArrowUpRight,
  bell: Bell,
  box: Box,
  check: Check,
  circleCheck: CircleCheck,
  circleSlash: CircleSlash,
  clock: Clock,
  cpu: Cpu,
  database: Database,
  eye: Eye,
  eyeOff: EyeOff,
  listChecks: ListChecks,
  mail: Mail,
  mailX: MailX,
  mapPin: MapPin,
  minus: Minus,
  moon: Moon,
  paperclip: Paperclip,
  pause: Pause,
  play: Play,
  plus: Plus,
  refreshCwOff: RefreshCwOff,
  repeat: Repeat,
  rotateCcw: RotateCcw,
  shieldCheck: ShieldCheck,
  squareTerminal: SquareTerminal,
  sun: Sun,
  tilde: Tilde,
  trash: Trash2,
  user: User,
  userRound: UserRound,
  users: Users,
  userX: UserX,
  video: Video,
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
