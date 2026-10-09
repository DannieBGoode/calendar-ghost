import type { PeoplePage, PeopleQuery, PeopleSort, PersonRole, PersonState, SortOrder, Verdict } from "@/lib/api"
import { VERDICTS } from "@/lib/operator-overview"

/** Everyone, in the order they joined, from the first page. */
export const DEFAULT_PEOPLE_QUERY: PeopleQuery = {
  search: "",
  role: "",
  state: "",
  verdict: "",
  sort: "joined",
  order: "asc",
  page: 1,
}

const ROLES: readonly PersonRole[] = ["installation_administrator", "user"]
const STATES: readonly PersonState[] = ["active", "disabled"]
const SORTS: readonly PeopleSort[] = ["joined", "email", "last_sign_in", "verdict"]
const ORDERS: readonly SortOrder[] = ["asc", "desc"]

function oneOf<T extends string>(values: readonly T[], value: string | null, fallback: T): T {
  return values.find((candidate) => candidate === value) ?? fallback
}

/**
 * The People page's search, filters, sort, and page, read from the address so reload, Back, and
 * shared links keep them. Anything unknown falls back to the default.
 */
export function peopleQueryFromSearch(search: string): PeopleQuery {
  const params = new URLSearchParams(search)
  const page = Number(params.get("page"))
  const defaults = DEFAULT_PEOPLE_QUERY
  return {
    search: params.get("search")?.trim() ?? "",
    role: oneOf<PersonRole | "">(ROLES, params.get("role"), ""),
    state: oneOf<PersonState | "">(STATES, params.get("state"), ""),
    verdict: oneOf<Verdict | "">(VERDICTS, params.get("verdict"), ""),
    sort: oneOf(SORTS, params.get("sort"), defaults.sort),
    order: oneOf(ORDERS, params.get("order"), defaults.order),
    page: Number.isInteger(page) && page > 1 ? page : 1,
  }
}

/** The address for a query, naming only what differs from the default. */
export function peopleSearch(query: PeopleQuery): string {
  const params = new URLSearchParams()
  const search = query.search.trim()
  if (search) params.set("search", search)
  if (query.role) params.set("role", query.role)
  if (query.state) params.set("state", query.state)
  if (query.verdict) params.set("verdict", query.verdict)
  if (query.sort !== DEFAULT_PEOPLE_QUERY.sort) params.set("sort", query.sort)
  if (query.order !== DEFAULT_PEOPLE_QUERY.order) params.set("order", query.order)
  if (query.page > 1) params.set("page", String(query.page))
  const text = params.toString()
  return text ? `?${text}` : ""
}

/** Sorting by a column: a new one starts ascending, the current one reverses; both from page 1. */
export function nextSort(query: PeopleQuery, sort: PeopleSort): Pick<PeopleQuery, "sort" | "order" | "page"> {
  const order: SortOrder = query.sort === sort && query.order === "asc" ? "desc" : "asc"
  return { sort, order, page: 1 }
}

/** Who a page shows, counted from 1, and whether there are pages before and after it. */
export function pageRange({
  page,
  page_size,
  total,
  shown,
}: Pick<PeoplePage, "page" | "page_size" | "total"> & { shown: number }) {
  const first = (page - 1) * page_size + 1
  return { first, last: first + shown - 1, previous: page > 1, next: page * page_size < total }
}
