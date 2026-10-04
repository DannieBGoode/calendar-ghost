/* @vitest-environment happy-dom */
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { rich } from "./rich"

describe("rich", () => {
  it("renders known tags and keeps surrounding text", () => {
    const html = renderToStaticMarkup(<p>{rich("Delete <strong>Work</strong> forever", { strong: (text) => <strong>{text}</strong> })}</p>)
    expect(html).toBe("<p>Delete <strong>Work</strong> forever</p>")
  })
  it("renders the text of an unknown tag", () => {
    expect(renderToStaticMarkup(<p>{rich("a <em>b</em>", {})}</p>)).toBe("<p>a b</p>")
  })
})
