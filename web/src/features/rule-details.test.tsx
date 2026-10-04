import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { EndpointFields } from "./calendar-replacement"
import type { ConnectedAccount, DiscoveredCalendar } from "@/lib/api"

const account: ConnectedAccount = {
  id: "personal",
  display_name: "Daniel Calatayud",
  email: "daniel@example.com",
  provider: "google",
  avatar_url: null,
  state: "connected",
  rule_count: 0,
  authorized_at: "2026-10-02T00:00:00Z",
}

const writableCalendar: DiscoveredCalendar = {
  id: "work@example.test",
  summary: "Work",
  access_role: "owner",
  writable: true,
  primary: true,
}

const readOnlyCalendar: DiscoveredCalendar = {
  id: "holidays@example.test",
  summary: "Holidays",
  access_role: "reader",
  writable: false,
  primary: false,
}

function renderFields(writableOnly: boolean) {
  return renderToStaticMarkup(
    createElement(EndpointFields, {
      legend: writableOnly ? "Destination calendar" : "Source calendar",
      idPrefix: writableOnly ? "replace-destination" : "replace-source",
      accounts: [account],
      account: account.id,
      calendar: writableCalendar.id,
      calendars: [writableCalendar, readOnlyCalendar],
      writableOnly,
      onAccount: () => undefined,
      onCalendar: () => undefined,
    }),
  )
}

describe("EndpointFields", () => {
  it("keeps a read-only calendar selectable as a Source Calendar", () => {
    const markup = renderFields(false)

    expect(markup).toContain(`value="${writableCalendar.id}"`)
    expect(markup).toContain(`value="${readOnlyCalendar.id}"`)
    expect(markup).toContain(readOnlyCalendar.summary)
  })

  it("excludes a read-only calendar from the Destination Calendar options", () => {
    const markup = renderFields(true)

    expect(markup).toContain(`value="${writableCalendar.id}"`)
    expect(markup).not.toContain(`value="${readOnlyCalendar.id}"`)
    expect(markup).not.toContain(readOnlyCalendar.summary)
  })
})
