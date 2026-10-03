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

  it("supports a happy expression for celebratory surfaces", () => {
    const markup = renderToStaticMarkup(<GhostMark expression="happy" />)
    expect(markup).toContain("M11.5 15.5q1.5-2.2 3 0")
    expect(markup).not.toContain('cx="13"')
  })

  it.each(["neutral", "happy", "concerned", "crying", "sleepy"] as const)("marks its %s expression", (expression) => {
    const markup = renderToStaticMarkup(<GhostMark expression={expression} />)
    expect(markup).toContain(`data-expression="${expression}"`)
  })

  it("tells worry from crying by the tears", () => {
    const concerned = renderToStaticMarkup(<GhostMark expression="concerned" />)
    const crying = renderToStaticMarkup(<GhostMark expression="crying" />)
    expect(concerned).not.toContain("ghost-mark-tear")
    expect(crying.match(/class="ghost-mark-tear/g)).toHaveLength(2)
  })
})
