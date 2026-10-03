import { appPathForView, type AppView } from "./navigation"

/** The visual review mode is explicit and never changes the installation's data. */
export function isPreviewMode(search: string = typeof window === "undefined" ? "" : window.location.search): boolean {
  const params = new URLSearchParams(search)
  return params.get("preview") === "1" || params.get("dashboardPreview") === "1"
}

export function previewSearchForView(view: AppView, search = ""): string {
  const params = new URLSearchParams(search)
  params.set("preview", "1")
  if (view === "overview") {
    params.set("dashboardPreview", "1")
    params.set("heroPreview", "1")
  } else {
    params.delete("dashboardPreview")
    params.delete("heroPreview")
  }
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ""
}

export function previewPathForView(view: AppView, search = ""): string {
  return `${appPathForView(view)}${previewSearchForView(view, search)}`
}
