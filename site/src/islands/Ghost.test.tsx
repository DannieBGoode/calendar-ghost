import { renderToString } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { GHOST_FACES, Ghost, SpeechBubble } from "./Ghost"

describe("Ghost", () => {
  it("draws every face, decorative and complete without JavaScript", () => {
    for (const face of GHOST_FACES) {
      const html = renderToString(<Ghost face={face} />)
      expect(html).toContain(`data-face="${face}"`)
      expect(html).toContain('aria-hidden="true"')
      expect(html).toContain('class="ghost-body"')
    }
  })

  it("is drawn flat: no cheeks, no shine, no gradient, plain eyes", () => {
    for (const face of GHOST_FACES) {
      for (const tone of ["moss", "lantern", "mist"] as const) {
        const html = renderToString(<Ghost face={face} tone={tone} float />)
        expect(html).not.toMatch(/cheek|blush|shine|gradient/i)
        // An open eye is one ellipse, with no catchlight circle on it.
        expect(html).not.toContain("<circle")
      }
    }
  })

  it("gives each face its own drawing", () => {
    const faces = GHOST_FACES.map((face) => renderToString(<Ghost face={face} />).replace(/data-face="\w+"/, ""))
    expect(new Set(faces).size).toBe(GHOST_FACES.length)
  })

  it("follows the pointer only with a neutral face", () => {
    const look = { x: 1, y: -1 }
    expect(renderToString(<Ghost face="neutral" look={look} />)).toContain('transform="translate(1.8 -1.8)"')
    expect(renderToString(<Ghost face="happy" look={look} />)).not.toContain("translate(")
  })

  it("draws both faces of a change, ending on the second", () => {
    const html = renderToString(<Ghost face="concerned" then="sleepy" />)
    expect(html).toContain('data-face="sleepy"')
    expect(html).toContain("data-sequence")
    expect(html).toContain("ghost-face-first")
    expect(html).toContain("ghost-face-then")
  })

  it("takes its tone, size, and idle life from props", () => {
    const html = renderToString(<Ghost tone="lantern" size={72} alive="brief" float />)
    expect(html).toContain('data-tone="lantern"')
    expect(html).toContain("--ghost-size:72px")
    expect(html).toContain('data-alive="brief"')
    expect(html).toContain("ghost-shadow")
  })
})

describe("SpeechBubble", () => {
  it("says its text from the side it is given", () => {
    const html = renderToString(<SpeechBubble side="left">Boo</SpeechBubble>)
    expect(html).toContain('data-side="left"')
    expect(html).toContain(">Boo<")
  })
})
