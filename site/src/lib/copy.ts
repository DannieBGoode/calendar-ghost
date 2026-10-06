// Copies an element's text for a Copy button. Without the Clipboard API (plain HTTP on a LAN,
// older browsers) it selects the text instead, so the visitor can copy it by hand.
export type CopyResult = "copied" | "selected"

export async function copyOrSelect(element: Element): Promise<CopyResult> {
  try {
    await navigator.clipboard.writeText(element.textContent ?? "")
    return "copied"
  } catch {
    const range = document.createRange()
    range.selectNodeContents(element)
    const selection = window.getSelection()
    selection?.removeAllRanges()
    selection?.addRange(range)
    return "selected"
  }
}

/** Says what happened on the button, and to screen readers through a live region, for a moment. */
export function announceCopy(button: HTMLButtonElement, status: HTMLElement | null, result: CopyResult): void {
  const message = (result === "copied" ? button.dataset.copied : button.dataset.selected) ?? ""
  button.textContent = message
  if (status) status.textContent = message
  window.setTimeout(() => {
    button.textContent = button.dataset.label ?? ""
    if (status) status.textContent = ""
  }, 2500)
}
