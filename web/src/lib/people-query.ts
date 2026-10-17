import type { PeoplePage, PeopleQuery, PeopleSort, PersonRole, PersonState, SortOrder, Verdict } from "@/lib/api"
import { appPathForPeopleTab } from "@/lib/navigation"
import { VERDICTS } from "@/lib/operator-overview"

/** Everyone, in the order they joined, from the first page. */
export const DEFAULT_PEOPLE_QUERY: PeopleQuery = {
  search: "",
  role: "",
  state: "",
  verdict: "",
  plan: "",
  over: false,
  sort: "joined",
  order: "asc",
  page: 1,
}

const ROLES: readonly PersonRole[] = ["installation_administrator", "user"]
const STATES: readonly PersonState[] = ["active", "disabled"]
const SORTS: readonly PeopleSort[] = ["joined", "email", "last_sign_in", "verdict"]
const ORDERS: readonly SortOrder[] = ["asc", "desc"]
/** A Plan's key as the server checks it (`PlanKey` in domain/plans.py); any other finds nobody. */
const PLAN_KEY = /^[a-z0-9][a-z0-9-]{0,31}$/

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
    plan: PLAN_KEY.test(params.get("plan") ?? "") ? (params.get("plan") ?? "") : "",
    over: params.get("over") === "true",
    sort: oneOf(SORTS, params.get("sort"), defaults.sort),
    order: oneOf(ORDERS, params.get("order"), defaults.order),
    page: Number.isInteger(page) && page > 1 ? page : 1,
  }
}

/** The search and filters in use, in the order the address names them. */
function filterParams(query: PeopleQuery): [string, string][] {
  const filters: [string, string][] = [
    ["search", query.search.trim()],
    ["role", query.role],
    ["state", query.state],
    ["verdict", query.verdict],
    ["plan", query.plan],
    ["over", query.over ? "true" : ""],
  ]
  return filters.filter(([, value]) => value !== "")
}

/** The address for a query, naming only what differs from the default. */
export function peopleSearch(query: PeopleQuery): string {
  const params = new URLSearchParams(filterParams(query))
  if (query.sort !== DEFAULT_PEOPLE_QUERY.sort) params.set("sort", query.sort)
  if (query.order !== DEFAULT_PEOPLE_QUERY.order) params.set("order", query.order)
  if (query.page > 1) params.set("page", String(query.page))
  const text = params.toString()
  return text ? `?${text}` : ""
}

/** The filters a link from elsewhere on People opens Everyone with, such as one Plan's people over a limit. */
export type PeopleFilter = Partial<Pick<PeopleQuery, "plan" | "over">>

/** Everyone's address, from its first page, showing only the people `filter` names. */
export function peoplePath(filter: PeopleFilter): string {
  return `${appPathForPeopleTab("everyone")}${peopleSearch({ ...DEFAULT_PEOPLE_QUERY, ...filter })}`
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
