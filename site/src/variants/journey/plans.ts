import type { Messages } from "../../i18n"
import type { PlanText } from "./crossing"

/** Sam's Dentist appointment in the /journey hero, with every word taken from the messages. */
export function journeyDentist(m: Messages): PlanText {
  const dentist = m.demo.events.dentist
  return {
    title: dentist.title,
    place: dentist.detail,
    description: m.variants.journey.crossing.description,
    guests: m.crossing.guests,
    link: m.crossing.link,
  }
}
