import { describe, expect, it } from "vitest"

import { DEFAULT_PEOPLE_QUERY, nextSort, pageRange, peopleQueryFromSearch, peopleSearch } from "./people-query"

describe("the People page address", () => {
  it("reads every part of the query", () => {
    expect(
      peopleQueryFromSearch("?search=rob&role=user&state=disabled&verdict=stopped&sort=verdict&order=desc&page=3"),
    ).toEqual({
      search: "rob",
      role: "user",
      state: "disabled",
      verdict: "stopped",
      sort: "verdict",
      order: "desc",
      page: 3,
    })
  })

  it("falls back to the defaults for missing or unknown values", () => {
    expect(peopleQueryFromSearch("")).toEqual(DEFAULT_PEOPLE_QUERY)
    expect(peopleQueryFromSearch("?role=owner&state=gone&verdict=fine&sort=name&order=up&page=-2")).toEqual(
      DEFAULT_PEOPLE_QUERY,
    )
    expect(peopleQueryFromSearch("?page=1.5").page).toBe(1)
    expect(peopleQueryFromSearch("?search=%20%20").search).toBe("")
  })

  it("writes only what differs from the defaults", () => {
    expect(peopleSearch(DEFAULT_PEOPLE_QUERY)).toBe("")
    expect(peopleSearch({ ...DEFAULT_PEOPLE_QUERY, search: " a b ", role: "installation_administrator", page: 2 })).toBe(
      "?search=a+b&role=installation_administrator&page=2",
    )
    expect(peopleSearch({ ...DEFAULT_PEOPLE_QUERY, sort: "last_sign_in", order: "desc", state: "active" })).toBe(
      "?state=active&sort=last_sign_in&order=desc",
    )
    expect(peopleSearch({ ...DEFAULT_PEOPLE_QUERY, verdict: "review", sort: "verdict" })).toBe(
      "?verdict=review&sort=verdict",
    )
  })

  it("round-trips through the address", () => {
    const query = {
      search: "dana",
      role: "user",
      state: "active",
      verdict: "waiting",
      sort: "email",
      order: "desc",
      page: 4,
    } as const
    expect(peopleQueryFromSearch(peopleSearch(query))).toEqual(query)
  })
})

describe("sorting", () => {
  it("sorts a new column ascending from the first page", () => {
    expect(nextSort({ ...DEFAULT_PEOPLE_QUERY, order: "desc", page: 3 }, "email")).toEqual({
      sort: "email",
      order: "asc",
      page: 1,
    })
  })

  it("reverses the column already sorted", () => {
    expect(nextSort({ ...DEFAULT_PEOPLE_QUERY, sort: "email", order: "asc", page: 2 }, "email")).toEqual({
      sort: "email",
      order: "desc",
      page: 1,
    })
    expect(nextSort({ ...DEFAULT_PEOPLE_QUERY, sort: "email", order: "desc" }, "email").order).toBe("asc")
  })
})

describe("pageRange", () => {
  it("names the first and last person shown and whether there is more", () => {
    expect(pageRange({ page: 2, page_size: 50, total: 1234, shown: 50 })).toEqual({
      first: 51,
      last: 100,
      previous: true,
      next: true,
    })
    expect(pageRange({ page: 1, page_size: 50, total: 3, shown: 3 })).toEqual({
      first: 1,
      last: 3,
      previous: false,
      next: false,
    })
    expect(pageRange({ page: 25, page_size: 50, total: 1234, shown: 34 })).toEqual({
      first: 1201,
      last: 1234,
      previous: true,
      next: false,
    })
  })
})
