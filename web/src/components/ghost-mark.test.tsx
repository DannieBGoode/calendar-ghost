import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { GhostMark } from "./ghost-mark"

describe("GhostMark", () => {
  it("is decorative unless titled", () => {
    const markup = renderToStaticMarkup(<GhostMark className="x" />)
    expect(markup).toContain('aria-hidden="true"')
    expect(markup).toContain('class="ghost-mark x"')
    expect(markup).not.toContain("role=")
  })

  it("is an image named by its title when it stands alone", () => {
    const markup = renderToStaticMarkup(<GhostMark title="Calendar Ghost" />)
    expect(markup).toContain('role="img"')
    expect(markup).toContain('aria-label="Calendar Ghost"')
    expect(markup).not.toContain("aria-hidden")
  })
})
