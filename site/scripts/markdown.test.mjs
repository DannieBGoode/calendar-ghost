import { describe, expect, it } from "vitest"
import { pageMarkdown } from "./markdown.mjs"

describe("built Markdown", () => {
  it("keeps content, commands, tables and absolute links without page controls or decoration", () => {
    const result = pageMarkdown(`<html><head><link rel="canonical" href="https://calendarghost.com/docs/self-hosting/"></head>
      <body><nav>Global menu</nav><main><nav>Contents</nav><h1>Self-hosting</h1>
      <p>Read <a href="/docs/troubleshooting#logs">the guide</a>.</p>
      <pre><code class="language-sh">docker compose up -d</code></pre>
      <table><thead><tr><th>Provider</th><th>Support</th></tr></thead><tbody><tr><td>Google</td><td>Yes</td></tr></tbody></table>
      <ol><li>First</li><astro-island><astro-slot><li>Second</li><li>Third</li></astro-slot></astro-island></ol>
      <button>Copy</button><div aria-hidden="true">Decoration</div><script>tracker()</script>
      <style>main {color:red}</style><template>Template</template><svg><text>Ghost</text></svg>
      <div class="doc-toc">Local contents</div><p class="doc-source">Edit source</p>
      </main><footer>Footer</footer></body></html>`)
    expect(result).toContain("# Self-hosting")
    expect(result).toContain("[the guide](https://calendarghost.com/docs/troubleshooting#logs)")
    expect(result).toContain("```sh\ndocker compose up -d\n```")
    expect(result).toContain("| Google | Yes |")
    expect(result).toContain("1.  First\n2.  Second\n3.  Third")
    for (const removed of ["Global menu", "Contents", "Copy", "Decoration", "tracker", "color:red", "Template", "Ghost", "Local contents", "Edit source", "Footer"]) {
      expect(result).not.toContain(removed)
    }
  })
})
