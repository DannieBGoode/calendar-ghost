import { afterEach, describe, expect, it, vi } from "vitest"
import { copyOrSelect } from "./copy"

afterEach(() => vi.unstubAllGlobals())

describe("copyOrSelect", () => {
  it("copies the text when the clipboard is there", async () => {
    const writeText = vi.fn(async () => undefined)
    vi.stubGlobal("navigator", { clipboard: { writeText } })
    const code = document.createElement("code")
    code.textContent = "docker compose up -d --build"
    expect(await copyOrSelect(code)).toBe("copied")
    expect(writeText).toHaveBeenCalledWith("docker compose up -d --build")
  })

  it("selects the text when the clipboard is not", async () => {
    vi.stubGlobal("navigator", {})
    const code = document.createElement("code")
    code.textContent = "cp .env.example .env"
    document.body.append(code)
    expect(await copyOrSelect(code)).toBe("selected")
    expect(window.getSelection()?.toString()).toBe("cp .env.example .env")
    code.remove()
  })
})
