import { describe, expect, it } from "vitest"
import { en } from "../../i18n/en"
import { journeyDentist } from "./plans"

describe("journeyDentist", () => {
  it("keeps the home page's Dentist words, so the two pages tell the same story", () => {
    expect(journeyDentist(en)).toEqual({
      title: en.demo.events.dentist.title,
      place: en.demo.events.dentist.detail,
      description: en.variants.journey.crossing.description,
      guests: en.crossing.guests,
      link: en.crossing.link,
    })
  })
})
