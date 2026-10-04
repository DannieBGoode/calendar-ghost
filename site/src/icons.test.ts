import { describe, expect, it } from "vitest"
import { ICONS, iconMarkup, type IconName } from "./icons"

describe("iconMarkup", () => {
  it("makes every icon a decorative inline SVG sized by CSS", () => {
    for (const name of Object.keys(ICONS) as IconName[]) {
      const svg = iconMarkup(name, "trust-icon")
      expect(svg.startsWith('<svg class="trust-icon" aria-hidden="true" focusable="false"')).toBe(true)
      expect(svg).not.toContain("<!--")
      expect(svg).not.toMatch(/\s(width|height)="24"/)
      expect(svg).toContain("</svg>")
    }
  })
})
