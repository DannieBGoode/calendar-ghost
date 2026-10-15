import {
  Cake,
  CalendarDays,
  CircleQuestionMark,
  CircleX,
  FileText,
  MailQuestionMark,
  RotateCcwClock,
  type LucideIcon,
} from "lucide-react"

/**
 * One icon for each thing a rule decides, whatever it decides, so Rule Preview and Rule Details
 * show the same icon for the same choice. Rule Preview's privacy line states the event information
 * with its own icon, for what the destination sees.
 */
export const RULE_SETTING_ICONS = {
  eventInformation: FileText,
  tentative: CircleQuestionMark,
  unanswered: MailQuestionMark,
  declined: CircleX,
  allDay: CalendarDays,
  birthdays: Cake,
  startingPoint: RotateCcwClock,
} satisfies Record<string, LucideIcon>
