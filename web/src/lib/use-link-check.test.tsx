/* @vitest-environment happy-dom */

import { act, useEffect } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it } from "vitest"

import { useLinkToken } from "@/lib/use-link-check"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Page = typeof window & { happyDOM: { setURL: (url: string) => void } }

let root: Root
let container: HTMLDivElement
let address: string
let isCurrent: (token: string) => boolean = () => false

function Probe({ onReady }: { onReady: (check: (token: string) => boolean) => void }) {
  const { isCurrent: check } = useLinkToken()
  useEffect(() => onReady(check), [check, onReady])
  return null
}

beforeEach(() => {
  address = window.location.href
  ;(window as Page).happyDOM.setURL("http://localhost:8000/invitation#inv_older-token")
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
  act(() => root.render(<Probe onReady={(check) => (isCurrent = check)} />))
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  ;(window as Page).happyDOM.setURL(address)
})

describe("useLinkToken", () => {
  it("treats an older link as stale as soon as the address names a newer one", () => {
    // The address changes before the browser tells the page, so an answer arriving in between
    // must already see the newer link.
    ;(window as Page).happyDOM.setURL("http://localhost:8000/invitation#inv_newer-token")

    expect(isCurrent("inv_older-token")).toBe(false)
  })

  it("keeps the link current once the page removes its spent token from the address", () => {
    window.history.replaceState(window.history.state, "", "/invitation")

    expect(isCurrent("inv_older-token")).toBe(true)
  })
})
