import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

const stylesheet = readFileSync(new URL("../index.css", import.meta.url), "utf8")
const html = readFileSync(new URL("../../index.html", import.meta.url), "utf8")
const entry = readFileSync(new URL("../main.tsx", import.meta.url), "utf8")

type Tokens = Map<string, string>

function block(selector: RegExp): Tokens {
  const body = stylesheet.match(selector)?.[1]
  if (!body) throw new Error(`No block for ${selector}`)
  return new Map([...body.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]))
}

const light = block(/:root \{([\s\S]*?)\n\}/)
const dark = new Map([...light, ...block(/:root\[data-theme="dark"\] \{([\s\S]*?)\n\}/)])

function resolve(tokens: Tokens, name: string): string {
  const value = tokens.get(name)
  if (!value) throw new Error(`Missing --${name}`)
  const reference = value.match(/^var\(--([\w-]+)\)$/)
  return reference ? resolve(tokens, reference[1]) : value
}

/** WCAG relative luminance of an `oklch(L C H)` value, via OKLab and linear sRGB. */
function luminance(value: string): number {
  const match = value.match(/oklch\(([\d.]+) ([\d.]+) ([\d.]+)/)
  if (!match) throw new Error(`Not oklch: ${value}`)
  const [L, C, h] = match.slice(1).map(Number)
  const a = C * Math.cos((h * Math.PI) / 180)
  const b = C * Math.sin((h * Math.PI) / 180)
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
  const clamp = (x: number) => Math.min(1, Math.max(0, x))
  const r = clamp(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s)
  const g = clamp(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s)
  const bl = clamp(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s)
  return 0.2126 * r + 0.7152 * g + 0.0722 * bl
}

function contrast(tokens: Tokens, fg: string, bg: string): number {
  const [x, y] = [luminance(resolve(tokens, fg)), luminance(resolve(tokens, bg))]
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

const TEXT: [string, string][] = [
  ["foreground", "background"],
  ["foreground", "surface"],
  ["muted-foreground", "background"],
  ["muted-foreground", "surface"],
  ["muted-foreground", "muted"],
  ["primary", "background"],
  ["primary-foreground", "primary"],
  ["destructive-foreground", "destructive"],
  ["destructive-soft-foreground", "destructive-soft"],
  ["success-foreground", "success-soft"],
  ["success-foreground", "success-surface"],
  ["warning-foreground", "warning-soft"],
  ["warning-foreground", "warning-surface"],
  ["twilight-ink", "twilight-canvas"],
  ["twilight-muted", "twilight-canvas"],
]
const NON_TEXT: [string, string][] = [
  ["input", "background"],
  ["ring", "background"],
  ["brand-eyes", "brand-glow"],
]

describe.each([
  ["light", light],
  ["dark", dark],
])("%s appearance", (_name, tokens) => {
  it.each(TEXT)("keeps %s on %s at AA text contrast", (fg, bg) => {
    expect(contrast(tokens, fg, bg)).toBeGreaterThanOrEqual(4.5)
  })
  it.each(NON_TEXT)("keeps %s on %s at non-text contrast", (fg, bg) => {
    expect(contrast(tokens, fg, bg)).toBeGreaterThanOrEqual(3)
  })
})

describe("Twilight identity", () => {
  it("uses Lantern Indigo as the action color", () => {
    expect(light.get("primary")).toBe("oklch(0.47 0.15 278)")
    expect(dark.get("primary")).toBe("oklch(0.74 0.12 278)")
  })

  it("bundles both typefaces instead of loading them from the network", () => {
    expect(entry).toContain('import "@fontsource-variable/figtree"')
    expect(entry).toContain('import "@fontsource-variable/fraunces')
    expect(stylesheet).toContain('--font-sans: "Figtree Variable"')
    expect(stylesheet).toContain('--font-display: "Fraunces Variable"')
    for (const source of [stylesheet, html]) {
      expect(source).not.toMatch(/fonts\.(googleapis|gstatic)\.com|@import url\(/)
    }
  })
})
