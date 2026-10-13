/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot } from "react-dom/client"
import { describe, expect, it } from "vitest"

import { rulePreviewKey } from "./use-rule-commands"
import { useRuleInvalidation } from "./use-rule-refresh"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe("useRuleInvalidation", () => {
  it("forgets the rule's preview, so the next visit previews the changed rule", async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(rulePreviewKey("rule-1"), { items: [] })
    queryClient.setQueryData(rulePreviewKey("rule-2"), { items: [] })
    let invalidate: (() => Promise<void>) | undefined
    function Probe() {
      invalidate = useRuleInvalidation("rule-1")
      return null
    }
    const root = createRoot(document.createElement("div"))
    act(() => root.render(<QueryClientProvider client={queryClient}><Probe /></QueryClientProvider>))

    await act(async () => {
      await invalidate?.()
    })

    expect(queryClient.getQueryData(rulePreviewKey("rule-1"))).toBeUndefined()
    expect(queryClient.getQueryData(rulePreviewKey("rule-2"))).toEqual({ items: [] })
    act(() => root.unmount())
  })
})
