/* @vitest-environment happy-dom */

import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

const stylesheet = readFileSync(`${import.meta.dirname}/../index.css`, "utf8")

/** One rule of the stylesheet: its selectors, its declarations, and the at-rules around it. */
type Rule = { selectors: string[]; body: string; within: string[] }

/** Every rule of the stylesheet with the at-rules it sits in, outermost first. */
function parse(css: string): Rule[] {
  const rules: Rule[] = []
  const open: string[] = []
  let text = ""
  for (const char of css.replace(/\/\*[\s\S]*?\*\//g, "")) {
    if (char === "{") {
      open.push(text.trim())
      text = ""
    } else if (char === "}") {
      const prelude = open.pop() ?? ""
      if (!prelude.startsWith("@")) {
        rules.push({ selectors: prelude.split(",").map((part) => part.trim()), body: text, within: [...open] })
      }
      text = ""
    } else {
      text += char
    }
  }
  return rules
}

const RULES = parse(stylesheet)

/**
 * The declarations a selector gets, by property, from the rules that name it: at the top level, or,
 * with `within`, inside the at-rule whose prelude starts so.
 */
function declarations(selector: string, within?: string): Map<string, string> {
  const found = new Map<string, string>()
  for (const rule of RULES) {
    const place = within === undefined ? rule.within.every((at) => at.startsWith("@layer")) : rule.within.some((at) => at.startsWith(within))
    if (!place || !rule.selectors.includes(selector)) continue
    for (const [, property = "", value = ""] of rule.body.matchAll(/([\w-]+)\s*:\s*([^;]+);/g)) found.set(property, value.trim())
  }
  return found
}

/** The style the element `markup` makes gets on a window `width` pixels wide, with the whole stylesheet's cascade. */
function computed(markup: string, width: number): CSSStyleDeclaration {
  const style = document.createElement("style")
  style.textContent = stylesheet
  document.head.replaceChildren(style)
  ;(window as typeof window & { happyDOM: { setViewport: (size: { width: number }) => void } }).happyDOM.setViewport({ width })
  document.body.innerHTML = markup
  return getComputedStyle(document.body.firstElementChild!)
}

describe("Cards", () => {
  it("inset Your plan 1rem on a narrow window, as the Settings groups above it", () => {
    expect(computed('<div class="page-card own-plan-card"></div>', 390).padding).toBe("16px")
  })
})

describe("Data tables", () => {
  it.each([".plan-name", ".plan-holders", ".person-email"])(
    "show %s as ink without an underline at rest, and underline it on hover and keyboard focus",
    (link) => {
      expect(declarations(link).get("text-decoration")).toBe("none")
      expect(declarations(`${link}:hover`).get("text-decoration-line")).toBe("underline")
      expect(declarations(`${link}:focus-visible`).get("text-decoration-line")).toBe("underline")
    },
  )

  it("marks a Plan's row as one target, as Activity's rows are", () => {
    expect(declarations(".plan-row").get("cursor")).toBe("pointer")
  })

  it("gives the Plan column what the fixed columns leave, so no gap opens before the row's menu", () => {
    expect(declarations(".plans-table .col-plan").has("width")).toBe(false)
    for (const column of [".plans-table .col-count", ".plans-table .col-speed", ".plans-table .col-people", ".plans-table .col-actions"]) {
      expect(declarations(column).get("width")).toMatch(/rem$/)
    }
  })

  it("aligns a count's heading with its numbers, and lets a long heading wrap rather than overhang", () => {
    expect(declarations(".plans-table thead th.plans-count").get("text-align")).toBe("right")
    expect(stylesheet).not.toMatch(/\.plans-table th\s*\{\s*white-space:\s*nowrap/)
  })

  it("keeps a Plan's people and its over-limit chip on one line while the catalog is a table", () => {
    expect(
      declarations('.plans-table:not([data-compact="true"]) .plan-people', "@container plans-catalog (min-width: 56rem)").get("flex-wrap"),
    ).toBe("nowrap")
    expect(stylesheet).toContain("@container plans-catalog (max-width: 56rem)")
  })

  it("puts a sync speed's words on the row's line of text, with room after the counts", () => {
    expect(declarations(".plan-speed").get("display")).toBe("inline")
    expect(declarations(".plans-table .plan-col-speed").get("padding-left")).toBeDefined()
  })

  it("sizes the status card's facts to as many as it has, so a missing one leaves no empty cell", () => {
    const facts = declarations(".plans-facts")
    expect(facts.get("grid-auto-flow")).toBe("column")
    expect(facts.get("grid-auto-columns")).toBe("minmax(0, 1fr)")
    expect(facts.has("grid-template-columns")).toBe(false)
    expect(stylesheet).not.toMatch(/\.plans-fact:nth-child/)
  })

  it("keeps a name that heads its row in the table's own type, as the cells beside it", () => {
    for (const heading of [".plans-table tbody th", ".people-table tbody th"]) {
      expect(declarations(heading).get("font-weight")).toBe("inherit")
      expect(declarations(heading).get("text-align")).toBe("left")
    }
  })
})

describe("Menus", () => {
  it("scroll their items inside themselves once capped to the room they have", () => {
    expect(declarations(".overflow-menu-list").get("overflow-y")).toBe("auto")
  })

  it("dim a disabled item's label and icon, never the reason it gives, which stays readable", () => {
    expect(declarations(".overflow-menu-item[aria-disabled]").has("opacity")).toBe(false)
    expect(declarations(".overflow-menu-item[aria-disabled] .overflow-menu-label").get("opacity")).toBe("0.6")
    expect(declarations(".overflow-menu-item[aria-disabled] .overflow-menu-description").has("opacity")).toBe(false)
  })
})

describe("Popovers", () => {
  it("fade a capped chooser's rows at the cut edge while more sit below, and not at their end", () => {
    const fade = declarations(".plan-change-popover[data-capped] .plan-change-options:not([data-end])")
    expect(fade.get("mask-image")).toMatch(/^linear-gradient\(to bottom, .*transparent\)$/)
    expect(declarations(".plan-change-popover .plan-change-options").has("mask-image")).toBe(false)
  })

  it("keep a focused row above that fade: the scroll padding at the cut edge is as tall as the fade", () => {
    const fade = declarations(".plan-change-popover[data-capped] .plan-change-options:not([data-end])")
    expect(fade.get("mask-image")).toContain(`black calc(100% - ${fade.get("scroll-padding-bottom")})`)
  })
})

describe("Side panels", () => {
  it("cap a Plan's panel at the window below where it starts, so its footer with Save is in view", () => {
    expect(declarations(".plan-panel").get("max-height")).toContain("var(--plan-panel-top")
  })
})

describe("The footer", () => {
  it("lays the legal notice out as text, so the space before its license link stays", () => {
    // A flex container trims the space at the end of the text before a link inside it.
    expect(declarations(".app-footer > .legal-notice").get("display")).toBe("block")
  })
})
