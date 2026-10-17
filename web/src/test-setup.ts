import { afterEach, beforeEach } from "vitest"

import { watchUnfilledText, type UnfilledWatch } from "@/i18n/unfilled"

/**
 * Fails any test whose page showed an unfilled `{placeholder}` or a raw catalog key at any moment,
 * whatever put it there. The translator already throws on a parameter it was not given; this also
 * catches what reaches the page without it, such as a value the server left out.
 */
if (typeof document !== "undefined") {
  let watch: UnfilledWatch | undefined
  beforeEach(() => {
    watch = watchUnfilledText(document)
  })
  afterEach(() => {
    const found = watch?.stop() ?? []
    watch = undefined
    if (found.length > 0) {
      throw new Error(`The page showed unfilled words, a {placeholder} or a catalog key:\n${found.map((text) => `  ${text}`).join("\n")}`)
    }
  })
}
