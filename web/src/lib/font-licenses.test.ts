import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

// The bundled fonts are OFL-1.1, which requires their notices to travel with the font files.
// Files in web/public are copied into the build, so the notices ship in the image beside the fonts.
describe.each(["fraunces", "figtree"])("%s font licence", (family) => {
  const shipped = new URL(`../../public/licenses/${family}-OFL.txt`, import.meta.url)
  const upstream = new URL(`../../node_modules/@fontsource-variable/${family}/LICENSE`, import.meta.url)

  it("ships the upstream notice unchanged", () => {
    expect(readFileSync(shipped, "utf8")).toBe(readFileSync(upstream, "utf8"))
  })

  it("carries the copyright and the SIL Open Font License", () => {
    const notice = readFileSync(shipped, "utf8")
    expect(notice).toMatch(/^Copyright \d{4} The \w+ Project Authors/)
    expect(notice).toContain("SIL OPEN FONT LICENSE Version 1.1")
  })
})
