import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest"

import {
  ApiError,
  api,
  call,
  errorDetail,
  type ReconcileResult,
  type Rule,
  type RuleDetail,
  type RuleSummary,
  type SyncResult,
  UnreadableResponseError,
} from "./api"

function stubFetch(status = 200, body: unknown = {}) {
  const fetch = vi.fn(() => Promise.resolve(new Response(status === 204 ? null : JSON.stringify(body), { status })))
  vi.stubGlobal("fetch", fetch)
  return fetch
}

function requested(fetch: ReturnType<typeof stubFetch>) {
  const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
  return { url, method: init.method, body: init.body }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("api routes", () => {
  it("types each call by the route it names in the schema", () => {
    expectTypeOf(api.rules).returns.resolves.toEqualTypeOf<RuleSummary[]>()
    expectTypeOf(api.rule).returns.resolves.toEqualTypeOf<RuleDetail>()
    expectTypeOf(api.createRule).returns.resolves.toEqualTypeOf<Rule>()
    expectTypeOf(api.syncRule).returns.resolves.toEqualTypeOf<SyncResult>()
    expectTypeOf(api.reconcileRule).returns.resolves.toEqualTypeOf<ReconcileResult>()
    expectTypeOf(api.logOut).returns.resolves.toEqualTypeOf<undefined>()
  })

  it("rejects a call that leaves out or invents a route input", () => {
    // Type checks only: the calls are never made.
    const wrongCalls = () => [
      // @ts-expect-error The rule route needs its rule_id.
      call("/api/v1/rules/{rule_id}", "get"),
      // @ts-expect-error Creating a rule needs a body.
      call("/api/v1/rules", "post"),
      // @ts-expect-error Removing a rule needs the projections query.
      call("/api/v1/rules/{rule_id}", "delete", { params: { rule_id: "r" } }),
      // @ts-expect-error The dashboard takes no body.
      call("/api/v1/dashboard", "get", { body: {} }),
      // @ts-expect-error Activity has no `rule` query parameter.
      call("/api/v1/audit-entries", "get", { query: { rule: "r" } }),
      // @ts-expect-error The dashboard route declares no POST.
      call("/api/v1/dashboard", "post"),
    ]
    expectTypeOf(wrongCalls).toBeFunction()
  })

  it("sends every activity filter as the query the route declares", async () => {
    const fetch = stubFetch(200, [])
    await api.activity({ ruleId: "rule-1", categories: ["changed", "blocked"], before: 42, query: " lunch " })
    expect(requested(fetch).url).toBe(
      "/api/v1/audit-entries?limit=100&rule_id=rule-1&category=changed&category=blocked&before=42&q=lunch",
    )
    const unfiltered = stubFetch(200, [])
    await api.activity()
    expect(requested(unfiltered).url).toBe("/api/v1/audit-entries?limit=100")
  })

  it("fills and encodes path parameters", async () => {
    const fetch = stubFetch()
    await api.rule("rule/1 x")
    expect(requested(fetch)).toEqual({ url: "/api/v1/rules/rule%2F1%20x", method: "GET", body: undefined })
  })

  it("sends the query and the JSON body the route declares", async () => {
    const remove = stubFetch()
    await api.removeRule("rule-1", "detach")
    expect(requested(remove)).toEqual({ url: "/api/v1/rules/rule-1?projections=detach", method: "DELETE", body: undefined })

    const clear = stubFetch()
    await api.clearActivity(30)
    expect(requested(clear)).toEqual({
      url: "/api/v1/storage/activity/clear",
      method: "POST",
      body: JSON.stringify({ older_than_days: 30 }),
    })
  })

  it("returns undefined for an empty success response", async () => {
    stubFetch(204)
    await expect(api.logOut()).resolves.toBeUndefined()
  })
})

describe("errorDetail", () => {
  it("reads a route's own message", () => {
    expect(errorDetail({ detail: "sync rule does not exist" })).toBe("sync rule does not exist")
  })

  it("joins the messages of a request validation error", () => {
    const body = {
      detail: [
        { loc: ["body", "privacy_policy"], msg: "Input should be 'busy_only' or 'copy_details'", type: "literal_error" },
        { loc: ["body", "password"], msg: "String should have at least 12 characters", type: "string_too_short" },
      ],
    }
    expect(errorDetail(body)).toBe(
      "Input should be 'busy_only' or 'copy_details'; String should have at least 12 characters",
    )
  })

  it("has no message for a body without a readable detail", () => {
    expect(errorDetail(null)).toBeNull()
    expect(errorDetail({ detail: [{ type: "missing" }] })).toBeNull()
    expect(errorDetail({ error: "boom" })).toBeNull()
  })

  it("puts a validation message on the thrown error", async () => {
    stubFetch(422, { detail: [{ msg: "Input should be 'busy_only' or 'copy_details'" }] })
    const error = await api.rules().catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toBe("Input should be 'busy_only' or 'copy_details'")
    expect((error as ApiError).detail).toBe("Input should be 'busy_only' or 'copy_details'")
  })
})

function respond(status: number, body: string, contentType = "application/json") {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(body, { status, headers: { "Content-Type": contentType } }))),
  )
}

async function failure(): Promise<ApiError> {
  try {
    await api.session()
  } catch (error) {
    if (error instanceof ApiError) return error
    throw error
  }
  throw new Error("expected a failure")
}

describe("request errors", () => {
  it("keeps the status and detail", async () => {
    respond(409, JSON.stringify({ detail: "storage is busy" }))
    const error = await failure()
    expect([error.status, error.detail]).toEqual([409, "storage is busy"])
  })

  it("has no detail for a validation list without messages", async () => {
    respond(422, JSON.stringify({ detail: [{ loc: ["body", "password"] }] }))
    const error = await failure()
    expect(error.detail).toBeNull()
    expect(error.message).toBe("The request could not be completed.")
  })

  it("survives a body that is not JSON", async () => {
    respond(502, "<html>Bad gateway</html>", "text/html")
    const error = await failure()
    expect([error.status, error.detail]).toEqual([502, null])
  })

  it("marks a successful response whose body is not JSON as unreadable", async () => {
    respond(200, "<html>Fallback</html>", "text/html")
    const error = await failure()
    expect(error).toBeInstanceOf(UnreadableResponseError)
  })
})
